package com.launchableinc.ingest.commits;

import static com.google.common.truth.Truth.assertThat;

import java.io.IOException;
import java.util.ArrayList;
import java.util.List;
import org.junit.Test;

public class BatchingConsumerTest {
  @Test
  public void splitsIntoBatchesAndFlushesTheRemainderOnClose() throws IOException {
    List<List<Integer>> batches = new ArrayList<>();

    try (BatchingConsumer<Integer> consumer = new BatchingConsumer<>(batches::add, 1024)) {
      for (int i = 0; i < 2500; i++) {
        consumer.accept(i);
      }
    }

    assertThat(batches).hasSize(3);
    assertThat(batches.get(0)).hasSize(1024);
    assertThat(batches.get(1)).hasSize(1024);
    assertThat(batches.get(2)).hasSize(452);
    assertThat(batches.get(2).get(0)).isEqualTo(2048);
  }

  @Test
  public void sinkOwnsTheBatchAndLaterItemsDoNotChangeIt() throws IOException {
    List<List<String>> batches = new ArrayList<>();
    BatchingConsumer<String> consumer = new BatchingConsumer<>(batches::add, 2);

    consumer.accept("a");
    consumer.accept("b");
    consumer.accept("c");
    consumer.close();

    assertThat(batches).hasSize(2);
    assertThat(batches.get(0)).containsExactly("a", "b").inOrder();
    assertThat(batches.get(1)).containsExactly("c");
  }

  @Test
  public void flushWithNothingPendingSendsNothing() throws IOException {
    List<List<String>> batches = new ArrayList<>();
    BatchingConsumer<String> consumer = new BatchingConsumer<>(batches::add, 2);

    consumer.flush();
    consumer.close();

    assertThat(batches).isEmpty();
  }
}
