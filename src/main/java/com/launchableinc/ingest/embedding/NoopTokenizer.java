package com.launchableinc.ingest.embedding;

public class NoopTokenizer implements Tokenizer {
    @Override
    public int countTokens(String text) {
        return 0;
    }

    @Override
    public boolean isAccurate() {
        return false;
    }
}
