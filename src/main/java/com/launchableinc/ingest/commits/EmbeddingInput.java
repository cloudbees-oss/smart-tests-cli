package com.launchableinc.ingest.commits;

/** One file ready to be embedded: its identity and the exact text to send to the model. */
class EmbeddingInput {
  final String fileName;
  final String blobSha;
  final String text;
  final int tokens;

  EmbeddingInput(String fileName, String blobSha, String text, int tokens) {
    this.fileName = fileName;
    this.blobSha = blobSha;
    this.text = text;
    this.tokens = tokens;
  }
}
