package com.launchableinc.ingest.embedding;

import static com.google.common.truth.Truth.assertThat;
import static org.mockserver.model.HttpRequest.request;
import static org.mockserver.model.HttpResponse.response;

import org.apache.http.impl.client.CloseableHttpClient;
import org.apache.http.impl.client.HttpClients;
import org.junit.Rule;
import org.junit.Test;
import org.junit.runner.RunWith;
import org.junit.runners.JUnit4;
import org.mockserver.client.MockServerClient;
import org.mockserver.junit.MockServerRule;

import java.net.InetSocketAddress;
import java.net.URL;
import java.util.Arrays;
import java.util.Collections;
import java.util.List;

@RunWith(JUnit4.class)
public class RemoteEmbeddingStrategyTest {
    @Rule public MockServerRule mockServerRule = new MockServerRule(this);
    private MockServerClient mockServerClient;

    private static final int DIMS = 2;

    @Test
    public void embedsSingleBatch() throws Exception {
        mockServerClient
            .when(request().withMethod("POST").withPath("/v1/embeddings"))
            .respond(response()
                .withStatusCode(200)
                .withHeader("Content-Type", "application/json")
                .withBody("{\"data\":[{\"index\":0,\"embedding\":[1.0,0.0]},{\"index\":1,\"embedding\":[0.0,1.0]}]}"));

        RemoteEmbeddingStrategy strategy = buildStrategy(false);

        List<FileToEmbed> files = Arrays.asList(
            new FileToEmbed("a.java", "class A {}", "abc1"),
            new FileToEmbed("b.java", "class B {}", "abc2")
        );

        List<FileEmbeddingResult> results = strategy.embed(files);

        assertThat(results).hasSize(2);
        assertThat(results.get(0).fileName).isEqualTo("a.java");
        assertThat(results.get(0).blobSha).isEqualTo("abc1");
        assertThat(results.get(1).fileName).isEqualTo("b.java");
        assertThat(results.get(1).blobSha).isEqualTo("abc2");
        // [1.0, 0.0] is already unit length
        assertThat(results.get(0).embedding[0]).isWithin(1e-6f).of(1.0f);
        assertThat(results.get(0).embedding[1]).isWithin(1e-6f).of(0.0f);
    }

    @Test
    public void l2NormalizesVectors() throws Exception {
        mockServerClient
            .when(request().withMethod("POST").withPath("/v1/embeddings"))
            .respond(response()
                .withStatusCode(200)
                .withHeader("Content-Type", "application/json")
                .withBody("{\"data\":[{\"index\":0,\"embedding\":[3.0,4.0]}]}"));

        RemoteEmbeddingStrategy strategy = buildStrategy(false);

        List<FileEmbeddingResult> results = strategy.embed(
            Collections.singletonList(new FileToEmbed("f.java", "content", "sha1")));

        assertThat(results).hasSize(1);
        float[] v = results.get(0).embedding;
        // [3,4] normalized = [0.6, 0.8]
        assertThat(v[0]).isWithin(1e-5f).of(0.6f);
        assertThat(v[1]).isWithin(1e-5f).of(0.8f);
    }

    @Test
    public void splitsOnTooManyTokensWhenNoopTokenizer() throws Exception {
        mockServerClient
            .when(request().withMethod("POST").withPath("/v1/embeddings"), org.mockserver.matchers.Times.once())
            .respond(response()
                .withStatusCode(400)
                .withHeader("Content-Type", "application/json")
                .withBody("{\"error\":{\"message\":\"too_many_tokens\",\"type\":\"invalid_request_error\"}}"));

        mockServerClient
            .when(request().withMethod("POST").withPath("/v1/embeddings"))
            .respond(response()
                .withStatusCode(200)
                .withHeader("Content-Type", "application/json")
                .withBody("{\"data\":[{\"index\":0,\"embedding\":[0.6,0.8]}]}"));

        RemoteEmbeddingStrategy strategy = buildStrategy(false);

        List<FileToEmbed> files = Arrays.asList(
            new FileToEmbed("a.java", "class A {}", "sha1"),
            new FileToEmbed("b.java", "class B {}", "sha2")
        );

        List<FileEmbeddingResult> results = strategy.embed(files);
        assertThat(results).hasSize(2);
        // [0.6, 0.8] is already unit length
        assertThat(results.get(0).embedding[0]).isWithin(1e-5f).of(0.6f);
        assertThat(results.get(0).embedding[1]).isWithin(1e-5f).of(0.8f);
    }

    @Test
    public void retriesOn5xxThenSucceeds() throws Exception {
        mockServerClient
            .when(request().withMethod("POST").withPath("/v1/embeddings"), org.mockserver.matchers.Times.once())
            .respond(response().withStatusCode(503).withBody("Service Unavailable"));

        mockServerClient
            .when(request().withMethod("POST").withPath("/v1/embeddings"))
            .respond(response()
                .withStatusCode(200)
                .withHeader("Content-Type", "application/json")
                .withBody("{\"data\":[{\"index\":0,\"embedding\":[1.0,0.0]}]}"));

        // Use a tiny retry base so the test doesn't sleep long
        RemoteEmbeddingStrategy strategy = buildStrategyWithRetryBase(false, 1);

        List<FileEmbeddingResult> results = strategy.embed(
            Collections.singletonList(new FileToEmbed("f.java", "content", "sha1")));

        assertThat(results).hasSize(1);
    }

    @Test
    public void retriesOn429ThenSucceeds() throws Exception {
        mockServerClient
            .when(request().withMethod("POST").withPath("/v1/embeddings"), org.mockserver.matchers.Times.once())
            .respond(response().withStatusCode(429).withBody("Rate limited"));

        mockServerClient
            .when(request().withMethod("POST").withPath("/v1/embeddings"))
            .respond(response()
                .withStatusCode(200)
                .withHeader("Content-Type", "application/json")
                .withBody("{\"data\":[{\"index\":0,\"embedding\":[1.0,0.0]}]}"));

        RemoteEmbeddingStrategy strategy = buildStrategyWithRetryBase(false, 1);

        List<FileEmbeddingResult> results = strategy.embed(
            Collections.singletonList(new FileToEmbed("f.java", "content", "sha1")));

        assertThat(results).hasSize(1);
    }

    @Test
    public void doesNotRetryOn4xx() throws Exception {
        mockServerClient
            .when(request().withMethod("POST").withPath("/v1/embeddings"))
            .respond(response().withStatusCode(401).withBody("Unauthorized"));

        RemoteEmbeddingStrategy strategy = buildStrategy(false);

        try {
            strategy.embed(Collections.singletonList(new FileToEmbed("f.java", "content", "sha1")));
            throw new AssertionError("Expected IOException");
        } catch (java.io.IOException e) {
            assertThat(e.getMessage()).contains("401");
        }
    }

    @Test
    public void trimsFileExceedingTokenLimit() throws Exception {
        // Cl100kTokenizer is accurate; build a file that is over 8100 tokens
        // We can't easily make a real 8100-token file in a unit test, so we use
        // a strategy with a custom tokenizer that reports the file as over-limit
        // on first call but under-limit after trimming.
        mockServerClient
            .when(request().withMethod("POST").withPath("/v1/embeddings"))
            .respond(response()
                .withStatusCode(200)
                .withHeader("Content-Type", "application/json")
                .withBody("{\"data\":[{\"index\":0,\"embedding\":[1.0,0.0]}]}"));

        // Tokenizer that reports content over limit until it is short enough
        Tokenizer stubbedTokenizer = new Tokenizer() {
            @Override public boolean isAccurate() { return true; }
            @Override public int countTokens(String text) {
                // Count newlines as a proxy: >32 newlines = over limit (stays non-empty after TRIM_LINES=30 removal)
                long newlines = text.chars().filter(c -> c == '\n').count();
                return newlines > 32 ? RemoteEmbeddingStrategy.MAX_TOKENS_PER_FILE + 1 : 1;
            }
        };

        InetSocketAddress addr = mockServerClient.remoteAddress();
        URL endpoint = new URL(String.format("http://%s:%d/v1/embeddings", addr.getHostString(), addr.getPort()));

        try (CloseableHttpClient httpClient = HttpClients.createDefault()) {
            RemoteEmbeddingStrategy strategy = new RemoteEmbeddingStrategy(
                endpoint, "text-embedding-3-small", DIMS, "test-key", httpClient, stubbedTokenizer);

            // 40 lines so that after one TRIM_LINES=30 removal 10 remain (non-empty)
            StringBuilder sb = new StringBuilder();
            for (int i = 1; i <= 40; i++) sb.append("line").append(i).append("\n");
            String longContent = sb.toString().stripTrailing();
            List<FileEmbeddingResult> results = strategy.embed(
                Collections.singletonList(new FileToEmbed("f.java", longContent, "sha1")));

            assertThat(results).hasSize(1);
        }
    }

    @Test
    public void tokenizerFactoryPicksCl100kForOpenAI() throws Exception {
        Tokenizer t = TokenizerFactory.create(new URL("https://api.openai.com/v1/embeddings"));
        assertThat(t).isInstanceOf(Cl100kTokenizer.class);
        assertThat(t.isAccurate()).isTrue();
    }

    @Test
    public void tokenizerFactoryPicksCl100kForAzure() throws Exception {
        Tokenizer t = TokenizerFactory.create(new URL("https://mydeployment.openai.azure.com/openai/deployments/text-embedding-3-small/embeddings"));
        assertThat(t).isInstanceOf(Cl100kTokenizer.class);
    }

    @Test
    public void tokenizerFactoryPicksNoopForUnknownHost() throws Exception {
        Tokenizer t = TokenizerFactory.create(new URL("http://localhost:8080/v1/embeddings"));
        assertThat(t).isInstanceOf(NoopTokenizer.class);
        assertThat(t.isAccurate()).isFalse();
    }

    @Test
    public void tokenizerFactoryProviderOpenaiPicksCl100k() throws Exception {
        URL localEndpoint = new URL("http://localhost:8080/v1/embeddings");
        Tokenizer t = TokenizerFactory.create("openai", localEndpoint);
        assertThat(t).isInstanceOf(Cl100kTokenizer.class);
        assertThat(t.isAccurate()).isTrue();
    }

    @Test
    public void tokenizerFactoryProviderAzureOpenaiPicksCl100k() throws Exception {
        URL localEndpoint = new URL("http://localhost:8080/v1/embeddings");
        Tokenizer t = TokenizerFactory.create("azure_openai", localEndpoint);
        assertThat(t).isInstanceOf(Cl100kTokenizer.class);
        assertThat(t.isAccurate()).isTrue();
    }

    @Test
    public void tokenizerFactoryProviderCustomPicksNoop() throws Exception {
        Tokenizer t = TokenizerFactory.create("custom", new URL("https://api.openai.com/v1/embeddings"));
        assertThat(t).isInstanceOf(NoopTokenizer.class);
        assertThat(t.isAccurate()).isFalse();
    }

    @Test
    public void tokenizerFactoryNullProviderFallsBackToUrlSniffing() throws Exception {
        Tokenizer t = TokenizerFactory.create(null, new URL("https://api.openai.com/v1/embeddings"));
        assertThat(t).isInstanceOf(Cl100kTokenizer.class);
    }

    // --- helpers ---

    private RemoteEmbeddingStrategy buildStrategy(boolean accurate) throws Exception {
        return buildStrategyWithRetryBase(accurate, RemoteEmbeddingStrategy.RETRY_BASE_MS);
    }

    private RemoteEmbeddingStrategy buildStrategyWithRetryBase(boolean accurate, long retryBaseMs) throws Exception {
        InetSocketAddress addr = mockServerClient.remoteAddress();
        URL endpoint = new URL(String.format("http://%s:%d/v1/embeddings", addr.getHostString(), addr.getPort()));
        CloseableHttpClient httpClient = HttpClients.createDefault();
        Tokenizer tokenizer = accurate ? new Cl100kTokenizer() : new NoopTokenizer();
        return new RemoteEmbeddingStrategy(endpoint, "text-embedding-3-small", DIMS, "test-key",
            httpClient, tokenizer, RemoteEmbeddingStrategy.DEFAULT_RATE_LIMIT_TOKENS_PER_SEC) {
            @Override
            protected long retryBaseMs() { return retryBaseMs; }
        };
    }
}
