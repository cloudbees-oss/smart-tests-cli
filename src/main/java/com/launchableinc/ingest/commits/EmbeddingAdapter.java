package com.launchableinc.ingest.commits;

import java.io.Closeable;
import java.io.IOException;
import java.util.List;

/** How to talk to one provider's embedding endpoint. */
interface EmbeddingAdapter extends Closeable {
  /**
   * Embeds the texts.
   *
   * @return one vector per text, in the same order. An entry is null if the provider returned
   *     nothing for that input.
   * @throws EmbeddingException if the endpoint fails
   */
  List<float[]> embed(List<String> texts) throws IOException;

  /** How to retry a request to this provider. A provider with different advice overrides this. */
  default RetryPolicy retryPolicy() {
    return RetryPolicy.DEFAULT;
  }
}
