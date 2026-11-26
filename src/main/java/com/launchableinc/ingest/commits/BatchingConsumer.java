package com.launchableinc.ingest.commits;

import java.io.IOException;
import java.io.UncheckedIOException;
import java.util.ArrayList;
import java.util.List;

/** Buffers items and hands them to the sink in lists of at most batchSize. */
class BatchingConsumer<T> implements FlushableConsumer<T> {
  private final IOConsumer<List<T>> sink;
  private final int batchSize;
  private List<T> pending = new ArrayList<>();

  BatchingConsumer(IOConsumer<List<T>> sink, int batchSize) {
    this.sink = sink;
    this.batchSize = batchSize;
  }

  @Override
  public void accept(T t) {
    pending.add(t);
    if (pending.size() >= batchSize) {
      try {
        flush();
      } catch (IOException e) {
        throw new UncheckedIOException(e);
      }
    }
  }

  @Override
  public void flush() throws IOException {
    if (pending.isEmpty()) {
      return;
    }
    // The sink may process the batch later on another thread, so it owns this list. Never reuse it.
    List<T> batch = pending;
    pending = new ArrayList<>();
    sink.accept(batch);
  }

  @Override
  public void close() throws IOException {
    flush();
  }
}
