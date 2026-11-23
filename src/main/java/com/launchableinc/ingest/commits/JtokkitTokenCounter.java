package com.launchableinc.ingest.commits;

import com.knuddels.jtokkit.Encodings;
import com.knuddels.jtokkit.api.Encoding;
import com.knuddels.jtokkit.api.ModelType;

/**
 * Token counter for OpenAI's text-embedding-3 models, using the same library, version and encoding
 * as the server (FileEmbeddingService), so a file is trimmed at exactly the same point in both
 * client and server modes.
 */
class JtokkitTokenCounter implements TokenCounter {
  private final Encoding encoding;

  JtokkitTokenCounter() {
    this.encoding =
        Encodings.newDefaultEncodingRegistry().getEncodingForModel(ModelType.TEXT_EMBEDDING_3_SMALL);
  }

  @Override
  public int count(String text) {
    return encoding.countTokensOrdinary(text);
  }
}
