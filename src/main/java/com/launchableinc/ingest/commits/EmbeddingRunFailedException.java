package com.launchableinc.ingest.commits;

import java.io.IOException;

/**
 * Client-side embedding cannot go on, for example because the endpoint rejects the key or the model
 * returns vectors of the wrong size. The message says what is wrong and is meant to be shown as it
 * is, without a stack trace. {@link Main#main} turns it into {@link Main#EXIT_EMBEDDING_FAILED}.
 */
class EmbeddingRunFailedException extends IOException {
  EmbeddingRunFailedException(String message, Throwable cause) {
    super(message, cause);
  }
}
