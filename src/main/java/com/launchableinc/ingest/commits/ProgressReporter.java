package com.launchableinc.ingest.commits;

import java.io.IOException;
import java.time.Duration;
import java.time.Instant;
import java.util.ArrayList;
import java.util.List;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.function.Consumer;

import static java.time.Instant.now;

/**
 * Given multiple concurrent slow {@link Producer}s, each g oing over a large
 * number of items in parallel,
 * provide a progress report to show that the work is still in progress.
 */
class ProgressReporter {
  private final Duration reportInterval;
  private Instant nextReportTime;

  /**
   * Number of items that need to be processed, across all consumers.
   */
  private final AtomicInteger workload = new AtomicInteger();
  /**
   * Number of items that have already been processed, across all consumers.
   */
  private final AtomicInteger completed = new AtomicInteger();

  ProgressReporter(Duration reportInterval) {
    this.reportInterval = reportInterval;
    this.nextReportTime = now().plus(reportInterval);
  }

  public void incrementCompleted() {
    completed.incrementAndGet();
    maybePrintStatus();
  }

  /** Several items are completed at once, for example a batch. */
  public void incrementCompleted(int items) {
    completed.addAndGet(items);
    maybePrintStatus();
  }

  /**
   * Deals with one serial stream of work.
   */
  class Producer<T> implements FlushableConsumer<T> {
    private final FlushableConsumer<T> base;
    private final List<T> pool = new ArrayList<>();

    Producer(FlushableConsumer<T> base) {
      this.base = base;
    }

    @Override
    public void accept(T t) {
      pool.add(t);
      workload.incrementAndGet();
    }

    @Override
    public void flush() throws IOException {
      for (T x : pool) {
        maybePrintStatus();
        base.accept(x);
      }
      pool.clear();
      base.flush();
    }

    @Override
    public void close() throws IOException {
      flush();
      base.close();
    }
  }

  private synchronized void maybePrintStatus() {
    if (now().isAfter(nextReportTime)) {
      print(completed.get(), workload.get());
      nextReportTime = now().plus(reportInterval);
    }
  }

  /**
   * Decorates the {@link Consumer} on the producing end to count the total number of work to be completed.
   */
  <T> FlushableConsumer<T> newProducer(FlushableConsumer<T> base) {
    return new Producer<>(base);
  }

  protected void print(int c, int w) {
    int width = String.valueOf(w).length();
    System.err.printf("%s/%d%n", pad(c, width), w);
  }

  static String pad(int i, int width) {
    String s = String.valueOf(i);
    while (s.length() < width) {
      s = " " + s;
    }
    return s;
  }
}
