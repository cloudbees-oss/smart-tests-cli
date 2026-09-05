package com.launchableinc.ingest.embedding;

import org.apache.http.impl.client.CloseableHttpClient;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.net.MalformedURLException;
import java.net.URL;

/**
 * Builds the right EmbeddingStrategy from workspace options + env vars.
 * When embeddingAugmentation is true, wraps RemoteEmbeddingStrategy in AugmentedEmbeddingStrategy.
 */
public class EmbeddingStrategyFactory {
    private static final Logger logger = LoggerFactory.getLogger(EmbeddingStrategyFactory.class);

    /**
     * @param provider             embedding provider from server options ("openai", "azure_openai", "custom", or null)
     * @param embeddingHttpClient  plain unauthenticated client for the customer's LLM endpoint
     * @param summariesHttpClient  Launchable-authenticated client for the summaries endpoint
     */
    public static EmbeddingStrategy create(
            URL embeddingEndpoint,
            String model,
            int dimensions,
            String apiKey,
            boolean embeddingAugmentation,
            String provider,
            URL summariesUrl,
            CloseableHttpClient embeddingHttpClient,
            CloseableHttpClient summariesHttpClient) throws MalformedURLException {

        Tokenizer tokenizer = TokenizerFactory.create(provider, embeddingEndpoint);
        EmbeddingStrategy strategy = new RemoteEmbeddingStrategy(
                embeddingEndpoint, model, dimensions, apiKey, embeddingHttpClient, tokenizer);

        if (embeddingAugmentation) {
            logger.info("Embedding augmentation enabled; will fetch summaries from server");
            RepoContextProvider contextProvider = new ServerRepoContextProvider(summariesUrl, summariesHttpClient);
            strategy = new AugmentedEmbeddingStrategy(strategy, contextProvider);
        }

        return strategy;
    }
}
