package com.launchableinc.ingest.commits;

import com.google.common.io.ByteStreams;
import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.io.OutputStream;
import java.nio.charset.StandardCharsets;
import java.util.Set;
import org.eclipse.jgit.diff.DiffEntry;
import org.eclipse.jgit.diff.DiffFormatter;
import org.eclipse.jgit.diff.Edit;
import org.eclipse.jgit.diff.EditList;
import org.eclipse.jgit.diff.RawText;
import org.eclipse.jgit.lib.Repository;

/**
 * {@link DiffFormatter} that counts the number of lines edited as opposed to print out the actual
 * diff. For config/schema files (build configs, migrations, schemas, etc.) it also captures the
 * diff hunk text so the server can embed the delta instead of the stale full-file content.
 *
 * <p>Use {@link #create(Repository)} to construct instances.
 */
class CountingDiffFormatter extends DiffFormatter {
  private int add;
  private int del;

  /**
   * File extensions that identify config/schema files. When a changed file matches, the diff
   * hunk is captured and sent as {@link JSFileChange#getDiffContent()} so the server can run
   * two-hop diff embedding at subset time.
   */
  private static final Set<String> CONFIG_OR_SCHEMA_EXTENSIONS =
      Set.of("xml", "gradle", "toml", "properties", "yml", "yaml", "env", "sql", "proto",
          "thrift", "graphqls", "graphql");

  private static final Set<String> CONFIG_OR_SCHEMA_EXACT_NAMES =
      Set.of("requirements.txt", "package.json", "package-lock.json", "go.mod", "go.sum",
          "Dockerfile", "Gemfile", "Gemfile.lock", "Pipfile", "Pipfile.lock",
          "Cargo.toml", "Cargo.lock", "build.sbt", "pom.xml");

  /**
   * Switching stream passed to the superclass constructor. Its delegate is swapped per {@link
   * #process(DiffEntry)} call so we can capture or discard the diff output without recreating the
   * formatter.
   */
  private final SwitchableOutputStream switchableOut;

  /**
   * Whether to capture diff hunks for config/schema files. {@code false} when the server hasn't
   * advertised any prior commits (i.e. this is the first time the repository is recorded), since
   * there's no previous build for the server to diff against.
   */
  private final boolean captureDiffContent;

  private CountingDiffFormatter(Repository git, SwitchableOutputStream out, boolean captureDiffContent) {
    super(out);
    setRepository(git);
    this.switchableOut = out;
    this.captureDiffContent = captureDiffContent;
  }

  static CountingDiffFormatter create(Repository git, boolean captureDiffContent) {
    return new CountingDiffFormatter(git, new SwitchableOutputStream(), captureDiffContent);
  }

  /** Entry point to compute a file level change. */
  JSFileChange process(DiffEntry de) throws IOException {
    add = 0;
    del = 0;

    String effectivePath = "/dev/null".equals(de.getNewPath()) ? de.getOldPath() : de.getNewPath();
    ByteArrayOutputStream diffCapture = null;
    if (captureDiffContent && isConfigOrSchemaFile(effectivePath)) {
      diffCapture = new ByteArrayOutputStream();
      switchableOut.delegate = diffCapture;
    } else {
      switchableOut.delegate = ByteStreams.nullOutputStream();
    }

    // This call internally reaches format(EditList, RawText, RawText) which counts lines.
    format(de);

    JSFileChange fc = new JSFileChange();
    fc.setLinesAdded(add);
    fc.setLinesDeleted(del);
    fc.setPath(de.getOldPath());
    fc.setPathTo(de.getNewPath());
    fc.setStatus(de.getChangeType().toString());

    if (diffCapture != null && diffCapture.size() > 0) {
      fc.setDiffContent(stripDiffHeader(diffCapture.toString(StandardCharsets.UTF_8)));
    }

    return fc;
  }

  /**
   * Removes the git extended-header lines ({@code diff --git}, {@code index ...}, {@code ---},
   * {@code +++}) from a unified diff, keeping only the {@code @@} hunk markers and the actual
   * +/-/context content lines. The header lines carry no content signal — {@link
   * JSFileChange#getPath()}, {@link JSFileChange#getPathTo()}, and {@link
   * JSFileChange#getStatus()} already convey what they encode — so keeping them would add noise
   * that whole-file content (sent as raw bytes, with no such wrapper syntax) never has.
   */
  private static String stripDiffHeader(String diff) {
    StringBuilder sb = new StringBuilder(diff.length());
    for (String line : diff.split("\n", -1)) {
      if (line.startsWith("diff --git ")
          || line.startsWith("index ")
          || line.startsWith("--- ")
          || line.startsWith("+++ ")) {
        continue;
      }
      sb.append(line).append('\n');
    }
    if (sb.length() > 0) {
      sb.setLength(sb.length() - 1);
    }
    return sb.toString();
  }

  @Override
  public void format(EditList edits, RawText a, RawText b) throws IOException {
    for (Edit edit : edits) {
      del += edit.getEndA() - edit.getBeginA();
      add += edit.getEndB() - edit.getBeginB();
    }
    // Write the actual hunk content to the output stream. When capturing an config/schema
    // file, this populates diffCapture with the +/- lines the server will embed. Without this call
    // the capture contains only the file header (diff --git / --- / +++) but no changed lines,
    // which produces a near-useless embedding signal.
    super.format(edits, a, b);
  }

  /**
   * Returns true if the file at {@code path} is an config/schema file — one whose full content
   * is not the right embedding signal (build configs, migrations, schemas, etc.).
   */
  static boolean isConfigOrSchemaFile(String path) {
    if (path == null || path.isEmpty()) return false;
    String name = path.contains("/") ? path.substring(path.lastIndexOf('/') + 1) : path;
    if (CONFIG_OR_SCHEMA_EXACT_NAMES.contains(name)) return true;
    int dot = name.lastIndexOf('.');
    if (dot >= 0) {
      String ext = name.substring(dot + 1).toLowerCase();
      if (CONFIG_OR_SCHEMA_EXTENSIONS.contains(ext)) return true;
    }
    if (path.contains(".github/workflows/")) return true;
    if (name.equals("Jenkinsfile") || name.endsWith(".jenkinsfile")) return true;
    return false;
  }

  /** An {@link OutputStream} whose underlying target can be swapped between calls. */
  private static final class SwitchableOutputStream extends OutputStream {
    OutputStream delegate = ByteStreams.nullOutputStream();

    @Override
    public void write(int b) throws IOException {
      delegate.write(b);
    }

    @Override
    public void write(byte[] b, int off, int len) throws IOException {
      delegate.write(b, off, len);
    }

    @Override
    public void flush() throws IOException {
      delegate.flush();
    }
  }
}
