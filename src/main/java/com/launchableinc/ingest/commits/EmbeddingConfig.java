package com.launchableinc.ingest.commits;

class EmbeddingConfig {

  final String provider;

  final String modelName;

  final int dimensions;

  final int modelId;

  /**
   * The full URL of the customer's embeddings endpoint, from SMART_TESTS_EMBEDDING_ENDPOINT env var, for example
   * https://api.openai.com/v1/embeddings.
   */
  final String endpoint;

  /** From SMART_TESTS_EMBEDDING_API_KEY. Never printed, never put on a command line. */
  private final String apiKey;

  EmbeddingConfig(String provider, String modelName, int dimensions, int modelId, String endpoint, String apiKey) {
    this.provider = provider;
    this.modelName = modelName;
    this.dimensions = dimensions;
    this.modelId = modelId;
    this.endpoint = endpoint;
    this.apiKey = apiKey;
  }

  String apiKey() {
    return apiKey;
  }

  @Override
  public String toString() {
    return "EmbeddingConfig{provider=" + provider + ", model=" + modelName + ", dimensions=" + dimensions
        + ", modelId=" + modelId + ", endpoint=" + endpoint + "}";
  }
}
