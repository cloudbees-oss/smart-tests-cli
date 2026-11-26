package com.launchableinc.ingest.commits;

import static com.google.common.truth.Truth.assertThat;
import static org.junit.Assert.assertThrows;

import org.junit.Test;

public class ModelProfilesTest {
  @Test
  public void usesTheServersOwnLimitsForTextEmbedding3Small() {
    ModelProfile profile = ModelProfiles.lookup("text-embedding-3-small");

    assertThat(profile.maxTokensPerInput).isEqualTo(8100);
    assertThat(profile.maxFilesPerRequest).isEqualTo(1900);
    assertThat(profile.maxTokensPerRequest).isEqualTo(210_000);
    assertThat(profile.tokensPerSecond).isEqualTo(150_000);
    assertThat(profile.tokenizer.count("hello world")).isEqualTo(2);
  }

  @Test
  public void theModelNameIsMatchedIgnoringCase() {
    assertThat(ModelProfiles.lookup("Text-Embedding-3-Small").maxTokensPerInput).isEqualTo(8100);
  }

  @Test
  public void aModelTheCliDoesNotKnowIsRejected() {
    UnsupportedEmbeddingException e =
        assertThrows(UnsupportedEmbeddingException.class, () -> ModelProfiles.lookup("ada-001"));

    assertThat(e).hasMessageThat().contains("ada-001");
  }
}
