package com.launchableinc.ingest.commits;

import static com.google.common.truth.Truth.assertThat;

import org.junit.Test;

public class JtokkitTokenCounterTest {
  private final TokenCounter counter = new JtokkitTokenCounter();

  @Test
  public void emptyTextIsZeroTokens() {
    assertThat(counter.count("")).isEqualTo(0);
  }

  @Test
  public void countsTokensNotCharacters() {
    // "hello world" is 11 characters but 2 tokens in the cl100k_base encoding
    assertThat(counter.count("hello world")).isEqualTo(2);
  }

  @Test
  public void longerTextCountsMoreTokens() {
    String small = "int x = 1;";
    String big = small + small + small + small;

    assertThat(counter.count(big)).isGreaterThan(counter.count(small));
  }
}
