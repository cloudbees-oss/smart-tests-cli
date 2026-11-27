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

  /**
   * Whether the CLI must scale this model's vectors to length 1 before uploading. False when the
   * model's own vectors are already close enough to length 1 for the server (it accepts a length
   * within 0.001 of 1), so they are stored as returned, as the server does in its own mode.
   */
  final boolean normalizeVectors;

  ModelProfile(
      int maxTokensPerInput,
      int maxFilesPerRequest,
      int maxTokensPerRequest,
      int tokensPerSecond,
      TokenCounter tokenizer,
      boolean normalizeVectors) {
    this.maxTokensPerInput = maxTokensPerInput;
    this.maxFilesPerRequest = maxFilesPerRequest;
    this.maxTokensPerRequest = maxTokensPerRequest;
    this.tokensPerSecond = tokensPerSecond;
    this.tokenizer = tokenizer;
    this.normalizeVectors = normalizeVectors;
  }

  /** A model whose vectors have to be scaled to length 1, which is the safe default. */
  ModelProfile(
      int maxTokensPerInput, int maxFilesPerRequest, int maxTokensPerRequest, int tokensPerSecond, TokenCounter tokenizer) {
    this(maxTokensPerInput, maxFilesPerRequest, maxTokensPerRequest, tokensPerSecond, tokenizer, true);
  }
}
