package com.launchableinc.ingest.commits;

import static com.google.common.truth.Truth.assertThat;
import static org.junit.Assert.assertThrows;

import com.google.common.util.concurrent.RateLimiter;
import java.io.IOException;
import java.util.ArrayDeque;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.Collections;
import java.util.Deque;
import java.util.List;
import org.junit.Test;

public class BatchEmbedderTest {
  private static final int DIMENSIONS = 2;

  /** Plays back scripted answers, then falls back to one valid vector per text. */
  private static class ScriptedAdapter implements EmbeddingAdapter {
    interface Step {
      List<float[]> run(List<String> texts) throws IOException;
    }

    final Deque<Step> steps = new ArrayDeque<>();
    final List<List<String>> calls = new ArrayList<>();

    ScriptedAdapter then(Step step) {
      steps.add(step);
      return this;
    }

    ScriptedAdapter thenFail(int status, boolean retryable, boolean contextLengthExceeded) {
      return then(
          texts -> {
            throw new EmbeddingException(status, "HTTP " + status, retryable, contextLengthExceeded);
          });
    }

    @Override
    public List<float[]> embed(List<String> texts) throws IOException {
      calls.add(new ArrayList<>(texts));
      return steps.isEmpty() ? unitVectors(texts.size()) : steps.poll().run(texts);
    }

    @Override
    public void close() {}
  }

  private static List<float[]> unitVectors(int n) {
    List<float[]> vectors = new ArrayList<>();
    for (int i = 0; i < n; i++) {
      vectors.add(new float[] {1, 0});
    }
    return vectors;
  }

  /** One token per character keeps the arithmetic obvious. A single input may have up to 10,000 of them. */
  private static BatchEmbedder embedder(
      EmbeddingAdapter adapter, int maxFilesPerRequest, int maxTokensPerRequest, List<Long> sleeps) {
    ModelProfile profile = new ModelProfile(10_000, maxFilesPerRequest, maxTokensPerRequest, 1_000_000, String::length);
    return new BatchEmbedder(adapter, profile, DIMENSIONS, RateLimiter.create(1e9), sleeps::add);
  }

  private static BatchEmbedder embedder(EmbeddingAdapter adapter, List<Long> sleeps) {
    return embedder(adapter, 100, 1_000_000, sleeps);
  }

  private static EmbeddingInput input(String name, String text) {
    return new EmbeddingInput(name, "blob-" + name, text, text.length());
  }

  /** {@code count} lines, each {@code width} characters long. */
  private static String lines(int count, int width) {
    StringBuilder line = new StringBuilder();
    for (int i = 0; i < width - 1; i++) {
      line.append('x');
    }
    List<String> lines = new ArrayList<>();
    for (int i = 0; i < count; i++) {
      lines.add(line.toString());
    }
    return String.join("\n", lines);
  }

  private static List<List<String>> names(List<List<EmbeddingInput>> requests) {
    List<List<String>> result = new ArrayList<>();
    for (List<EmbeddingInput> request : requests) {
      List<String> names = new ArrayList<>();
      for (EmbeddingInput input : request) {
        names.add(input.fileName);
      }
      result.add(names);
    }
    return result;
  }

  @Test
  public void packsRequestsByFileCount() {
    BatchEmbedder embedder = embedder(new ScriptedAdapter(), 2, 1_000_000, new ArrayList<>());
    List<EmbeddingInput> inputs = new ArrayList<>();
    for (String name : new String[] {"a", "b", "c", "d", "e"}) {
      inputs.add(input(name, "x"));
    }

    assertThat(names(embedder.pack(inputs)))
        .containsExactly(Arrays.asList("a", "b"), Arrays.asList("c", "d"), Arrays.asList("e"))
        .inOrder();
  }

  @Test
  public void packsRequestsByTokenBudget() {
    BatchEmbedder embedder = embedder(new ScriptedAdapter(), 100, 10, new ArrayList<>());
    // 6 + 6 would be 12 > 10, so the second input starts a new request, and 6 + 3 = 9 fits
    List<EmbeddingInput> inputs = Arrays.asList(input("a", "123456"), input("b", "123456"), input("c", "123"));

    assertThat(names(embedder.pack(inputs)))
        .containsExactly(Arrays.asList("a"), Arrays.asList("b", "c"))
        .inOrder();
  }

  @Test
  public void returnsNormalizedVectorsWithTheFileIdentity() throws IOException {
    ScriptedAdapter adapter = new ScriptedAdapter().then(texts -> Collections.singletonList(new float[] {3, 4}));

    BatchEmbedder.Result result = embedder(adapter, new ArrayList<>()).embed(Arrays.asList(input("a.txt", "hello")));

    assertThat(result.embeddings).hasSize(1);
    assertThat(result.embeddings.get(0).fileName).isEqualTo("a.txt");
    assertThat(result.embeddings.get(0).blobSha).isEqualTo("blob-a.txt");
    assertThat(result.embeddings.get(0).embedding).usingTolerance(1e-6).containsExactly(0.6f, 0.8f).inOrder();
  }

  @Test
  public void aModelWhoseVectorsNeedNoScalingIsUploadedAsReturnedUnlessTheServerWouldRejectIt() throws IOException {
    ModelProfile profile = new ModelProfile(10_000, 100, 1_000_000, 1_000_000, String::length, false);
    ScriptedAdapter adapter =
        new ScriptedAdapter().then(texts -> Arrays.asList(new float[] {0.6f, 0.8004f}, new float[] {3, 4}));
    BatchEmbedder embedder = new BatchEmbedder(adapter, profile, DIMENSIONS, RateLimiter.create(1e9), millis -> {});

    BatchEmbedder.Result result = embedder.embed(Arrays.asList(input("near", "x"), input("far", "x")));

    assertThat(result.embeddings.get(0).embedding).isEqualTo(new float[] {0.6f, 0.8004f}); // kept
    assertThat(result.embeddings.get(1).embedding).usingTolerance(1e-6).containsExactly(0.6f, 0.8f).inOrder(); // scaled
  }

  @Test
  public void retriesRateLimitingAndServerErrorsWithGrowingWaits() throws IOException {
    List<Long> sleeps = new ArrayList<>();
    ScriptedAdapter adapter = new ScriptedAdapter().thenFail(429, true, false).thenFail(503, true, false);

    BatchEmbedder.Result result = embedder(adapter, sleeps).embed(Arrays.asList(input("a", "x")));

    assertThat(result.embeddings).hasSize(1);
    assertThat(adapter.calls).hasSize(3);
    assertThat(sleeps).containsExactly(2000L, 4000L).inOrder();
  }

  @Test
  public void givesUpAfterFiveAttemptsAndSkipsTheRequest() throws IOException {
    List<Long> sleeps = new ArrayList<>();
    ScriptedAdapter adapter = new ScriptedAdapter();
    for (int i = 0; i < 10; i++) {
      adapter.thenFail(500, true, false);
    }

    BatchEmbedder.Result result = embedder(adapter, sleeps).embed(Arrays.asList(input("a", "x")));

    assertThat(adapter.calls).hasSize(5);
    assertThat(sleeps).containsExactly(2000L, 4000L, 8000L, 16000L).inOrder();
    assertThat(result.embeddings).isEmpty();
    assertThat(result.skipped).hasSize(1);
    assertThat(result.skipReason).contains("HTTP 500");
  }

  @Test
  public void aRequestThatFailsForGoodIsSkippedAndTheVectorsOfTheOthersAreKept() throws IOException {
    ScriptedAdapter adapter = new ScriptedAdapter().then(texts -> unitVectors(1));
    for (int i = 0; i < 10; i++) {
      adapter.thenFail(400, false, false);
    }
    // one file per request, so "a" is sent alone and succeeds and "b" is sent alone and fails
    BatchEmbedder embedder = embedder(adapter, 1, 1_000_000, new ArrayList<>());

    BatchEmbedder.Result result = embedder.embed(Arrays.asList(input("a", "x"), input("b", "x")));

    assertThat(result.embeddings).hasSize(1);
    assertThat(result.embeddings.get(0).fileName).isEqualTo("a");
    assertThat(result.skipped).hasSize(1);
    assertThat(result.skipped.get(0).fileName).isEqualTo("b");
  }

  @Test
  public void aWrongKeyOrAnUnknownEndpointStopsTheRunWithoutRetrying() {
    for (int status : new int[] {401, 403, 404}) {
      List<Long> sleeps = new ArrayList<>();
      ScriptedAdapter adapter = new ScriptedAdapter().thenFail(status, false, false);

      EmbeddingException e =
          assertThrows(
              EmbeddingException.class, () -> embedder(adapter, sleeps).embed(Arrays.asList(input("a", "x"))));

      assertThat(e.statusCode).isEqualTo(status);
      assertThat(adapter.calls).hasSize(1);
      assertThat(sleeps).isEmpty();
    }
  }

  @Test
  public void anEndpointThatCannotBeUsedAtAllStopsTheRun() {
    ScriptedAdapter adapter =
        new ScriptedAdapter()
            .then(
                texts -> {
                  throw new EmbeddingException(-1, "not a valid URL", false, false);
                });

    assertThrows(
        EmbeddingException.class, () -> embedder(adapter, new ArrayList<>()).embed(Arrays.asList(input("a", "x"))));
  }

  @Test
  public void anInputThatIsTooLongLosesThirtyLinesAndShortInputsAreLeftAlone() throws IOException {
    List<Long> sleeps = new ArrayList<>();
    String longText = lines(100, 100); // 10,099 tokens: within 10% of the 10,000 limit
    ScriptedAdapter adapter = new ScriptedAdapter().thenFail(400, false, true);

    BatchEmbedder.Result result =
        embedder(adapter, sleeps).embed(Arrays.asList(input("short", "short"), input("long", longText)));

    assertThat(result.embeddings).hasSize(2);
    assertThat(adapter.calls).hasSize(2);
    assertThat(adapter.calls.get(0)).containsExactly("short", longText).inOrder();
    assertThat(adapter.calls.get(1).get(0)).isEqualTo("short"); // not trimmed, and not dropped
    assertThat(adapter.calls.get(1).get(1).split("\n")).hasLength(70);
    assertThat(sleeps).containsExactly(2000L);
  }

  @Test
  public void aFileThatTrimsAwayToNothingIsReportedAsDroppedWithoutFurtherCalls() throws IOException {
    ScriptedAdapter adapter = new ScriptedAdapter().thenFail(400, false, true);
    // 10 lines is fewer than the 30 that one round removes, so nothing is left
    EmbeddingInput tooLong = input("minified.js", lines(10, 1000));

    BatchEmbedder.Result result = embedder(adapter, new ArrayList<>()).embed(Arrays.asList(tooLong));

    assertThat(result.dropped).containsExactly(tooLong);
    assertThat(result.embeddings).isEmpty();
    assertThat(adapter.calls).hasSize(1);
  }

  @Test
  public void skipsUnusableVectorsAndKeepsTheRest() throws IOException {
    ScriptedAdapter adapter =
        new ScriptedAdapter()
            .then(
                texts ->
                    Arrays.asList(
                        new float[] {1, 0},
                        new float[] {Float.NaN, 0},
                        new float[] {1, 0, 0},
                        null,
                        new float[] {0, 0}));

    BatchEmbedder.Result result =
        embedder(adapter, new ArrayList<>())
            .embed(
                Arrays.asList(
                    input("good", "x"),
                    input("nan", "x"),
                    input("wrong-size", "x"),
                    input("missing", "x"),
                    input("zero", "x")));

    assertThat(result.embeddings).hasSize(1);
    assertThat(result.embeddings.get(0).fileName).isEqualTo("good");
    assertThat(result.skipped).isEmpty(); // a single bad vector is a warning, not a failed request
  }

  @Test
  public void aWholeAnswerOfTheWrongSizeStopsTheRunWithOneMessage() {
    ScriptedAdapter adapter =
        new ScriptedAdapter().then(texts -> Arrays.asList(new float[] {1, 0, 0}, new float[] {0, 1, 0}));

    EmbeddingException e =
        assertThrows(
            EmbeddingException.class,
            () -> embedder(adapter, new ArrayList<>()).embed(Arrays.asList(input("a", "x"), input("b", "x"))));

    assertThat(e).hasMessageThat().contains("vectors of 3 values");
    assertThat(e).hasMessageThat().contains("expects 2");
  }

  @Test
  public void aWrongNumberOfVectorsSkipsTheRequest() throws IOException {
    ScriptedAdapter adapter = new ScriptedAdapter().then(texts -> unitVectors(1));

    BatchEmbedder.Result result =
        embedder(adapter, new ArrayList<>()).embed(Arrays.asList(input("a", "x"), input("b", "x")));

    assertThat(result.skipped).hasSize(2);
    assertThat(result.skipReason).contains("1 vectors for 2 inputs");
  }

  @Test
  public void describeUsesTheMessageThenTheCauseThenTheClassName() {
    assertThat(BatchEmbedder.describe(new IOException("the message"))).isEqualTo("the message");
    assertThat(BatchEmbedder.describe(new RuntimeException(null, new IllegalStateException("the cause"))))
        .isEqualTo("the cause");
    assertThat(BatchEmbedder.describe(new NullPointerException())).isEqualTo("NullPointerException");
  }
}
