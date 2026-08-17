package com.launchableinc.ingest.embedding;

import com.knuddels.jtokkit.Encodings;
import com.knuddels.jtokkit.api.Encoding;
import com.knuddels.jtokkit.api.EncodingType;

public class Cl100kTokenizer implements Tokenizer {
    private final Encoding encoding;

    public Cl100kTokenizer() {
        this.encoding = Encodings.newDefaultEncodingRegistry().getEncoding(EncodingType.CL100K_BASE);
    }

    @Override
    public int countTokens(String text) {
        return encoding.countTokens(text);
    }

    @Override
    public boolean isAccurate() {
        return true;
    }
}
