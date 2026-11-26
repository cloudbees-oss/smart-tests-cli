package com.launchableinc.ingest.commits;

/**
 * How often, and how patiently, to retry a request to an embedding provider. Each provider's
 * {@link EmbeddingAdapter} can supply its own.
 */
class RetryPolicy {
  /**
   * The server's own numbers for OpenAI (OpenAiClientService): 5 attempts in total, waiting 2, 4, 8
   * and 16 seconds in between.
   */
  static final RetryPolicy DEFAULT = new RetryPolicy(5, 1000);

  /** The most times one request is tried, the first try included. */
  final int maxAttempts;

  /** The wait after the first failure is twice this, and it doubles after every further failure. */
  final long baseWaitMillis;

  RetryPolicy(int maxAttempts, long baseWaitMillis) {
    this.maxAttempts = maxAttempts;
    this.baseWaitMillis = baseWaitMillis;
  }

  /** How long to wait after the given failed attempt (1 for the first). */
  long waitMillisAfter(int failedAttempt) {
    return baseWaitMillis << failedAttempt;
  }
}
