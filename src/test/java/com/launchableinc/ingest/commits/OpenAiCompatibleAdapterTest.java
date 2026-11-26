package com.launchableinc.ingest.commits;

import static com.google.common.truth.Truth.assertThat;
import static org.junit.Assert.assertThrows;
import static org.mockserver.model.HttpRequest.request;
import static org.mockserver.model.HttpResponse.response;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import java.io.IOException;
import java.util.Arrays;
import java.util.List;
import org.apache.http.client.config.CookieSpecs;
import org.apache.http.impl.client.CloseableHttpClient;
import org.apache.http.impl.client.HttpClients;
import org.junit.After;
import org.junit.Before;
import org.junit.Rule;
import org.junit.Test;
import org.mockserver.client.MockServerClient;
import org.mockserver.junit.MockServerRule;
import org.mockserver.model.HttpRequest;

public class OpenAiCompatibleAdapterTest {
  private static final String API_KEY = "sk-secret-key";

  @Rule public MockServerRule mockServerRule = new MockServerRule(this);
  private MockServerClient mockServerClient;

  private CloseableHttpClient http;
  private OpenAiCompatibleAdapter adapter;

  @Before
  public void setUp() {
    http = HttpClients.createDefault();
    adapter = new OpenAiCompatibleAdapter(http, url(), API_KEY, "text-embedding-3-small");
  }

  @After
  public void tearDown() throws IOException {
    http.close();
  }

  /** The full URL of the embeddings endpoint, as the customer gives it. */
  private String url() {
    return "http://localhost:" + mockServerClient.remoteAddress().getPort() + "/v1/embeddings";
  }

  private HttpRequest embeddingsRequest() {
    return request().withMethod("POST").withPath("/v1/embeddings");
  }

  private EmbeddingException failureOf(OpenAiCompatibleAdapter adapter) {
    return assertThrows(EmbeddingException.class, () -> adapter.embed(Arrays.asList("a")));
  }

  @Test
  public void sendsTheModelAndTheInputsWithABearerKey() throws Exception {
    mockServerClient
        .when(embeddingsRequest())
        .respond(
            response()
                .withBody("{\"data\":[{\"index\":0,\"embedding\":[1.0,2.0]},{\"index\":1,\"embedding\":[3.0,4.0]}]}"));

    List<float[]> vectors = adapter.embed(Arrays.asList("first", "second"));

    HttpRequest sent = mockServerClient.retrieveRecordedRequests(embeddingsRequest())[0];
    assertThat(sent.getFirstHeader("Authorization")).isEqualTo("Bearer " + API_KEY);
    assertThat(sent.getFirstHeader("Content-Type")).contains("application/json");
    JsonNode body = new ObjectMapper().readTree(sent.getBodyAsString());
    assertThat(body.get("model").asText()).isEqualTo("text-embedding-3-small");
    assertThat(body.get("input").get(0).asText()).isEqualTo("first");
    assertThat(body.get("input").get(1).asText()).isEqualTo("second");
    assertThat(body.has("dimensions")).isFalse(); // the server's own embedder never sends it either
    assertThat(vectors.get(0)).isEqualTo(new float[] {1, 2});
    assertThat(vectors.get(1)).isEqualTo(new float[] {3, 4});
  }

  @Test
  public void usesTheUrlExactlyAsGivenIncludingTheQueryString() throws Exception {
    mockServerClient
        .when(embeddingsRequest().withQueryStringParameter("api-version", "2024-02-01"))
        .respond(response().withBody("{\"data\":[{\"index\":0,\"embedding\":[1.0]}]}"));
    OpenAiCompatibleAdapter withQuery =
        new OpenAiCompatibleAdapter(http, "  " + url() + "?api-version=2024-02-01 \n", API_KEY, "m");

    assertThat(withQuery.embed(Arrays.asList("a"))).hasSize(1);
  }

  @Test
  public void putsRowsBackInInputOrderUsingTheirIndex() throws Exception {
    mockServerClient
        .when(embeddingsRequest())
        .respond(response().withBody("{\"data\":[{\"index\":1,\"embedding\":[3.0]},{\"index\":0,\"embedding\":[1.0]}]}"));

    List<float[]> vectors = adapter.embed(Arrays.asList("first", "second"));

    assertThat(vectors.get(0)).isEqualTo(new float[] {1});
    assertThat(vectors.get(1)).isEqualTo(new float[] {3});
  }

  @Test
  public void fallsBackToTheResponseOrderWhenTheIndexesAreNotEachUsedOnce() throws Exception {
    // some compatible servers keep the rows in order but send the same index for all of them
    mockServerClient
        .when(embeddingsRequest())
        .respond(response().withBody("{\"data\":[{\"index\":0,\"embedding\":[1.0]},{\"index\":0,\"embedding\":[2.0]}]}"));

    List<float[]> vectors = adapter.embed(Arrays.asList("first", "second"));

    assertThat(vectors.get(0)).isEqualTo(new float[] {1});
    assertThat(vectors.get(1)).isEqualTo(new float[] {2});
  }

  @Test
  public void ignoresFieldsItDoesNotKnow() throws Exception {
    mockServerClient
        .when(embeddingsRequest())
        .respond(
            response()
                .withBody(
                    "{\"object\":\"list\",\"model\":\"x\",\"usage\":{\"total_tokens\":3},"
                        + "\"data\":[{\"object\":\"embedding\",\"index\":0,\"embedding\":[1.0]}]}"));

    assertThat(adapter.embed(Arrays.asList("a"))).hasSize(1);
  }

  @Test
  public void aValueThatIsNotANumberIsAnErrorNotAZero() {
    mockServerClient
        .when(embeddingsRequest())
        .respond(response().withBody("{\"data\":[{\"index\":0,\"embedding\":[1.0,\"oops\"]}]}"));

    EmbeddingException e = failureOf(adapter);

    assertThat(e).hasMessageThat().contains("not a number");
    assertThat(e.retryable).isFalse();
  }

  @Test
  public void anAnswerWithTheWrongNumberOfRowsIsAnError() {
    mockServerClient.when(embeddingsRequest()).respond(response().withBody("{\"data\":[]}"));

    assertThat(failureOf(adapter)).hasMessageThat().contains("0 embeddings for 1 inputs");
  }

  @Test
  public void rateLimitingAndServerErrorsAreRetryable() {
    for (int status : new int[] {429, 500, 503}) {
      mockServerClient.reset();
      mockServerClient.when(embeddingsRequest()).respond(response().withStatusCode(status).withBody("slow down"));

      EmbeddingException e = failureOf(adapter);

      assertThat(e.retryable).isTrue();
      assertThat(e.statusCode).isEqualTo(status);
    }
  }

  @Test
  public void otherClientErrorsAreNotRetryable() {
    mockServerClient.when(embeddingsRequest()).respond(response().withStatusCode(401).withBody("bad key"));

    EmbeddingException e = failureOf(adapter);

    assertThat(e.retryable).isFalse();
    assertThat(e.contextLengthExceeded).isFalse();
  }

  @Test
  public void anOverlongInputIsFlaggedAndNotRetryable() {
    mockServerClient
        .when(embeddingsRequest())
        .respond(
            response()
                .withStatusCode(400)
                .withBody("{\"error\":{\"code\":\"context_length_exceeded\",\"message\":\"too long\"}}"));

    EmbeddingException e = failureOf(adapter);

    assertThat(e.contextLengthExceeded).isTrue();
    assertThat(e.retryable).isFalse();
  }

  @Test
  public void aNotFoundAnswerSaysThatTheEndpointMustBeTheFullUrl() {
    mockServerClient.when(embeddingsRequest()).respond(response().withStatusCode(404).withBody("no such path"));

    assertThat(failureOf(adapter)).hasMessageThat().contains("full URL of the embeddings endpoint");
  }

  @Test
  public void aConnectionFailureIsRetryable() {
    EmbeddingException e = failureOf(new OpenAiCompatibleAdapter(http, "http://localhost:1/v1/embeddings", API_KEY, "m"));

    assertThat(e.retryable).isTrue();
    assertThat(e.statusCode).isEqualTo(-1);
  }

  @Test
  public void aUrlWithoutASchemeIsNotRetryableAndSaysWhatToCheck() {
    EmbeddingException e = failureOf(new OpenAiCompatibleAdapter(http, "llm.example.com/v1/embeddings", API_KEY, "m"));

    assertThat(e.retryable).isFalse();
    assertThat(e).hasMessageThat().contains("full https:// URL");
  }

  @Test
  public void theClientThatTalksToTheModelDoesNotKeepOrSendCookies() throws Exception {
    // Providers sit behind services that set cookies meant for browsers. The call is authenticated by
    // the key alone, so a cookie must neither be sent back nor make the HTTP client complain about it.
    mockServerClient
        .when(embeddingsRequest())
        .respond(
            response()
                .withHeader("Set-Cookie", "session=abc; Path=/")
                .withBody("{\"data\":[{\"index\":0,\"embedding\":[1.0]}]}"));
    try (CloseableHttpClient plain = EmbeddingAdapters.newPlainHttpClient(CookieSpecs.IGNORE_COOKIES)) {
      OpenAiCompatibleAdapter plainAdapter = new OpenAiCompatibleAdapter(plain, url(), API_KEY, "m");
      plainAdapter.embed(Arrays.asList("a"));
      plainAdapter.embed(Arrays.asList("a"));
    }

    HttpRequest[] sent = mockServerClient.retrieveRecordedRequests(embeddingsRequest());
    assertThat(sent).hasLength(2);
    assertThat(sent[1].getFirstHeader("Cookie")).isEmpty();
  }

  @Test
  public void aProviderThatNeedsCookiesCanKeepThem() throws Exception {
    mockServerClient
        .when(embeddingsRequest())
        .respond(response().withHeader("Set-Cookie", "session=abc; Path=/").withBody("{\"data\":[{\"index\":0,\"embedding\":[1.0]}]}"));
    try (CloseableHttpClient plain = EmbeddingAdapters.newPlainHttpClient(CookieSpecs.STANDARD)) {
      OpenAiCompatibleAdapter plainAdapter = new OpenAiCompatibleAdapter(plain, url(), API_KEY, "m");
      plainAdapter.embed(Arrays.asList("a"));
      plainAdapter.embed(Arrays.asList("a"));
    }

    HttpRequest[] sent = mockServerClient.retrieveRecordedRequests(embeddingsRequest());
    assertThat(sent[1].getFirstHeader("Cookie")).isEqualTo("session=abc");
  }

  @Test
  public void errorMessagesNeverContainTheApiKey() {
    mockServerClient.when(embeddingsRequest()).respond(response().withStatusCode(401).withBody("invalid key"));

    assertThat(failureOf(adapter)).hasMessageThat().doesNotContain(API_KEY);
  }
}
