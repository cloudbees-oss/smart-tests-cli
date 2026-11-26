package com.launchableinc.ingest.commits;

import static com.google.common.truth.Truth.assertThat;

import org.junit.Test;

public class EmbeddingTextTest {
  /** Counts one token per line, which makes the trimming arithmetic easy to follow. */
  private static final TokenCounter LINES = text -> text.split("\n", -1).length;

  private static String lines(int n) {
    StringBuilder sb = new StringBuilder();
    for (int i = 0; i < n; i++) {
      sb.append(i == 0 ? "" : "\n").append("line").append(i);
    }
    return sb.toString();
  }

  @Test
  public void buildUsesTheServersFormat() {
    assertThat(EmbeddingText.build("R", "D", "src/A.java", "code"))
        .isEqualTo(
            "Repository summary: R\n"
                + "Directory summary: D\n"
                + "File name: src/A.java\n"
                + "----\n"
                + "code\n");
  }

  @Test
  public void aMissingSummaryIsWrittenAsNullLikeTheServerDoes() {
    assertThat(EmbeddingText.build("R", null, "a.txt", "x")).contains("Directory summary: null\n");
  }

  @Test
  public void textUnderTheLimitIsReturnedUnchanged() {
    String text = lines(10);

    assertThat(EmbeddingText.fitToLimit(text, LINES, 50)).isEqualTo(text);
  }

  @Test
  public void overlongTextLosesThirtyTrailingLinesPerRoundUntilItFits() {
    // 100 lines -> 70 -> 40, and 40 fits in 50
    String trimmed = EmbeddingText.fitToLimit(lines(100), LINES, 50);

    assertThat(trimmed).isEqualTo(lines(40));
  }

  @Test
  public void textThatTrimsAwayToNothingIsDropped() {
    // 40 lines with a limit of 5: 40 -> 10 -> 0 lines, which is empty
    assertThat(EmbeddingText.fitToLimit(lines(40), LINES, 5)).isNull();
  }

  @Test
  public void removeLastLinesKeepsEverythingWhenThereAreFewerLinesThanRequested() {
    assertThat(EmbeddingText.removeLastLines("a\nb", 30)).isEmpty();
    assertThat(EmbeddingText.removeLastLines("a\nb\nc", 1)).isEqualTo("a\nb");
  }
}
