package com.launchableinc.ingest.commits;

import static com.google.common.truth.Truth.assertThat;

import java.io.File;
import org.eclipse.jgit.api.Git;
import org.eclipse.jgit.lib.ObjectId;
import org.eclipse.jgit.lib.ObjectInserter;
import org.eclipse.jgit.lib.Repository;
import org.junit.Rule;
import org.junit.Test;
import org.junit.rules.TemporaryFolder;
import org.junit.runner.RunWith;
import org.junit.runners.JUnit4;

import static org.eclipse.jgit.lib.Constants.OBJ_BLOB;

@RunWith(JUnit4.class)
public class GitFileTest {

  @Rule public TemporaryFolder tmp = new TemporaryFolder();

  @Test
  public void isText_textFile_returnsTrue() throws Exception {
    assertThat(gitFileWithContent("public class Hello {}".getBytes()).isText()).isTrue();
  }

  @Test
  public void isText_binaryFile_returnsFalse() throws Exception {
    // 0xFF 0xFE is invalid UTF-8
    assertThat(gitFileWithContent(new byte[]{(byte) 0xFF, (byte) 0xFE, 0x00, 0x01}).isText()).isFalse();
  }

  @Test
  public void isText_utf8MultiByte_returnsTrue() throws Exception {
    assertThat(gitFileWithContent("日本語テスト".getBytes(java.nio.charset.StandardCharsets.UTF_8)).isText()).isTrue();
  }

  private GitFile gitFileWithContent(byte[] content) throws Exception {
    File repoDir = tmp.newFolder();
    try (Git git = Git.init().setDirectory(repoDir).call()) {
      Repository repo = git.getRepository();
      ObjectId blobId;
      try (ObjectInserter inserter = repo.newObjectInserter()) {
        blobId = inserter.insert(OBJ_BLOB, content);
        inserter.flush();
      }
      return new GitFile("test", "file", blobId, repo::newObjectReader);
    }
  }
}
