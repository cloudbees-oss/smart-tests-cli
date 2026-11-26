package com.launchableinc.ingest.commits;

import static com.google.common.truth.Truth.assertThat;
import static org.junit.Assert.assertThrows;

import java.io.IOException;
import org.junit.Test;

public class EmbeddingAdaptersTest {
  private static EmbeddingConfig config(String provider) {
    return new EmbeddingConfig(provider, "text-embedding-3-small", 1536, 1, "https://llm.example.com/v1/embeddings", "sk-secret");
  }

  @Test
  public void providerNamesAreMatchedIgnoringCaseAndPunctuation() throws IOException {
    for (String provider : new String[] {"OpenAI", "openai", " Open AI ", "open-ai"}) {
      try (EmbeddingAdapter adapter = EmbeddingAdapters.create(config(provider))) {
        assertThat(adapter).isInstanceOf(OpenAiCompatibleAdapter.class);
      }
    }
  }

  @Test
  public void aProviderTheCliDoesNotKnowIsRejected() {
    UnsupportedEmbeddingException e =
        assertThrows(UnsupportedEmbeddingException.class, () -> EmbeddingAdapters.create(config("Some New Provider")));

    assertThat(e).hasMessageThat().contains("Some New Provider");
    assertThrows(UnsupportedEmbeddingException.class, () -> EmbeddingAdapters.create(config(null)));
  }

  @Test
  public void anEndpointNeedsAnHttpOrHttpsScheme() {
    assertThat(EmbeddingAdapters.endpointProblem("https://api.openai.com/v1/embeddings")).isNull();
    assertThat(EmbeddingAdapters.endpointProblem("http://localhost:8080/v1/embeddings")).isNull();
    assertThat(EmbeddingAdapters.endpointProblem("  https://api.openai.com/v1/embeddings \n")).isNull();
    assertThat(EmbeddingAdapters.endpointProblem("api.openai.com/v1/embeddings")).contains("must be a full URL");
    assertThat(EmbeddingAdapters.endpointProblem("ftp://api.openai.com/x")).contains("must be a full URL");
  }

  @Test
  public void aMalformedEndpointIsReportedWithoutQuotingIt() {
    String problem = EmbeddingAdapters.endpointProblem("https://exa mple.com/v1?key=secret");

    assertThat(problem).contains("not a valid URL");
    assertThat(problem).doesNotContain("secret"); // the query string can carry a secret
  }

  @Test
  public void onlyPlainHttpIsUnencrypted() {
    assertThat(EmbeddingAdapters.sendsUnencrypted("https://api.openai.com/v1/embeddings")).isFalse();
    assertThat(EmbeddingAdapters.sendsUnencrypted("HTTPS://api.openai.com/v1")).isFalse();

    assertThat(EmbeddingAdapters.sendsUnencrypted("http://llm.example.com/v1")).isTrue();
    assertThat(EmbeddingAdapters.sendsUnencrypted("  http://10.0.0.5/v1 ")).isTrue();
    assertThat(EmbeddingAdapters.sendsUnencrypted("HTTP://localhost:11434/v1")).isTrue();
  }
}
