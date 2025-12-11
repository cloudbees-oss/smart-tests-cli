package com.launchableinc.ingest.commits;

import java.io.IOException;
import java.time.Duration;
import java.time.Instant;
import java.util.ArrayList;
import java.util.List;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.function.Function;

import static java.time.Instant.now;

/**
 * Given multiple concurrent slow {@link Consumer}s, each g oing over a large
 * number of items in parallel,
 * provide a progress report to show that the work is still in progress.
 */
class ProgressReporter<T> {
  private final Function<T, String> printer;
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

  ProgressReporter(Function<T, String> printer, Duration reportInterval) {
    this.printer = printer;
    this.reportInterval = reportInterval;
    this.nextReportTime = now().plus(reportInterval);
  }

  /**
   * Deals with one serial stream of work.
   */
  class Consumer implements FlushableConsumer<T>, AutoCloseable {
    private final FlushableConsumer<T> base;
    private final List<T> pool = new ArrayList<>();

    Consumer(FlushableConsumer<T> base) {
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
        synchronized (ProgressReporter.this) {
          if (now().isAfter(nextReportTime)) {
            print(completed.get(), workload.get(), x);
            nextReportTime = now().plus(reportInterval);
          }
        }
        base.accept(x);
        completed.incrementAndGet();
      }
      pool.clear();
      base.flush();
    }

    @Override
    public void close() throws IOException {
      flush();
    }
  }

  Consumer newConsumer(FlushableConsumer<T> base) {
    return new Consumer(base);
  }

  protected void print(int c, int w, T x) {
    int width = String.valueOf(w).length();
    System.err.printf("%s/%d: %s%n", pad(c, width), w, printer.apply(x));
  }

  static String pad(int i, int width) {
    String s = String.valueOf(i);
    while (s.length() < width) {
      s = " " + s;
    }
    return s;
  }
}
