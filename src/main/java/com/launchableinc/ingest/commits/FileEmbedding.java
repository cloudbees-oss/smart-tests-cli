package com.launchableinc.ingest.commits;

import com.fasterxml.jackson.annotation.JsonProperty;

/** One entry of the collect/embeddings request. The field names are part of the server's contract. */
class FileEmbedding {
  @JsonProperty final String fileName;
  @JsonProperty final String blobSha;
  @JsonProperty final float[] embedding;

  FileEmbedding(String fileName, String blobSha, float[] embedding) {
    this.fileName = fileName;
    this.blobSha = blobSha;
    this.embedding = embedding;
  }
}
