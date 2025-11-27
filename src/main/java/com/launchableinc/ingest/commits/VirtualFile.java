package com.launchableinc.ingest.commits;

import org.eclipse.jgit.lib.ObjectId;

import java.io.IOException;
import java.io.OutputStream;

public interface VirtualFile {
  /**
   * Repository identifier, unique within the workspace.
   */
  String repo();

  /**
   * Path to the file within the repository.
   */
  String path();

  /**
   * Blob ID of the file content.
   */
  ObjectId blob();

  long size() throws IOException;
  void writeTo(OutputStream os) throws IOException;

  static VirtualFile from(String repo, String path, ObjectId blob, byte[] payload) {
    return new VirtualFile() {

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

      @Override
      public long size() {
        return payload.length;
      }

      @Override
      public void writeTo(OutputStream os) throws IOException {
        os.write(payload);
      }
    };
  }
}
