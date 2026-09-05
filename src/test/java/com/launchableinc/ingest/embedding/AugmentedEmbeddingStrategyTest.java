package com.launchableinc.ingest.embedding;

import static com.google.common.truth.Truth.assertThat;

import org.junit.Test;
import org.junit.runner.RunWith;
import org.junit.runners.JUnit4;

import java.io.IOException;
import java.util.Arrays;
import java.util.Collections;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

@RunWith(JUnit4.class)
public class AugmentedEmbeddingStrategyTest {

    /** Captures the augmented inputs that were passed to the inner strategy. */
    private static class CapturingStrategy implements EmbeddingStrategy {
        List<FileToEmbed> capturedFiles;

        @Override
        public List<FileEmbeddingResult> embed(List<FileToEmbed> files) {
            this.capturedFiles = files;
            return Collections.emptyList();
        }

        @Override public String modelName() { return "test"; }
        @Override public int dimensions() { return 2; }
    }

    @Test
    public void prependsRepoAndDirSummaryWithExactFormat() throws IOException {
        CapturingStrategy inner = new CapturingStrategy();

        Map<String, String> dirSummaries = new HashMap<>();
        dirSummaries.put("src/foo", "Foo utilities");
        Summaries summaries = new Summaries("Repo about testing", dirSummaries);

        RepoContextProvider provider = files -> summaries;

        AugmentedEmbeddingStrategy strategy = new AugmentedEmbeddingStrategy(inner, provider);

        List<FileToEmbed> files = Collections.singletonList(
            new FileToEmbed("src/foo/Bar.java", "class Bar {}", "sha1"));

        strategy.embed(files);

        assertThat(inner.capturedFiles).hasSize(1);
        String augmented = inner.capturedFiles.get(0).content;
        assertThat(augmented).isEqualTo(
            "Repository summary: Repo about testing\n" +
            "Directory summary: Foo utilities\n" +
            "File name: src/foo/Bar.java\n" +
            "----\n" +
            "class Bar {}");
    }

    @Test
    public void usesEmptyDirSummaryWhenNoMatchingDirectory() throws IOException {
        CapturingStrategy inner = new CapturingStrategy();

        Summaries summaries = new Summaries("Repo summary", Collections.emptyMap());
        RepoContextProvider provider = files -> summaries;

        AugmentedEmbeddingStrategy strategy = new AugmentedEmbeddingStrategy(inner, provider);

        List<FileToEmbed> files = Collections.singletonList(
            new FileToEmbed("Root.java", "class Root {}", "sha1"));

        strategy.embed(files);

        String augmented = inner.capturedFiles.get(0).content;
        assertThat(augmented).isEqualTo(
            "Repository summary: Repo summary\n" +
            "Directory summary: \n" +
            "File name: Root.java\n" +
            "----\n" +
            "class Root {}");
    }

    @Test
    public void preservesBlobShaAndFileName() throws IOException {
        CapturingStrategy inner = new CapturingStrategy();
        RepoContextProvider provider = files -> new Summaries("r", Collections.emptyMap());

        AugmentedEmbeddingStrategy strategy = new AugmentedEmbeddingStrategy(inner, provider);

        List<FileToEmbed> files = Arrays.asList(
            new FileToEmbed("a/A.java", "A content", "sha-a"),
            new FileToEmbed("b/B.java", "B content", "sha-b"));

        strategy.embed(files);

        assertThat(inner.capturedFiles.get(0).fileName).isEqualTo("a/A.java");
        assertThat(inner.capturedFiles.get(0).blobSha).isEqualTo("sha-a");
        assertThat(inner.capturedFiles.get(1).fileName).isEqualTo("b/B.java");
        assertThat(inner.capturedFiles.get(1).blobSha).isEqualTo("sha-b");
    }

    @Test
    public void delegatesModelNameAndDimensions() {
        EmbeddingStrategy inner = new CapturingStrategy() {
            @Override public String modelName() { return "text-embedding-3-small"; }
            @Override public int dimensions() { return 1536; }
        };
        RepoContextProvider provider = files -> new Summaries("", Collections.emptyMap());

        AugmentedEmbeddingStrategy strategy = new AugmentedEmbeddingStrategy(inner, provider);

        assertThat(strategy.modelName()).isEqualTo("text-embedding-3-small");
        assertThat(strategy.dimensions()).isEqualTo(1536);
    }
}
