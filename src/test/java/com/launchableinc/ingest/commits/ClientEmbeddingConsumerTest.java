package com.launchableinc.ingest.commits;

import static com.google.common.truth.Truth.assertThat;

import com.google.common.collect.ImmutableList;
import com.google.common.collect.ImmutableMap;
import com.google.common.util.concurrent.RateLimiter;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.Collections;
import java.util.List;
import java.util.Map;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.atomic.AtomicInteger;
import org.eclipse.jgit.lib.ObjectId;
import org.junit.Test;

public class ClientEmbeddingConsumerTest {
  private static final List<String> TREE = ImmutableList.of("a.txt", "b.txt", "c.txt");

  private static VirtualFile file(String path) {
    return VirtualFile.from("repo", path, ObjectId.zeroId(), new byte[0]);
  }

  private static List<VirtualFile> files(int n) {
    List<VirtualFile> files = new ArrayList<>();
    for (int i = 0; i < n; i++) {
      files.add(file("f" + i + ".txt"));
    }
    return files;
  }

  /** The files in these tests are empty, so nothing is ever embedded and this model is never asked. */
  private static BatchEmbedder idleEmbedder() {
    EmbeddingAdapter adapter =
        new EmbeddingAdapter() {
          @Override
          public List<float[]> embed(List<String> texts) {
            throw new AssertionError("nothing should be embedded");
          }

          @Override
          public void close() {}
        };
    ModelProfile profile = new ModelProfile(10_000, 100, 1_000_000, 1_000_000, String::length);
    return new BatchEmbedder(adapter, profile, 2, RateLimiter.create(1_000_000), millis -> {});
  }

  private static ClientEmbeddingConsumer job(CommitGraphCollector.SummariesSender summaries) {
    return job(summaries, count -> {});
  }

  private static ClientEmbeddingConsumer job(
      CommitGraphCollector.SummariesSender summaries, java.util.function.IntConsumer onSkipped) {
    return new ClientEmbeddingConsumer(TREE, summaries, idleEmbedder(), vectors -> 0, count -> {}, onSkipped, count -> {}, false);
  }

  /** Runs the whole pipeline the way transfer() wires it. */
  private static void run(ClientEmbeddingConsumer job, ExecutorService pool, int batchSize, List<VirtualFile> input)
      throws IOException {
    try (ConcurrentConsumer<List<VirtualFile>> parallel = new ConcurrentConsumer<>(job, pool);
        BatchingConsumer<VirtualFile> batcher = new BatchingConsumer<>(parallel, batchSize)) {
      input.forEach(batcher);
    }
  }

  @Test
  public void sendsEveryBatchWithTheWholeRepositoryTree() throws IOException {
    List<List<String>> selectedPerCall = Collections.synchronizedList(new ArrayList<>());
    List<List<String>> treePerCall = Collections.synchronizedList(new ArrayList<>());
    ClientEmbeddingConsumer job =
        job(
            (tree, selected) -> {
              treePerCall.add(tree);
              selectedPerCall.add(selected);
              return new JSSummariesResponse();
            });
    ExecutorService pool = new BoundedExecutorService(4);

    try {
      run(job, pool, 2, ImmutableList.of(file("a.txt"), file("b.txt"), file("c.txt")));
    } finally {
      pool.shutdown();
    }

    assertThat(selectedPerCall).hasSize(2);
    assertThat(selectedPerCall).contains(ImmutableList.of("a.txt", "b.txt"));
    assertThat(selectedPerCall).contains(ImmutableList.of("c.txt"));
    for (List<String> tree : treePerCall) {
      assertThat(tree).isEqualTo(TREE);
    }
  }

  @Test
  public void neverRunsMoreCallsAtOnceThanThePoolAllows() throws IOException {
    AtomicInteger inFlight = new AtomicInteger();
    AtomicInteger maxInFlight = new AtomicInteger();
    ClientEmbeddingConsumer job =
        job(
            (tree, selected) -> {
              int now = inFlight.incrementAndGet();
              maxInFlight.accumulateAndGet(now, Math::max);
              try {
                Thread.sleep(50);
              } catch (InterruptedException e) {
                throw new IOException(e);
              } finally {
                inFlight.decrementAndGet();
              }
              return new JSSummariesResponse();
            });
    ExecutorService pool = new BoundedExecutorService(3);

    try {
      run(job, pool, 1, files(12));
    } finally {
      pool.shutdown();
    }

    assertThat(maxInFlight.get()).isAtMost(3);
    assertThat(maxInFlight.get()).isGreaterThan(1); // really ran in parallel
  }

  @Test
  public void aBatchWhoseSummariesFailIsSkippedAndTheOthersCarryOn() throws IOException {
    AtomicInteger calls = new AtomicInteger();
    AtomicInteger skippedFiles = new AtomicInteger();
    ClientEmbeddingConsumer job =
        job(
            (tree, selected) -> {
              if (calls.incrementAndGet() == 1) {
                throw new IOException("boom");
              }
              return new JSSummariesResponse();
            },
            skippedFiles::addAndGet);
    // one worker, so batches are processed strictly one after another
    ExecutorService pool = new BoundedExecutorService(1);

    try {
      run(job, pool, 1, files(4));
    } finally {
      pool.shutdown();
    }

    assertThat(calls.get()).isEqualTo(4); // the failure did not stop the other batches
    assertThat(skippedFiles.get()).isEqualTo(1); // only the failed batch's file is skipped
  }

  // ---- the work done for each file

  private static VirtualFile file(String path, String content) {
    return VirtualFile.from("repo", path, ObjectId.zeroId(), content.getBytes(StandardCharsets.UTF_8));
  }

  /** An embedder whose "model" answers [3, 4] for every text and remembers the texts it was asked about. */
  private static BatchEmbedder recordingEmbedder(List<String> seenTexts) {
    EmbeddingAdapter adapter =
        new EmbeddingAdapter() {
          @Override
          public List<float[]> embed(List<String> texts) {
            seenTexts.addAll(texts);
            List<float[]> vectors = new ArrayList<>();
            for (int i = 0; i < texts.size(); i++) {
              vectors.add(new float[] {3, 4});
            }
            return vectors;
          }

          @Override
          public void close() {}
        };
    ModelProfile profile = new ModelProfile(10_000, 100, 1_000_000, 1_000_000, String::length);
    return new BatchEmbedder(adapter, profile, 2, RateLimiter.create(1_000_000), millis -> {});
  }

  private static CommitGraphCollector.SummariesSender summaries(String repo, Map<String, String> folders) {
    return (tree, selected) -> {
      JSSummariesResponse response = new JSSummariesResponse();
      response.repoSummary = repo;
      response.dirSummaries = folders;
      return response;
    };
  }

  /** Counts what the consumer reports, and runs the given files through it as one batch. */
  private static class Outcome {
    final List<String> modelSaw = Collections.synchronizedList(new ArrayList<>());
    final List<FileEmbedding> uploaded = Collections.synchronizedList(new ArrayList<>());
    final AtomicInteger embedded = new AtomicInteger();
    final AtomicInteger skipped = new AtomicInteger();
    final AtomicInteger processed = new AtomicInteger();

    void run(
        CommitGraphCollector.SummariesSender summaries,
        CommitGraphCollector.EmbeddingsSender sender,
        boolean dryRun,
        List<VirtualFile>... batches)
        throws IOException {
      ClientEmbeddingConsumer job =
          new ClientEmbeddingConsumer(
              TREE, summaries, recordingEmbedder(modelSaw), sender, embedded::addAndGet, skipped::addAndGet,
              processed::addAndGet, dryRun);
      for (List<VirtualFile> batch : batches) {
        job.accept(batch);
      }
    }

    CommitGraphCollector.EmbeddingsSender collecting() {
      return vectors -> {
        uploaded.addAll(vectors);
        return vectors.size();
      };
    }
  }

  @Test
  @SuppressWarnings("unchecked")
  public void embedsEachFileWithTheServersTextAndUploadsUnitVectors() throws IOException {
    Outcome outcome = new Outcome();

    outcome.run(
        summaries("A test repo", ImmutableMap.of("", "Top level", "src", "Sources")),
        outcome.collecting(),
        false,
        ImmutableList.of(file("README.md", "readme"), file("src/A.java", "code")));

    assertThat(outcome.modelSaw)
        .containsExactly(
            "Repository summary: A test repo\nDirectory summary: Top level\nFile name: README.md\n----\nreadme\n",
            "Repository summary: A test repo\nDirectory summary: Sources\nFile name: src/A.java\n----\ncode\n");
    assertThat(outcome.uploaded).hasSize(2);
    assertThat(outcome.uploaded.get(0).embedding).usingTolerance(1e-6).containsExactly(0.6f, 0.8f).inOrder();
    assertThat(outcome.uploaded.get(0).blobSha).isEqualTo(ObjectId.zeroId().name());
    assertThat(outcome.embedded.get()).isEqualTo(2);
  }

  @Test
  @SuppressWarnings("unchecked")
  public void blankFilesAreNotEmbedded() throws IOException {
    Outcome outcome = new Outcome();

    outcome.run(
        summaries("R", ImmutableMap.of()),
        outcome.collecting(),
        false,
        ImmutableList.of(file("empty.txt", ""), file("spaces.txt", "  \n\t\n"), file("real.txt", "x")));

    assertThat(outcome.modelSaw).hasSize(1);
    assertThat(outcome.modelSaw.get(0)).contains("File name: real.txt");
  }

  @Test
  @SuppressWarnings("unchecked")
  public void aFolderWithoutASummaryIsWrittenAsNullLikeTheServerDoes() throws IOException {
    Outcome outcome = new Outcome();

    outcome.run(summaries("R", ImmutableMap.of()), outcome.collecting(), false, ImmutableList.of(file("lib/B.java", "x")));

    assertThat(outcome.modelSaw.get(0)).contains("Directory summary: null\n");
  }

  @Test
  @SuppressWarnings("unchecked")
  public void aFileThatCannotBeTrimmedIsLeftOutAndTheOthersAreStillEmbedded() throws IOException {
    Outcome outcome = new Outcome();
    String oneVeryLongLine = new String(new char[20_000]).replace('\0', 'x'); // a minified file

    outcome.run(
        summaries("R", ImmutableMap.of()),
        outcome.collecting(),
        false,
        ImmutableList.of(file("minified.js", oneVeryLongLine), file("small.txt", "x")));

    assertThat(outcome.modelSaw).hasSize(1);
    assertThat(outcome.modelSaw.get(0)).contains("File name: small.txt");
    assertThat(outcome.processed.get()).isEqualTo(2); // the long one still counts as finished
  }

  @Test
  @SuppressWarnings("unchecked")
  public void aDryRunSendsNothingToTheModelOrTheServerAndReportsNoProgress() throws IOException {
    Outcome outcome = new Outcome();

    outcome.run(summaries("R", ImmutableMap.of()), outcome.collecting(), true, ImmutableList.of(file("a.txt", "x")));

    assertThat(outcome.modelSaw).isEmpty();
    assertThat(outcome.uploaded).isEmpty();
    assertThat(outcome.processed.get()).isEqualTo(0);
  }

  @Test
  @SuppressWarnings("unchecked")
  public void aFailedUploadSkipsThoseFilesAndTheRunGoesOn() throws IOException {
    Outcome outcome = new Outcome();
    CommitGraphCollector.EmbeddingsSender failing =
        vectors -> {
          throw new IOException("upload failed");
        };

    outcome.run(
        summaries("R", ImmutableMap.of()),
        failing,
        false,
        ImmutableList.of(file("a.txt", "x"), file("b.txt", "y")),
        ImmutableList.of(file("c.txt", "z")));

    assertThat(outcome.skipped.get()).isEqualTo(3); // both batches were embedded, then skipped when the upload failed
    assertThat(outcome.embedded.get()).isEqualTo(0);
    assertThat(outcome.processed.get()).isEqualTo(3);
  }

  @Test
  @SuppressWarnings("unchecked")
  public void filesLeftWithoutAVectorBecauseOfAFailureStopTheRunAfterTheLastBatch() throws IOException {
    ClientEmbeddingConsumer job = consumerWith(failingUpload(), file("a.txt", "x"), file("b.txt", "y"));

    EmbeddingRunFailedException e =
        org.junit.Assert.assertThrows(EmbeddingRunFailedException.class, job::failIfAnyBatchFailed);

    assertThat(e).hasMessageThat().contains("2 files were skipped");
    assertThat(e).hasMessageThat().contains("no commits were recorded");
  }

  @Test
  @SuppressWarnings("unchecked")
  public void blankAndTooLongFilesDoNotStopTheRun() throws IOException {
    String oneVeryLongLine = new String(new char[20_000]).replace('\0', 'x');
    Outcome outcome = new Outcome();
    ClientEmbeddingConsumer job =
        consumerWith(outcome.collecting(), file("empty.txt", ""), file("minified.js", oneVeryLongLine), file("ok.txt", "x"));

    job.failIfAnyBatchFailed(); // does not throw
  }

  private static CommitGraphCollector.EmbeddingsSender failingUpload() {
    return vectors -> {
      throw new IOException("upload failed");
    };
  }

  private static ClientEmbeddingConsumer consumerWith(CommitGraphCollector.EmbeddingsSender sender, VirtualFile... files)
      throws IOException {
    ClientEmbeddingConsumer job =
        new ClientEmbeddingConsumer(
            TREE, summaries("R", ImmutableMap.of()), recordingEmbedder(new ArrayList<>()), sender,
            count -> {}, count -> {}, count -> {}, false);
    job.accept(java.util.Arrays.asList(files));
    return job;
  }

  @Test
  @SuppressWarnings("unchecked")
  public void everyFileIsReportedAsFinishedWhateverHappenedToIt() throws IOException {
    Outcome outcome = new Outcome();
    AtomicInteger calls = new AtomicInteger();
    CommitGraphCollector.SummariesSender firstFails =
        (tree, selected) -> {
          if (calls.incrementAndGet() == 1) {
            throw new IOException("boom");
          }
          return new JSSummariesResponse();
        };

    outcome.run(
        firstFails,
        outcome.collecting(),
        false,
        ImmutableList.of(file("a.txt", "x"), file("b.txt", "y")), // summaries fail: skipped
        ImmutableList.of(file("c.txt", "z"))); // embedded

    assertThat(outcome.skipped.get()).isEqualTo(2);
    assertThat(outcome.embedded.get()).isEqualTo(1);
    assertThat(outcome.processed.get()).isEqualTo(3);
  }
}
