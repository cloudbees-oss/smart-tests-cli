package com.launchableinc.ingest.commits;

import static org.mockserver.model.HttpRequest.request;
import static org.mockserver.model.HttpResponse.response;

import java.io.File;
import java.net.InetSocketAddress;
import java.net.URL;
import java.nio.file.Files;

import org.eclipse.jgit.api.CommitCommand;
import org.eclipse.jgit.api.Git;
import org.eclipse.jgit.lib.ObjectId;
import org.eclipse.jgit.revwalk.RevCommit;
import org.junit.Rule;
import org.junit.Test;
import org.junit.rules.TemporaryFolder;
import org.junit.runner.RunWith;
import org.junit.runners.JUnit4;
import org.mockserver.client.MockServerClient;
import org.mockserver.junit.MockServerRule;

@RunWith(JUnit4.class)
public class CommitIngesterTest {
  @Rule public TemporaryFolder tmp = new TemporaryFolder();
  @Rule public MockServerRule mockServerRule = new MockServerRule(this);
  private MockServerClient mockServerClient;

  @Test
  public void specifySubmodule() throws Exception {
    File subrepoDir = tmp.newFolder();
    File mainrepoDir = tmp.newFolder();

    RevCommit subCommit;
    try (Git subrepo = Git.init().setDirectory(subrepoDir).call()) {
      Files.writeString(subrepoDir.toPath().resolve("a"), "");
      subCommit = commit(subrepo).setMessage("sub").call();
    }
    RevCommit mainCommit;
    try (Git mainrepo = Git.init().setDirectory(mainrepoDir).call()) {
      mainrepo.submoduleAdd().setPath("sub").setURI(subrepoDir.toURI().toString()).call();
      mainCommit = commit(mainrepo).setMessage("created a submodule").call();
    }

    mockServerClient
        .when(request().withPath("/intake/organizations/testorg/workspaces/testws/commits/latest"))
        .respond(response().withBody("[]"));
    mockServerClient
        .when(request().withPath("/intake/organizations/testorg/workspaces/testws/commits/collect"))
        .respond(
            request -> {
              String body = request.getBodyAsString();
              String subCommitHash = ObjectId.toString(subCommit);
              if (!body.contains(subCommitHash)) {
                return response()
                    .withStatusCode(500)
                    .withBody("Body should contain " + subCommitHash);
              }
              String mainCommitHash = ObjectId.toString(mainCommit);
              if (body.contains(mainCommitHash)) {
                return response()
                    .withStatusCode(500)
                    .withBody("Body should not contain " + mainCommitHash);
              }
              return response().withBody("OK");
            });

    CommitIngester commitIngester = new CommitIngester();
    InetSocketAddress addr = mockServerClient.remoteAddress();
    // Specify submodule as the repository. JGit cannot open this directly, so the code should open
    // the main repository first, then open the submodule.
    commitIngester.repo = new File(mainrepoDir, "sub");
    commitIngester.url =
        new URL(String.format("http://%s:%s/intake/", addr.getHostString(), addr.getPort()));
    commitIngester.launchableToken = "v1:testorg/testws:dummy-token";
    commitIngester.run();
  }

  private CommitCommand commit(Git r) {
    return r.commit().setAll(true).setSign(false);
  }
}
