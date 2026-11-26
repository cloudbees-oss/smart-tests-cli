package com.launchableinc.ingest.commits;

import java.io.IOException;

/**
 * Thrown by an {@link EmbeddingAdapter} when the provider's endpoint fails. It tells the generic
 * retry code what to do without that code knowing anything about the provider.
 */
class EmbeddingException extends IOException {
  /** The HTTP status, or -1 when there was no response. */
  final int statusCode;

  /** True for failures that are worth retrying: HTTP 429, HTTP 5xx and network errors. */
  final boolean retryable;

  /** True when the provider said an input is longer than the model accepts. */
  final boolean contextLengthExceeded;

  EmbeddingException(int statusCode, String message, boolean retryable, boolean contextLengthExceeded) {
    super(message);
    this.statusCode = statusCode;
    this.retryable = retryable;
    this.contextLengthExceeded = contextLengthExceeded;
  }
}
