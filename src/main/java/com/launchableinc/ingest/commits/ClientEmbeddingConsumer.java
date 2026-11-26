package com.launchableinc.ingest.commits;

import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.List;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.function.IntConsumer;
import java.util.stream.Collectors;
import org.apache.commons.io.FilenameUtils;

/**
 * Processes one batch of the files the server selected via collect/tree, from summaries to stored
 * vectors:
 *
 * <ol>
 *   <li>collect/summaries returns a repository summary and folder summaries for the batch
 *   <li>each file becomes the text the server's own embedder would build (see {@link
 *       EmbeddingText}), trimmed to the model's token limit. Blank files are skipped
 *   <li>the customer's embedding endpoint turns the texts into vectors ({@link BatchEmbedder})
 *   <li>collect/embeddings uploads the vectors and the server stores them in the background
 * </ol>
 *
 * <p>A batch that fails along the way is skipped with a warning, and the other batches carry on.
 * Its files have no stored vector, so the next run offers them again. Only a wrong key or a
 * missing endpoint on the customer's side stops the whole run, because every batch would fail.
 *
 * <p>Batches are processed concurrently, see {@link ConcurrentConsumer}, so this class must be
 * thread safe.
 */
class ClientEmbeddingConsumer implements IOConsumer<List<VirtualFile>> {
  /** Every file path in the repository. Read-only after construction, so it is shared by all batches. */
  private final List<String> tree;

  private final CommitGraphCollector.SummariesSender summaries;
  private final BatchEmbedder embedder;
  private final CommitGraphCollector.EmbeddingsSender embeddingsSender;

  /** Told how many files the server accepted for each batch. */
  private final IntConsumer onEmbedded;

  /** Told how many files were skipped, to be retried on the next run. */
  private final IntConsumer onSkipped;

  /** Told how many files are finished with, however it ended: embedded, skipped or left out. */
  private final IntConsumer onProcessed;

  /** In a dry run the summaries call only prints its request, and nothing is embedded or uploaded. */
  private final boolean dryRun;

  /** Set when the whole run has to stop, so batches still queued don't spend more money. */
  private volatile boolean failed;

  private final AtomicInteger batches = new AtomicInteger();
  private final AtomicInteger summaryFailures = new AtomicInteger();

  /** Files left without a vector because something failed. Blank and too long files are not counted. */
  private final AtomicInteger failedFiles = new AtomicInteger();

  ClientEmbeddingConsumer(
      List<String> tree,
      CommitGraphCollector.SummariesSender summaries,
      BatchEmbedder embedder,
      CommitGraphCollector.EmbeddingsSender embeddingsSender,
      IntConsumer onEmbedded,
      IntConsumer onSkipped,
      IntConsumer onProcessed,
      boolean dryRun) {
    this.tree = tree;
    this.summaries = summaries;
    this.embedder = embedder;
    this.embeddingsSender = embeddingsSender;
    this.onEmbedded = onEmbedded;
    this.onSkipped = onSkipped;
    this.onProcessed = onProcessed;
    this.dryRun = dryRun;
  }

  @Override
  public void accept(List<VirtualFile> batch) throws IOException {
    if (failed) {
      // The run is stopping anyway. The first failure is reported by ConcurrentConsumer.close().
      return;
    }
    batches.incrementAndGet();
    try {
      process(batch);
    } catch (IOException | RuntimeException e) {
      failed = true;
      throw e;
    }
    if (!dryRun) {
      onProcessed.accept(batch.size()); // however it ended, this batch is finished
    }
  }

  private void process(List<VirtualFile> batch) throws IOException {
    List<String> selected = batch.stream().map(VirtualFile::path).collect(Collectors.toList());
    JSSummariesResponse summary;
    try {
      summary = summaries.send(tree, selected);
    } catch (IOException | RuntimeException e) {
      // Without the summaries this batch cannot be embedded, and the customer's endpoint was not
      // called, so nothing was spent. The other batches can still work.
      summaryFailures.incrementAndGet();
      skip(batch.size(), "could not fetch the summaries: " + BatchEmbedder.describe(e));
      return;
    }
    if (dryRun) {
      return;
    }

    List<String> tooLong = new ArrayList<>();
    List<EmbeddingInput> inputs = buildInputs(batch, summary, tooLong);
    BatchEmbedder.Result result = embedder.embed(inputs);
    for (EmbeddingInput input : result.dropped) {
      tooLong.add(input.fileName);
    }
    warnNotEmbedded(tooLong);
    if (!result.skipped.isEmpty()) {
      skip(result.skipped.size(), result.skipReason);
    }
    if (!result.embeddings.isEmpty()) {
      upload(result.embeddings);
    }
  }

  /** Call after every batch has finished. Prints one warning if not a single batch got its summaries. */
  void warnIfNothingWorked() {
    int total = batches.get();
    if (total > 0 && summaryFailures.get() == total) {
      System.err.printf(
          "Could not fetch the summaries for any of the %d batches, so no embeddings were generated in this run."
              + " The files will be offered again on the next record commit.%n",
          total);
    }
  }

  /**
   * Call after every batch has finished. The server expects the files before the commits, so that a
   * run that left files without a vector records no commits and the next run starts over.
   */
  void failIfAnyBatchFailed() throws EmbeddingRunFailedException {
    int n = failedFiles.get();
    if (n > 0) {
      throw new EmbeddingRunFailedException(
          "Client-side embedding failed: "
              + n
              + (n == 1 ? " file was" : " files were")
              + " skipped, so no commits were recorded. Fix the problem above and run record commit again;"
              + " the files will be retried.",
          null);
    }
  }

  private void upload(List<FileEmbedding> vectors) {
    try {
      onEmbedded.accept(embeddingsSender.send(vectors));
    } catch (IOException | RuntimeException e) {
      skip(vectors.size(), "could not upload the embeddings: " + BatchEmbedder.describe(e));
    }
  }

  private void skip(int files, String reason) {
    failedFiles.addAndGet(files);
    onSkipped.accept(files);
    System.err.printf(
        "Skipping %d %s (they will be retried on the next record commit): %s%n",
        files, files == 1 ? "file" : "files", reason);
  }

  /**
   * Files that cannot be made short enough for the model are not an error and are not retried on the
   * next run, since they would come out the same, so they get their own warning instead of the
   * "skipped" one.
   */
  private void warnNotEmbedded(List<String> files) {
    if (files.isEmpty()) {
      return;
    }
    int shown = Math.min(files.size(), 5);
    String names = String.join(", ", files.subList(0, shown)) + (files.size() > shown ? " and " + (files.size() - shown) + " more" : "");
    System.err.printf(
        "Not embedding %d %s: nothing is left after trimming to the model's %d-token limit (for example a minified"
            + " file that is a single very long line). It will be left out on every run until it changes: %s%n",
        files.size(), files.size() == 1 ? "file" : "files", embedder.maxTokensPerInput(), names);
  }

  /**
   * @param tooLong receives the names of the files that cannot be trimmed to the model's limit
   */
  private List<EmbeddingInput> buildInputs(List<VirtualFile> batch, JSSummariesResponse summary, List<String> tooLong)
      throws IOException {
    TokenCounter counter = embedder.tokenCounter();
    List<EmbeddingInput> inputs = new ArrayList<>();
    for (VirtualFile file : batch) {
      String content = read(file);
      if (content.trim().isEmpty()) {
        continue; // the server skips blank files too
      }
      // top-level files belong to the folder named "", exactly as in the server's own embedder
      String folder = FilenameUtils.getPathNoEndSeparator(file.path());
      String folderSummary = summary.dirSummaries == null ? null : summary.dirSummaries.get(folder);

      String text = EmbeddingText.build(summary.repoSummary, folderSummary, file.path(), content);
      text = EmbeddingText.fitToLimit(text, counter, embedder.maxTokensPerInput());
      if (text == null) {
        tooLong.add(file.path());
      } else {
        inputs.add(new EmbeddingInput(file.path(), file.blob().name(), text, counter.count(text)));
      }
    }
    return inputs;
  }

  private static String read(VirtualFile file) throws IOException {
    ByteArrayOutputStream bytes = new ByteArrayOutputStream();
    file.writeTo(bytes);
    return new String(bytes.toByteArray(), StandardCharsets.UTF_8);
  }
}
