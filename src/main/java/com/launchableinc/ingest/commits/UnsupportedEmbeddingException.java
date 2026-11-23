package com.launchableinc.ingest.commits;

/** The workspace's embedding provider or model is not one this CLI knows how to use. */
class UnsupportedEmbeddingException extends RuntimeException {
  UnsupportedEmbeddingException(String message) {
    super(message);
  }
}
