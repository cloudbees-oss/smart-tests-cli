package com.launchableinc.ingest.commits;

import static com.google.common.truth.Truth.assertThat;
import static org.junit.Assert.assertThrows;
import static org.mockserver.model.HttpRequest.request;
import static org.mockserver.model.HttpResponse.response;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import java.io.ByteArrayOutputStream;
import java.io.File;
import java.io.PrintStream;
import java.net.InetSocketAddress;
import java.net.URL;
import java.nio.file.Files;
import java.util.HashMap;
import java.util.Map;
import java.util.concurrent.atomic.AtomicReference;

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
import org.mockserver.model.HttpRequest;
import org.mockserver.verify.VerificationTimes;

@RunWith(JUnit4.class)
public class MainTest {
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

    Main main = new Main();
    InetSocketAddress addr = mockServerClient.remoteAddress();
    // Specify submodule as the repository. JGit cannot open this directly, so the code should open
    // the main repository first, then open the submodule.
    main.repo = new File(mainrepoDir, "sub");
    main.url =
        new URL(String.format("http://%s:%s/intake/", addr.getHostString(), addr.getPort()));
    main.launchableToken = "v1:testorg/testws:dummy-token";
    main.run();
  }


  // ---- client-side embedding

  private static final String COMMITS = "/intake/organizations/testorg/workspaces/testws/commits/";
  private static final String LLM_KEY = "sk-customers-llm-key";

  /** A repository with one committed text file, and a Main pointed at it and at the mock server. */
  private Main clientEmbeddingMain(Map<String, String> env) throws Exception {
    File repoDir = tmp.newFolder();
    try (Git git = Git.init().setDirectory(repoDir).call()) {
      Files.writeString(repoDir.toPath().resolve("a.txt"), "hello");
      git.add().addFilepattern("a.txt").call();
      commit(git).setMessage("first").call();
    }

    InetSocketAddress addr = mockServerClient.remoteAddress();
    Main main = new Main();
    main.name = "test";
    main.repo = repoDir;
    main.url = new URL(String.format("http://%s:%s/intake/", addr.getHostString(), addr.getPort()));
    main.launchableToken = "v1:testorg/testws:dummy-token";
    main.collectFiles = true;
    main.clientEmbedding = true;
    main.embeddingProvider = "OpenAI";
    main.embeddingModelName = "text-embedding-3-small";
    main.embeddingModelId = 5;
    main.embeddingDimensions = 4;
    main.getenv = env::get;
    return main;
  }

  private String llmEndpoint() {
    InetSocketAddress addr = mockServerClient.remoteAddress();
    return String.format("http://%s:%s/llm/v1/embeddings", addr.getHostString(), addr.getPort());
  }

  private Map<String, String> goodEnvironment() {
    Map<String, String> env = new HashMap<>();
    env.put("SMART_TESTS_EMBEDDING_ENDPOINT", llmEndpoint());
    env.put("SMART_TESTS_EMBEDDING_API_KEY", LLM_KEY);
    return env;
  }

  private void mockSmartTestsServer() {
    mockServerClient.when(request().withPath(COMMITS + "latest")).respond(response().withBody("[]"));
    mockServerClient.when(request().withPath(COMMITS + "collect/tree")).respond(response().withBody("[\"a.txt\"]"));
    mockServerClient
        .when(request().withPath(COMMITS + "collect/summaries"))
        .respond(response().withBody("{\"repoSummary\":\"A test repo\",\"dirSummaries\":{\"\":\"Top level\"}}"));
    mockServerClient.when(request().withPath(COMMITS + "collect")).respond(response().withBody("OK"));
  }

  /** Runs main, and returns what it printed to stdout and to stderr. */
  private String[] runCapturingOutput(Main main) throws Exception {
    PrintStream originalOut = System.out;
    PrintStream originalErr = System.err;
    ByteArrayOutputStream out = new ByteArrayOutputStream();
    ByteArrayOutputStream err = new ByteArrayOutputStream();
    System.setOut(new PrintStream(out, true, "UTF-8"));
    System.setErr(new PrintStream(err, true, "UTF-8"));
    try {
      main.run();
    } finally {
      System.setOut(originalOut);
      System.setErr(originalErr);
    }
    return new String[] {out.toString("UTF-8"), err.toString("UTF-8")};
  }

  private void verifyNoRequest(String path) {
    mockServerClient.verify(request().withPath(path), VerificationTimes.exactly(0));
  }

  @Test
  public void clientEmbeddingEmbedsWithTheCustomersEndpointAndUploadsOnlyVectors() throws Exception {
    mockSmartTestsServer();
    // the customer's model answers [3, 0, 0, 4], which has to be scaled to unit length
    mockServerClient
        .when(request().withMethod("POST").withPath("/llm/v1/embeddings"))
        .respond(response().withBody("{\"data\":[{\"index\":0,\"embedding\":[3.0,0.0,0.0,4.0]}]}"));
    AtomicReference<String> uploaded = new AtomicReference<>();
    mockServerClient
        .when(request().withPath(COMMITS + "collect/embeddings"))
        .respond(
            request -> {
              uploaded.set(request.getBodyAsString());
              return response().withBody("{\"workId\":7}");
            });
    mockServerClient
        .when(request().withPath(COMMITS + "collect/embeddings/work/7"))
        .respond(response().withBody("{\"status\":\"SUCCEEDED\",\"ingestedCount\":1,\"rejectedFiles\":[]}"));

    String[] output = runCapturingOutput(clientEmbeddingMain(goodEnvironment()));

    assertThat(output[0]).contains("uploaded embeddings for 1 file");
    // what the customer's model received: the text the server would embed, with the customer's key
    HttpRequest toModel = mockServerClient.retrieveRecordedRequests(request().withPath("/llm/v1/embeddings"))[0];
    assertThat(toModel.getFirstHeader("Authorization")).isEqualTo("Bearer " + LLM_KEY);
    JsonNode modelBody = new ObjectMapper().readTree(toModel.getBodyAsString());
    assertThat(modelBody.get("input").get(0).asText())
        .isEqualTo("Repository summary: A test repo\nDirectory summary: Top level\nFile name: a.txt\n----\nhello\n");
    // what Smart Tests received: the model details and a unit vector, and never the file's contents
    JsonNode upload = new ObjectMapper().readTree(uploaded.get());
    assertThat(upload.get("modelId").asInt()).isEqualTo(5);
    assertThat(upload.get("dimensions").asInt()).isEqualTo(4);
    JsonNode file = upload.get("files").get(0);
    assertThat(file.get("fileName").asText()).isEqualTo("a.txt");
    assertThat(file.get("blobSha").asText()).hasLength(40);
    assertThat(file.get("embedding").get(0).asDouble()).isWithin(1e-6).of(0.6);
    assertThat(file.get("embedding").get(3).asDouble()).isWithin(1e-6).of(0.8);
    assertThat(uploaded.get()).doesNotContain("hello");
    verifyNoRequest(COMMITS + "collect/files");
    // the commits are recorded last
    mockServerClient.verify(request().withPath(COMMITS + "collect"), VerificationTimes.exactly(1));
    // the customer's key goes only to the customer's endpoint, and Smart Tests credentials never go there
    for (HttpRequest toSmartTests : mockServerClient.retrieveRecordedRequests(request().withPath("/intake/.*"))) {
      assertThat(toSmartTests.toString()).doesNotContain(LLM_KEY);
    }
    assertThat(toModel.toString()).doesNotContain("dummy-token");
  }

  @Test
  public void clientEmbeddingWithoutCredentialsStopsTheRunBeforeAnythingIsSent() throws Exception {
    mockSmartTestsServer();

    EmbeddingRunFailedException e =
        assertThrows(EmbeddingRunFailedException.class, () -> clientEmbeddingMain(new HashMap<>()).run());

    assertThat(e).hasMessageThat().contains("is not set in the environment");
    verifyNoRequest(COMMITS + "collect/tree");
    verifyNoRequest(COMMITS + "collect"); // without embeddings the commits are not recorded either
  }

  @Test
  public void clientEmbeddingWithAProviderTheCliDoesNotKnowStopsTheRun() throws Exception {
    mockSmartTestsServer();
    Main main = clientEmbeddingMain(goodEnvironment());
    main.embeddingProvider = "Some New Provider";

    EmbeddingRunFailedException e = assertThrows(EmbeddingRunFailedException.class, main::run);

    assertThat(e).hasMessageThat().contains("Some New Provider");
    verifyNoRequest(COMMITS + "collect/summaries");
    verifyNoRequest(COMMITS + "collect");
  }

  @Test
  public void aFileTheModelRejectsStopsTheRunAndNoCommitIsRecorded() throws Exception {
    mockSmartTestsServer();
    mockServerClient
        .when(request().withMethod("POST").withPath("/llm/v1/embeddings"))
        .respond(response().withStatusCode(400).withBody("{\"error\":{\"code\":\"invalid_request\"}}"));

    EmbeddingRunFailedException e =
        assertThrows(EmbeddingRunFailedException.class, () -> clientEmbeddingMain(goodEnvironment()).run());

    assertThat(e).hasMessageThat().contains("1 file was skipped");
    verifyNoRequest(COMMITS + "collect/embeddings");
    verifyNoRequest(COMMITS + "collect");
  }

  @Test
  public void anEndpointThatIsNotAUrlStopsTheRunBeforeAnythingIsSent() throws Exception {
    mockSmartTestsServer();
    Map<String, String> env = goodEnvironment();
    env.put("SMART_TESTS_EMBEDDING_ENDPOINT", "api.example.com/v1/embeddings"); // no https://

    EmbeddingRunFailedException e =
        assertThrows(EmbeddingRunFailedException.class, () -> clientEmbeddingMain(env).run());

    assertThat(e).hasMessageThat().contains("Client-side embedding failed");
    assertThat(e).hasMessageThat().contains("SMART_TESTS_EMBEDDING_ENDPOINT must be a full URL");
    assertThat(e).hasMessageThat().doesNotContain(LLM_KEY);
    verifyNoRequest(COMMITS + "latest"); // nothing at all was sent, so no server credits were spent
  }

  @Test
  public void aKeyTheModelRejectsStopsTheRunAndNoCommitIsRecorded() throws Exception {
    mockSmartTestsServer();
    mockServerClient
        .when(request().withMethod("POST").withPath("/llm/v1/embeddings"))
        .respond(response().withStatusCode(401).withBody("invalid key"));

    EmbeddingRunFailedException e =
        assertThrows(EmbeddingRunFailedException.class, () -> clientEmbeddingMain(goodEnvironment()).run());

    assertThat(e).hasMessageThat().contains("HTTP 401");
    verifyNoRequest(COMMITS + "collect/embeddings");
    verifyNoRequest(COMMITS + "collect"); // the commits are only recorded once the files are dealt with
  }

  private CommitCommand commit(Git r) {
    return r.commit().setAll(true).setSign(false);
  }
}
