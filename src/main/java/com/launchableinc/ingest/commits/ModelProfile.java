package com.launchableinc.ingest.commits;

/** The limits and tokenizer that go with one embedding model. */
class ModelProfile {
  /** The most tokens one input may have. Longer files are trimmed. */
  final int maxTokensPerInput;

  /** The most inputs in one request to the provider. */
  final int maxFilesPerRequest;

  /** The most tokens in one request to the provider, across all its inputs. */
  final int maxTokensPerRequest;

  /** The rate limit, shared by every request. */
  final int tokensPerSecond;

  final TokenCounter tokenizer;

  ModelProfile(
      int maxTokensPerInput, int maxFilesPerRequest, int maxTokensPerRequest, int tokensPerSecond, TokenCounter tokenizer) {
    this.maxTokensPerInput = maxTokensPerInput;
    this.maxFilesPerRequest = maxFilesPerRequest;
    this.maxTokensPerRequest = maxTokensPerRequest;
    this.tokensPerSecond = tokensPerSecond;
    this.tokenizer = tokenizer;
  }
}
