package com.launchableinc.ingest.commits;

import org.junit.Test;

import java.time.Duration;
import java.util.ArrayList;
import java.util.HashSet;
import java.util.List;
import java.util.Set;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.Future;

import static com.google.common.truth.Truth.*;
import static java.util.Collections.*;

public class ProgressReporterTest {
  ProgressReporter pr = new ProgressReporter(Duration.ofMillis(100)) {
    int cc = 0;
    int ww = 0;
    @Override
    protected void print(int c, int w) {
      super.print(c, w);

      // ensure numbers are monotonically increasing
      assertThat(c).isAtLeast(cc);
      assertThat(w).isAtLeast(ww);
      cc = c;
      ww = w;
    }
  };

  /**
   * Tests the most important bit -- that all items are processed.
   */
  @Test
  public void serial() throws Exception {
    List<String> done = new ArrayList<>();
    try (FlushableConsumer<String> x = pr.newProducer(FlushableConsumer.of(s -> {
      done.add(s);
      sleep();
    }))) {
      for (int i = 0; i < 100; i++) {
        x.accept("item " + i);
      }
    }
    assertThat(done.size()).isEqualTo(100);
  }

  /**
   * Perform work in parallel and make sure they all do get processed.
   */
  @Test
  public void parallel() throws Exception {
    Set<String> done = synchronizedSet(new HashSet<>());

    ExecutorService es = Executors.newFixedThreadPool(10);
    List<Future<?>> all = new ArrayList<>();
    for (int i=0; i<10; i++) {
      final int ii = i;
      all.add(es.submit(() -> {
        try (FlushableConsumer<String> x = pr.newProducer(FlushableConsumer.of(s -> {done.add(s);sleep();}))) {
            for (int j = 0; j < 100; j++) {
                x.accept("item " + (ii*100+j));
            }
            return null;
        }
      }));
    }
    for (Future<?> f : all) {
      f.get();
    }
    es.shutdown();

    assertThat(done.size()).isEqualTo(1000);
    for (int i=0; i<1000; i++) {
      assertThat(done).contains("item " + i);
    }
  }

  private static void sleep() {
    try {
      Thread.sleep(10);
    } catch (InterruptedException e) {
      throw new UnsupportedOperationException();
    }
  }

  @Test
  public void pad() {
    assertThat(ProgressReporter.pad(5,3)).isEqualTo("  5");
    assertThat(ProgressReporter.pad(15,3)).isEqualTo(" 15");
    assertThat(ProgressReporter.pad(1234,3)).isEqualTo("1234");
  }

  @Test
  public void incrementCompletedCountsAWholeBatchAtOnce() {
    List<String> printed = new ArrayList<>();
    // a negative interval makes every call due, so each one prints
    ProgressReporter reporter = new ProgressReporter(Duration.ofSeconds(-1)) {
      @Override
      protected void print(int c, int w) {
        printed.add(c + "/" + w);
      }
    };

    reporter.incrementCompleted(1024);
    reporter.incrementCompleted(452);

    assertThat(printed).containsExactly("1024/0", "1476/0").inOrder();
  }
}
