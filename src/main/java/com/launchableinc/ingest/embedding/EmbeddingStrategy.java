package com.launchableinc.ingest.embedding;

import java.io.IOException;
import java.util.List;

public interface EmbeddingStrategy {
    List<FileEmbeddingResult> embed(List<FileToEmbed> files) throws IOException;

    String modelName();

    int dimensions();
}
