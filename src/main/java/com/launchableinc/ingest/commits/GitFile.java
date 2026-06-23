package com.launchableinc.ingest.commits;

import org.eclipse.jgit.lib.ObjectId;
import org.eclipse.jgit.lib.ObjectLoader;
import org.eclipse.jgit.lib.ObjectReader;

import java.io.IOException;
import java.io.InputStreamReader;
import java.io.OutputStream;
import java.io.Reader;
import java.nio.charset.CharacterCodingException;
import java.nio.charset.StandardCharsets;

import static java.nio.charset.StandardCharsets.UTF_8;
import static org.eclipse.jgit.lib.Constants.*;

/**
 * Represents a file in a Git repository, and encapsulates the read access for convenience.
 */
final class GitFile implements VirtualFile {
  final String repo;
  final String path;
  final ObjectId blob;
  private final ObjectReader objectReader;

  public GitFile(String repo, String path, ObjectId blob, ObjectReader objectReader) {
    this.repo = repo;
    this.path = path;
    this.blob = blob;
    this.objectReader = objectReader;
  }

  @Override
  public String repo() {
    return repo;
  }

  @Override
  public String path() {
    return path;
  }

  @Override
  public ObjectId blob() {
    return blob;
  }

  public long size() throws IOException {
    return open().getSize();
  }

  @Override
  public void writeTo(OutputStream os) throws IOException {
    open().copyTo(os);
  }

  private ObjectLoader open() throws IOException {
    return objectReader.open(blob, OBJ_BLOB);
  }

  /**
   * Returns true if the file is a text file.
   *
   * <p>I briefly thought about whether it makes sense to deal with the platform default encoding, then
   * decided not. In the unlikely event we decide to deal with this, it'd be best to convert to UTF-8 on the CLI
   * side since encoding codec is not portable.
   */
  public boolean isText() throws IOException {
    try {
      char[] c = new char[1024];
      try (Reader r = new InputStreamReader(open().openStream(), UTF_8)) {
        while (r.read(c)!= -1) {
          // Read the file until EOF.
        }
      }
      return true;
    } catch (CharacterCodingException e) {
      return false;
    }
  }
}
