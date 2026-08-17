package com.launchableinc.ingest.embedding;

import java.io.IOException;
import java.util.ArrayList;
import java.util.List;

/**
 * Decorator that prepends server-generated repo/directory summaries to each file's content
 * before passing to the inner strategy. The prepend format matches the server template exactly
 * (FileEmbeddingService augmentation logic).
 */
public class AugmentedEmbeddingStrategy implements EmbeddingStrategy {
    private final EmbeddingStrategy inner;
    private final RepoContextProvider contextProvider;

    public AugmentedEmbeddingStrategy(EmbeddingStrategy inner, RepoContextProvider contextProvider) {
        this.inner = inner;
        this.contextProvider = contextProvider;
    }

    @Override
    public String modelName() {
        return inner.modelName();
    }

    @Override
    public int dimensions() {
        return inner.dimensions();
    }

    @Override
    public List<FileEmbeddingResult> embed(List<FileToEmbed> files) throws IOException {
        Summaries summaries = contextProvider.getSummaries(files);
        List<FileToEmbed> augmented = new ArrayList<>(files.size());
        for (FileToEmbed f : files) {
            augmented.add(new FileToEmbed(f.fileName, buildAugmentedContent(summaries, f), f.blobSha));
        }
        return inner.embed(augmented);
    }

    private String buildAugmentedContent(Summaries s, FileToEmbed f) {
        String dir = extractParentDir(f.fileName);
        return String.format(
            "Repository summary: %s\nDirectory summary: %s\nFile name: %s\n----\n%s",
            s.repoSummary,
            s.dirSummaries.getOrDefault(dir, ""),
            f.fileName,
            f.content);
    }

    private static String extractParentDir(String fileName) {
        int slash = fileName.lastIndexOf('/');
        return slash > 0 ? fileName.substring(0, slash) : "";
    }
}
