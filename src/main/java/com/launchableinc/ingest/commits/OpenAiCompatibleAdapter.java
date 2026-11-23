package com.launchableinc.ingest.commits;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import java.io.IOException;
import java.net.UnknownHostException;
import java.nio.charset.StandardCharsets;
import java.security.cert.CertificateException;
import java.util.ArrayList;
import java.util.Collections;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import javax.net.ssl.SSLPeerUnverifiedException;
import org.apache.http.client.ClientProtocolException;
import org.apache.http.client.methods.CloseableHttpResponse;
import org.apache.http.client.methods.HttpPost;
import org.apache.http.entity.StringEntity;
import org.apache.http.impl.client.CloseableHttpClient;
import org.apache.http.util.EntityUtils;

/**
 * Calls an OpenAI-compatible embeddings endpoint. The request and response shapes mirror what the
 * server's own embedder (langchain4j-open-ai) sends and reads:
 *
 * <pre>
 * POST {endpoint}            the full URL, for example https://api.openai.com/v1/embeddings
 * Authorization: Bearer {key}
 * {"model": "...", "input": ["text", ...]}
 *
 * {"data": [{"index": 0, "embedding": [0.1, ...]}, ...], ...}
 * </pre>
 *
 * <p>The HTTP client here is deliberately not the one that talks to Smart Tests, so Smart Tests
 * credentials can never be sent to the customer's provider.
 */
class OpenAiCompatibleAdapter implements EmbeddingAdapter {
  private static final ObjectMapper MAPPER = new ObjectMapper();
  private static final int MAX_ERROR_BODY_CHARS = 500;

  private final CloseableHttpClient http;
  private final String url;
  private final String apiKey;
  private final String modelName;

  OpenAiCompatibleAdapter(CloseableHttpClient http, String endpoint, String apiKey, String modelName) {
    this.http = http;
    // The customer gives the full URL of the embeddings endpoint, so it is used exactly as it is, query
    // string included (Azure-style URLs end in ?api-version=...). Only stray whitespace from copying
    // is dropped.
    this.url = endpoint.trim();
    this.apiKey = apiKey;
    this.modelName = modelName;
  }

  @Override
  public List<float[]> embed(List<String> texts) throws IOException {
    Map<String, Object> body = new LinkedHashMap<>();
    body.put("model", modelName);
    body.put("input", texts);

    HttpPost post = new HttpPost(url);
    post.setHeader("Authorization", "Bearer " + apiKey);
    post.setHeader("Content-Type", "application/json");
    post.setEntity(new StringEntity(MAPPER.writeValueAsString(body), StandardCharsets.UTF_8));

    int status;
    String responseBody;
    try (CloseableHttpResponse response = http.execute(post)) {
      status = response.getStatusLine().getStatusCode();
      responseBody =
          response.getEntity() == null ? "" : EntityUtils.toString(response.getEntity(), StandardCharsets.UTF_8);
    } catch (IOException e) {
      // The message of a connection error never contains request headers, so it is safe to show.
      throw new EmbeddingException(
          -1, "Request to " + url + " failed: " + BatchEmbedder.describe(e) + hint(e), isTransient(e), false);
    }

    if (status >= 400) {
      throw new EmbeddingException(
          status,
          "The embedding endpoint " + url + " returned HTTP " + status + ": " + abbreviate(responseBody)
              + (status == 404
                  ? "\nSMART_TESTS_EMBEDDING_ENDPOINT must be the full URL of the embeddings endpoint,"
                      + " for example https://api.openai.com/v1/embeddings"
                  : ""),
          status == 429 || status >= 500,
          responseBody.contains("context_length_exceeded"));
    }
    return parse(responseBody, texts.size());
  }

  /**
   * Whether trying again could help. A refused connection, a timeout or a dropped connection might
   * pass. A malformed endpoint, an unknown host or an untrusted certificate never will, and retrying
   * those would only keep the user waiting.
   */
  private static boolean isTransient(IOException e) {
    return !(e instanceof ClientProtocolException
        || e instanceof UnknownHostException
        || e instanceof SSLPeerUnverifiedException
        || hasCause(e, CertificateException.class));
  }

  /** Points at the likely fix for the failures that are not transient. */
  private static String hint(IOException e) {
    if (hasCause(e, CertificateException.class) || e instanceof SSLPeerUnverifiedException) {
      return ". The endpoint's certificate is not trusted. Trust it with a JVM truststore, for example"
          + " JAVA_TOOL_OPTIONS=-Djavax.net.ssl.trustStore=<file>. -skip-cert-verification does not apply to this call";
    }
    if (e instanceof ClientProtocolException) {
      return ". Check that SMART_TESTS_EMBEDDING_ENDPOINT is a full https:// URL";
    }
    if (e instanceof UnknownHostException) {
      return ". Check the host name in SMART_TESTS_EMBEDDING_ENDPOINT";
    }
    return "";
  }

  private static boolean hasCause(Throwable e, Class<? extends Throwable> type) {
    for (Throwable t = e; t != null; t = t.getCause() == t ? null : t.getCause()) {
      if (type.isInstance(t)) {
        return true;
      }
    }
    return false;
  }

  private List<float[]> parse(String responseBody, int expected) throws EmbeddingException {
    JsonNode data;
    try {
      JsonNode root = MAPPER.readTree(responseBody);
      data = root == null ? null : root.get("data");
    } catch (IOException e) {
      throw new EmbeddingException(200, "The embedding endpoint returned a response that is not JSON", false, false);
    }
    if (data == null || !data.isArray() || data.size() != expected) {
      throw new EmbeddingException(
          200,
          "The embedding endpoint returned "
              + (data == null || !data.isArray() ? "no data array" : data.size() + " embeddings")
              + " for " + expected + " inputs",
          false,
          false);
    }

    // Place the rows by their `index` only when the indexes are exactly 0..n-1, each used once. Some
    // OpenAI-compatible servers send odd or repeated indexes while keeping the rows in order, and the
    // server's own embedder (langchain4j) simply trusts the response order, so fall back to that.
    boolean placeByIndex = hasEachIndexExactlyOnce(data, expected);

    List<float[]> vectors = new ArrayList<>(Collections.nCopies(expected, (float[]) null));
    int position = 0;
    for (JsonNode row : data) {
      JsonNode embedding = row.get("embedding");
      if (embedding == null || !embedding.isArray()) {
        throw new EmbeddingException(200, "The embedding endpoint returned a malformed row", false, false);
      }
      float[] vector = new float[embedding.size()];
      for (int i = 0; i < vector.length; i++) {
        JsonNode number = embedding.get(i);
        if (!number.isNumber()) {
          throw new EmbeddingException(
              200, "The embedding endpoint returned a vector with a value that is not a number", false, false);
        }
        vector[i] = (float) number.asDouble();
      }
      vectors.set(placeByIndex ? row.get("index").asInt() : position, vector);
      position++;
    }
    return vectors;
  }

  /** True if every row has an integer `index` and together they are exactly 0..expected-1, each once. */
  private static boolean hasEachIndexExactlyOnce(JsonNode data, int expected) {
    boolean[] seen = new boolean[expected];
    for (JsonNode row : data) {
      JsonNode index = row.get("index");
      if (index == null || !index.isInt() || index.asInt() < 0 || index.asInt() >= expected || seen[index.asInt()]) {
        return false;
      }
      seen[index.asInt()] = true;
    }
    return true; // `expected` rows, no repeats, all in range: that is every index exactly once
  }

  private static String abbreviate(String s) {
    return s.length() <= MAX_ERROR_BODY_CHARS ? s : s.substring(0, MAX_ERROR_BODY_CHARS) + "...";
  }

  @Override
  public void close() throws IOException {
    http.close();
  }
}
