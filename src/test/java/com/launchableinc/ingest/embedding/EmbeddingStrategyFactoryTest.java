package com.launchableinc.ingest.embedding;

import static com.google.common.truth.Truth.assertThat;
import static org.mockserver.model.HttpRequest.request;
import static org.mockserver.model.HttpResponse.response;

import org.apache.http.impl.client.HttpClients;
import org.junit.Rule;
import org.junit.Test;
import org.junit.runner.RunWith;
import org.junit.runners.JUnit4;
import org.mockserver.client.MockServerClient;
import org.mockserver.junit.MockServerRule;

import java.net.InetSocketAddress;
import java.net.URL;

@RunWith(JUnit4.class)
public class EmbeddingStrategyFactoryTest {

    @Rule public MockServerRule mockServerRule = new MockServerRule(this);
    private MockServerClient mockServerClient;

    @Test
    public void createReturnsRemoteStrategyWithoutAugmentation() throws Exception {
        InetSocketAddress addr = mockServerClient.remoteAddress();
        URL endpoint = new URL(String.format("http://%s:%d/v1/embeddings", addr.getHostString(), addr.getPort()));
        URL summariesUrl = new URL(String.format("http://%s:%d/collect/summaries", addr.getHostString(), addr.getPort()));

        EmbeddingStrategy strategy = EmbeddingStrategyFactory.create(
            endpoint, "text-embedding-3-small", 1536, "api-key",
            false, null, summariesUrl, HttpClients.createDefault(), HttpClients.createDefault());

        assertThat(strategy).isInstanceOf(RemoteEmbeddingStrategy.class);
        assertThat(strategy.modelName()).isEqualTo("text-embedding-3-small");
        assertThat(strategy.dimensions()).isEqualTo(1536);
    }

    @Test
    public void createWrapsInAugmentedStrategyWhenEnabled() throws Exception {
        InetSocketAddress addr = mockServerClient.remoteAddress();
        URL endpoint = new URL(String.format("http://%s:%d/v1/embeddings", addr.getHostString(), addr.getPort()));
        URL summariesUrl = new URL(String.format("http://%s:%d/collect/summaries", addr.getHostString(), addr.getPort()));

        EmbeddingStrategy strategy = EmbeddingStrategyFactory.create(
            endpoint, "text-embedding-3-small", 1536, "api-key",
            true, null, summariesUrl, HttpClients.createDefault(), HttpClients.createDefault());

        assertThat(strategy).isInstanceOf(AugmentedEmbeddingStrategy.class);
        assertThat(strategy.modelName()).isEqualTo("text-embedding-3-small");
        assertThat(strategy.dimensions()).isEqualTo(1536);
    }

    @Test
    public void endToEndWithoutAugmentation() throws Exception {
        mockServerClient
            .when(request().withMethod("POST").withPath("/v1/embeddings"))
            .respond(response()
                .withStatusCode(200)
                .withHeader("Content-Type", "application/json")
                .withBody("{\"data\":[{\"index\":0,\"embedding\":[0.6,0.0,0.8]}]}"));

        InetSocketAddress addr = mockServerClient.remoteAddress();
        URL endpoint = new URL(String.format("http://%s:%d/v1/embeddings", addr.getHostString(), addr.getPort()));
        URL summariesUrl = new URL(String.format("http://%s:%d/collect/summaries", addr.getHostString(), addr.getPort()));

        EmbeddingStrategy strategy = EmbeddingStrategyFactory.create(
            endpoint, "text-embedding-3-small", 3, "api-key",
            false, null, summariesUrl, HttpClients.createDefault(), HttpClients.createDefault());

        java.util.List<FileEmbeddingResult> results = strategy.embed(
            java.util.Collections.singletonList(new FileToEmbed("A.java", "class A {}", "sha1")));

        assertThat(results).hasSize(1);
        assertThat(results.get(0).fileName).isEqualTo("A.java");
        // vector [0.6, 0.0, 0.8] has norm 1.0, so already normalized
        assertThat(results.get(0).embedding[0]).isWithin(1e-5f).of(0.6f);
    }

    @Test
    public void providerOpenaiPicksCl100kTokenizer() throws Exception {
        InetSocketAddress addr = mockServerClient.remoteAddress();
        URL endpoint = new URL(String.format("http://%s:%d/v1/embeddings", addr.getHostString(), addr.getPort()));
        URL summariesUrl = new URL(String.format("http://%s:%d/collect/summaries", addr.getHostString(), addr.getPort()));

        // localhost would normally pick NoopTokenizer; provider="openai" overrides that
        EmbeddingStrategy strategy = EmbeddingStrategyFactory.create(
            endpoint, "text-embedding-3-small", 1536, "api-key",
            false, "openai", summariesUrl, HttpClients.createDefault(), HttpClients.createDefault());

        assertThat(strategy).isInstanceOf(RemoteEmbeddingStrategy.class);
    }

    @Test
    public void providerCustomPicksNoopTokenizer() throws Exception {
        InetSocketAddress addr = mockServerClient.remoteAddress();
        URL endpoint = new URL(String.format("http://%s:%d/v1/embeddings", addr.getHostString(), addr.getPort()));
        URL summariesUrl = new URL(String.format("http://%s:%d/collect/summaries", addr.getHostString(), addr.getPort()));

        EmbeddingStrategy strategy = EmbeddingStrategyFactory.create(
            endpoint, "my-model", 512, "api-key",
            false, "custom", summariesUrl, HttpClients.createDefault(), HttpClients.createDefault());

        assertThat(strategy).isInstanceOf(RemoteEmbeddingStrategy.class);
    }
}
