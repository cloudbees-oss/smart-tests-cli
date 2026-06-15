package com.launchableinc.ingest.commits;

import org.eclipse.jgit.lib.ObjectId;
import org.eclipse.jgit.lib.ObjectLoader;
import org.eclipse.jgit.lib.ObjectReader;

import java.io.IOException;
import java.io.OutputStream;
import java.nio.ByteBuffer;
import java.nio.charset.CharacterCodingException;
import java.nio.charset.CodingErrorAction;
import java.util.function.Supplier;

import static java.nio.charset.StandardCharsets.UTF_8;
import static org.eclipse.jgit.lib.Constants.OBJ_BLOB;

/**
 * Represents a file in a Git repository, and encapsulates the read access for convenience.
 */
final class GitFile implements VirtualFile {
  final String repo;
  final String path;
  final ObjectId blob;
  // ObjectReader is not thread-safe, so we use Supplier to get a new instance per thread.
  private final Supplier<ObjectReader> objectReader;

  public GitFile(String repo, String path, ObjectId blob, Supplier<ObjectReader> objectReader) {
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
    return objectReader.get().open(blob, OBJ_BLOB);
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
      UTF_8.newDecoder()
          .onMalformedInput(CodingErrorAction.REPORT)
          .onUnmappableCharacter(CodingErrorAction.REPORT)
          .decode(ByteBuffer.wrap(open().getCachedBytes(Integer.MAX_VALUE)));
      return true;
    } catch (CharacterCodingException e) {
      return false;
    }
  }
}
