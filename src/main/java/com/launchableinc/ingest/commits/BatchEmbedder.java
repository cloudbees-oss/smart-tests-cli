package com.launchableinc.ingest.commits;

import com.google.common.util.concurrent.RateLimiter;
import java.io.Closeable;
import java.io.IOException;
import java.util.ArrayList;
import java.util.List;

/**
 * Turns files into unit-length vectors using the customer's embedding endpoint
 *
 * <ul>
 *   <li>inputs are packed into requests of at most {@link ModelProfile#maxFilesPerRequest} files
 *       and {@link ModelProfile#maxTokensPerRequest} tokens
 *   <li>each request waits for the shared tokens-per-second rate limit
 *   <li>a request is retried as the provider's {@link EmbeddingAdapter#retryPolicy()} says, by
 *       default up to 5 attempts waiting 2, 4, 8 and 16 seconds in between. Only rate limiting
 *       (429), server errors (5xx) and network errors are retried
 *   <li>if the provider says an input is too long, every input loses another round of trailing
 *       lines and the request is retried
 * </ul>
 *
 * <p>One instance is shared by all batches, so it is thread safe.
 */
class BatchEmbedder implements Closeable {
  /** Let tests run without really waiting. */
  interface Sleeper {
    void sleep(long millis) throws InterruptedException;
  }

  private final EmbeddingAdapter adapter;
  private final ModelProfile profile;
  private final int dimensions;
  private final RateLimiter rateLimiter;
  private final Sleeper sleeper;

  BatchEmbedder(EmbeddingAdapter adapter, ModelProfile profile, int dimensions, RateLimiter rateLimiter, Sleeper sleeper) {
    this.adapter = adapter;
    this.profile = profile;
    this.dimensions = dimensions;
    this.rateLimiter = rateLimiter;
    this.sleeper = sleeper;
  }

  /**
   * @throws UnsupportedEmbeddingException if the provider or the model is not supported
   */
  static BatchEmbedder create(EmbeddingConfig config) {
    ModelProfile profile = ModelProfiles.lookup(config.modelName);
    EmbeddingAdapter adapter = EmbeddingAdapters.create(config);
    return new BatchEmbedder(
        adapter, profile, config.dimensions, RateLimiter.create(profile.tokensPerSecond), Thread::sleep);
  }

  TokenCounter tokenCounter() {
    return profile.tokenizer;
  }

  int maxTokensPerInput() {
    return profile.maxTokensPerInput;
  }

  /** What one call to {@link #embed} produced. */
  static class Result {
    /** Vectors that are ready to upload. */
    final List<FileEmbedding> embeddings = new ArrayList<>();

    /**
     * Files whose request failed for good. They have no vector, so the next run offers them again.
     * Sending the request again here, or splitting it up to find a bad file, would spend more of the
     * customer's money on an API call that already failed.
     */
    final List<EmbeddingInput> skipped = new ArrayList<>();

    /** Why the first request was skipped, for the warning. */
    String skipReason;

    /**
     * Files that could not be made short enough for the model: nothing was left after trimming. They
     * will not fit on the next run either, unless the file changes.
     */
    final List<EmbeddingInput> dropped = new ArrayList<>();
  }

  /**
   * Embeds the inputs. A file whose vector comes back unusable is skipped with a warning and does
   * not affect the others. A request that still fails after its retries is skipped as a whole, and
   * the vectors from the requests that succeeded are kept, because they are already paid for.
   *
   * @throws IOException if the endpoint rejects the key or cannot be found (HTTP 401, 403 or 404):
   *     every request would fail the same way, so there is no point in going on
   */
  Result embed(List<EmbeddingInput> inputs) throws IOException {
    Result result = new Result();
    for (List<EmbeddingInput> request : pack(inputs)) {
      try {
        result.embeddings.addAll(embedRequest(request, result));
      } catch (IOException e) {
        if (isFatal(e) || Thread.currentThread().isInterrupted()) {
          throw e;
        }
        result.skipped.addAll(request);
        if (result.skipReason == null) {
          result.skipReason = describe(e);
        }
      }
    }
    return result;
  }

  /**
   * The error's message for a warning. When it has none, the message of what caused it, and as a last
   * resort its class name (for example a NullPointerException).
   */
  static String describe(Throwable e) {
    for (Throwable t = e; t != null; t = t.getCause() == t ? null : t.getCause()) {
      String message = t.getMessage();
      if (message != null && !message.isEmpty()) {
        return message;
      }
    }
    return e.getClass().getSimpleName();
  }

  /**
   * A wrong key, an endpoint or model that is not found, or an endpoint that cannot be used at all (a
   * malformed URL, an untrusted certificate): every request would fail the same way.
   */
  private static boolean isFatal(IOException e) {
    if (!(e instanceof EmbeddingException)) {
      return false;
    }
    EmbeddingException failure = (EmbeddingException) e;
    int status = failure.statusCode;
    boolean noAnswerAndNeverWillBe = status == -1 && !failure.retryable;
    return status == 401 || status == 403 || status == 404 || noAnswerAndNeverWillBe;
  }

  /** Groups the inputs, in order, into requests that stay within the model's limits. */
  List<List<EmbeddingInput>> pack(List<EmbeddingInput> inputs) {
    List<List<EmbeddingInput>> requests = new ArrayList<>();
    List<EmbeddingInput> current = new ArrayList<>();
    int tokens = 0;
    for (EmbeddingInput input : inputs) {
      boolean full =
          tokens + input.tokens > profile.maxTokensPerRequest || current.size() + 1 > profile.maxFilesPerRequest;
      if (!current.isEmpty() && full) {
        requests.add(current);
        current = new ArrayList<>();
        tokens = 0;
      }
      current.add(input);
      tokens += input.tokens;
    }
    if (!current.isEmpty()) {
      requests.add(current);
    }
    return requests;
  }

  private List<FileEmbedding> embedRequest(List<EmbeddingInput> request, Result result) throws IOException {
    rateLimiter.acquire(Math.max(1, sumTokens(request)));

    RetryPolicy retry = adapter.retryPolicy();
    List<EmbeddingInput> sent = request;
    for (int attempt = 1; ; attempt++) {
      try {
        return toEmbeddings(sent, adapter.embed(texts(sent)));
      } catch (EmbeddingException e) {
        if (attempt >= retry.maxAttempts || !(e.retryable || e.contextLengthExceeded)) {
          throw e;
        }
        if (e.contextLengthExceeded) {
          sent = trimLongest(sent, result);
          if (sent.isEmpty()) {
            return new ArrayList<>();
          }
        }
        pause(retry.waitMillisAfter(attempt));
      }
    }
  }

  private List<FileEmbedding> toEmbeddings(List<EmbeddingInput> sent, List<float[]> vectors) throws IOException {
    if (vectors.size() != sent.size()) {
      throw new IOException(
          "The embedding endpoint returned " + vectors.size() + " vectors for " + sent.size() + " inputs");
    }
    failIfEveryVectorHasTheWrongSize(vectors);
    List<FileEmbedding> results = new ArrayList<>(sent.size());
    for (int i = 0; i < sent.size(); i++) {
      EmbeddingInput input = sent.get(i);
      float[] vector = EmbeddingVectors.prepare(vectors.get(i), dimensions, profile.normalizeVectors);
      if (vector == null) {
        System.err.printf("Skipping %s: the embedding endpoint returned an unusable vector%n", input.fileName);
        continue;
      }
      results.add(new FileEmbedding(input.fileName, input.blobSha, vector));
    }
    return results;
  }

  /**
   * If every vector in an answer has a different size than the server expects, the model or the
   * dimensions setting is wrong, and every later answer would be wrong in the same way. That is one
   * problem to report once, not one warning per file. A lone odd vector is still just skipped.
   */
  private void failIfEveryVectorHasTheWrongSize(List<float[]> vectors) throws EmbeddingException {
    int received = 0;
    int actualSize = -1;
    for (float[] vector : vectors) {
      if (vector == null) {
        continue;
      }
      received++;
      if (vector.length == dimensions) {
        return;
      }
      actualSize = vector.length;
    }
    if (received > 0) {
      throw new EmbeddingException(
          -1,
          "The embedding endpoint returned vectors of " + actualSize + " values, but this workspace expects "
              + dimensions + ". Check that SMART_TESTS_EMBEDDING_ENDPOINT serves the workspace's embedding model",
          false,
          false);
    }
  }

  /**
   * The provider said an input is too long, but not which one. Our own token count is close to the
   * provider's, so it has to be one of the longest inputs. Only those lose another round of trailing
   * lines: the inputs within 10% of the limit, and always at least the longest one, so every round
   * makes progress. Short files are left alone. A file with nothing left goes to {@code
   * result.dropped}.
   */
  private List<EmbeddingInput> trimLongest(List<EmbeddingInput> inputs, Result result) {
    int longest = 0;
    for (EmbeddingInput input : inputs) {
      longest = Math.max(longest, input.tokens);
    }
    int threshold = Math.min(longest, profile.maxTokensPerInput / 10 * 9);

    List<EmbeddingInput> remaining = new ArrayList<>();
    for (EmbeddingInput input : inputs) {
      if (input.tokens < threshold) {
        remaining.add(input);
        continue;
      }
      String text = EmbeddingText.trimOnce(input.text);
      if (text == null) {
        result.dropped.add(input);
      } else {
        remaining.add(new EmbeddingInput(input.fileName, input.blobSha, text, profile.tokenizer.count(text)));
      }
    }
    return remaining;
  }

  private void pause(long millis) throws IOException {
    try {
      sleeper.sleep(millis);
    } catch (InterruptedException e) {
      Thread.currentThread().interrupt();
      throw new IOException("Interrupted while waiting to retry the embedding request", e);
    }
  }

  private static int sumTokens(List<EmbeddingInput> inputs) {
    int sum = 0;
    for (EmbeddingInput input : inputs) {
      sum += input.tokens;
    }
    return sum;
  }

  private static List<String> texts(List<EmbeddingInput> inputs) {
    List<String> texts = new ArrayList<>(inputs.size());
    for (EmbeddingInput input : inputs) {
      texts.add(input.text);
    }
    return texts;
  }

  @Override
  public void close() throws IOException {
    adapter.close();
  }
}
