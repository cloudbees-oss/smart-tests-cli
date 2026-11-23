package com.launchableinc.ingest.commits;

import java.util.Arrays;

/**
 * Builds the text that gets embedded for one file, mirroring the server's own embedder
 * (FileEmbeddingService) so vectors from client mode and server mode are comparable.
 */
class EmbeddingText {
  /** Server's per-input token cap for text-embedding-3-small (8192 minus a safety margin). */
  static final int MAX_TOKENS = 8100;

  /** How many trailing lines are dropped per round when the text is over the limit. */
  private static final int TRIM_LINES_PER_ROUND = 30;

  private EmbeddingText() {}

  /** A null summary is written as the text "null", exactly as the server mode does. */
  static String build(String repoSummary, String dirSummary, String fileName, String content) {
    return "Repository summary: " + repoSummary + "\n"
        + "Directory summary: " + dirSummary + "\n"
        + "File name: " + fileName + "\n"
        + "----\n"
        + content + "\n";
  }

  /**
   * Drops trailing lines, {@value #TRIM_LINES_PER_ROUND} at a time, until the text fits.
   *
   * @return the text that fits, or null if nothing is left after trimming
   */
  static String fitToLimit(String text, TokenCounter counter, int maxTokens) {
    String current = text;
    while (counter.count(current) > maxTokens) {
      current = removeLastLines(current, TRIM_LINES_PER_ROUND);
      if (current.trim().isEmpty()) {
        return null;
      }
    }
    return current;
  }

  /**
   * Drops one round of trailing lines.
   *
   * @return the shorter text, or null if nothing is left
   */
  static String trimOnce(String text) {
    String trimmed = removeLastLines(text, TRIM_LINES_PER_ROUND);
    return trimmed.trim().isEmpty() ? null : trimmed;
  }

  static String removeLastLines(String content, int linesToRemove) {
    if (content == null || content.isEmpty() || linesToRemove < 1) {
      return content;
    }
    String[] lines = content.split("\n");
    int newLength = Math.max(0, lines.length - linesToRemove);
    return String.join("\n", Arrays.copyOf(lines, newLength));
  }
}
