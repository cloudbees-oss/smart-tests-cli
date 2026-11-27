package com.launchableinc.ingest.commits;

/**
 * Looks up a {@link ModelProfile} by model name. The numbers are the server's own limits for
 * text-embedding-3-small (FileEmbeddingService): OpenAI's published limits with a safety margin.
 *
 * <p>The same trained model has the same profile whichever provider serves it, which is why the
 * lookup is by model name alone.
 */
class ModelProfiles {
  private ModelProfiles() {}

  /**
   * @throws UnsupportedEmbeddingException if the CLI does not know the model
   */
  static ModelProfile lookup(String modelName) {
    switch (EmbeddingAdapters.normalize(modelName)) {
      case "textembedding3small":
        // OpenAI's vectors are within about 0.0005 of length 1. The server stores them as returned in
        // its own mode, so client mode does too, which keeps the scores of both modes identical.
        return new ModelProfile(EmbeddingText.MAX_TOKENS, 1900, 210_000, 150_000, new JtokkitTokenCounter(), false);
      default:
        throw new UnsupportedEmbeddingException(
            "The embedding model '" + modelName + "' is not supported by this version of the CLI.");
    }
  }
}
