package com.launchableinc.ingest.commits;

import java.io.IOException;
import java.util.function.Consumer;

/**
 * Consumers that spool items it accepts and process them in bulk.
 */
public interface FlushableConsumer<T> extends Consumer<T> {
  /**
   * Process all items that have been accepted so far.
   */
  void flush() throws IOException;

  static <T> FlushableConsumer<T> of(Consumer<T> c) {
    return new FlushableConsumer<T>() {
      @Override
      public void flush() throws IOException {
        // noop
      }

      @Override
      public void accept(T t) {
        c.accept(t);
      }
    };
  }
}
