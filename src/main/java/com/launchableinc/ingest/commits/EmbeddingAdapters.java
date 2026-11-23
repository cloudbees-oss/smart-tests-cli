package com.launchableinc.ingest.commits;

import java.net.URI;
import java.net.URISyntaxException;
import java.util.Locale;
import org.apache.http.client.config.CookieSpecs;
import org.apache.http.client.config.RequestConfig;
import org.apache.http.impl.client.CloseableHttpClient;
import org.apache.http.impl.client.HttpClientBuilder;

/** Picks the {@link EmbeddingAdapter} for a provider. */
class EmbeddingAdapters {
  private static final int CONNECT_TIMEOUT_MILLIS = 10_000;
  /** Embedding a request of 200,000 tokens can take a while. */
  private static final int READ_TIMEOUT_MILLIS = 120_000;

  private EmbeddingAdapters() {}

  /**
   * @throws UnsupportedEmbeddingException if the CLI does not know the provider
   */
  static EmbeddingAdapter create(EmbeddingConfig config) {
    switch (normalize(config.provider)) {
      case "openai":
        return new OpenAiCompatibleAdapter(
            newPlainHttpClient(CookieSpecs.IGNORE_COOKIES), config.endpoint, config.apiKey(), config.modelName);
      default:
        // "Azure OpenAI" lands here on purpose: its URL layout and auth header differ from plain
        // OpenAI, and that has not been verified against a real endpoint.
        throw new UnsupportedEmbeddingException(
            "The embedding provider '" + config.provider + "' is not supported by this version of the CLI.");
    }
  }

  /**
   * Whether the endpoint can be used at all: a URL with an http or https scheme. The URL is not quoted
   * in the answer, because it can carry a secret in its query string.
   *
   * @return what is wrong with the endpoint, or null if it can be used
   */
  static String endpointProblem(String endpoint) {
    URI uri;
    try {
      uri = new URI(endpoint.trim());
    } catch (URISyntaxException e) {
      return "SMART_TESTS_EMBEDDING_ENDPOINT is not a valid URL (" + e.getReason() + ")";
    }
    String scheme = uri.getScheme();
    if ("https".equalsIgnoreCase(scheme) || "http".equalsIgnoreCase(scheme)) {
      return null;
    }
    return "SMART_TESTS_EMBEDDING_ENDPOINT must be a full URL starting with https://, for example"
        + " https://api.openai.com/v1/embeddings";
  }

  /**
   * Whether the API key and the contents of the customer's files would travel unencrypted, which is
   * plain http. Providers all use https, but a gateway inside a private network might not, and that
   * is the customer's decision, so this only warrants a warning.
   */
  static boolean sendsUnencrypted(String endpoint) {
    return endpoint.trim().toLowerCase(Locale.ROOT).startsWith("http://");
  }

  /** Lower-cases and drops everything that is not a letter or a digit: "Azure OpenAI" becomes "azureopenai". */
  static String normalize(String s) {
    return s == null ? "" : s.toLowerCase(Locale.ROOT).replaceAll("[^a-z0-9]", "");
  }

  /**
   * A plain client that carries no Smart Tests credentials. It honors the proxy system properties.
   *
   * @param cookieSpec what to do with cookies, a {@link CookieSpecs} constant. Each provider chooses
   *     for itself: {@link CookieSpecs#IGNORE_COOKIES} for a stateless API, {@link CookieSpecs#STANDARD}
   *     for a gateway that needs cookies such as a sticky-session affinity cookie sent back.
   */
  static CloseableHttpClient newPlainHttpClient(String cookieSpec) {
    return HttpClientBuilder.create()
        .useSystemProperties()
        .setDefaultRequestConfig(
            RequestConfig.custom()
                .setCookieSpec(cookieSpec)
                .setConnectTimeout(CONNECT_TIMEOUT_MILLIS)
                .setSocketTimeout(READ_TIMEOUT_MILLIS)
                .build())
        .build();
  }
}
