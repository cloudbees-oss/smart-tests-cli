package com.launchableinc.ingest.embedding;

public interface Tokenizer {
    int countTokens(String text);

    /** Whether this counter is accurate (jtokkit) or a no-op (unknown provider). */
    boolean isAccurate();
}
