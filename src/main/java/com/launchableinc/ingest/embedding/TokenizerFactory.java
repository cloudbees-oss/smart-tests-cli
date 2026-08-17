package com.launchableinc.ingest.embedding;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.net.URL;

public class TokenizerFactory {
    private static final Logger logger = LoggerFactory.getLogger(TokenizerFactory.class);

    /**
     * Creates a tokenizer using the provider name returned by the server options response.
     * Falls back to URL-host sniffing when provider is null.
     */
    public static Tokenizer create(String provider, URL endpoint) {
        String override = System.getenv("SMART_TESTS_EMBEDDING_TOKENIZER");
        if (override != null) {
            switch (override) {
                case "cl100k_base":
                    logger.info("Tokenizer: cl100k_base (forced via SMART_TESTS_EMBEDDING_TOKENIZER)");
                    return new Cl100kTokenizer();
                case "none":
                    logger.info("Tokenizer: none (forced via SMART_TESTS_EMBEDDING_TOKENIZER)");
                    return new NoopTokenizer();
                default:
                    throw new IllegalArgumentException(
                        "Unknown SMART_TESTS_EMBEDDING_TOKENIZER value: " + override
                            + ". Valid values: cl100k_base, none");
            }
        }

        if (provider != null) {
            switch (provider) {
                case "openai":
                case "azure_openai":
                    logger.info("Tokenizer: cl100k_base (provider={})", provider);
                    return new Cl100kTokenizer();
                case "custom":
                    logger.info("Tokenizer: none (provider=custom)");
                    return new NoopTokenizer();
                default:
                    logger.info("Tokenizer: none (unknown provider {}). Set SMART_TESTS_EMBEDDING_TOKENIZER=cl100k_base if this endpoint serves an OpenAI-family model.", provider);
                    return new NoopTokenizer();
            }
        }

        // Fallback: sniff from URL host
        String host = endpoint.getHost();
        if ("api.openai.com".equals(host) || host.endsWith(".openai.azure.com")) {
            logger.info("Tokenizer: cl100k_base (detected OpenAI/Azure endpoint)");
            return new Cl100kTokenizer();
        }

        logger.info("Tokenizer: none (unrecognized host {}). Set SMART_TESTS_EMBEDDING_TOKENIZER=cl100k_base if this endpoint serves an OpenAI-family model.", host);
        return new NoopTokenizer();
    }

    /** Convenience overload when no provider is available (URL-sniffing only). */
    public static Tokenizer create(URL endpoint) {
        return create(null, endpoint);
    }
}
