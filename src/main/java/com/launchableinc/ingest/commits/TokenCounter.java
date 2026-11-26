package com.launchableinc.ingest.commits;

/** Counts tokens the way the target embedding model does. */
interface TokenCounter {
  int count(String text);
}
