package com.launchableinc.ingest.embedding;

import com.fasterxml.jackson.annotation.JsonIgnoreProperties;
import com.fasterxml.jackson.annotation.JsonProperty;
import com.fasterxml.jackson.core.JsonFactory;
import com.fasterxml.jackson.core.JsonParser;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.google.common.io.CharStreams;
import com.google.common.util.concurrent.RateLimiter;
import org.apache.http.client.methods.CloseableHttpResponse;
import org.apache.http.client.methods.HttpPost;
import org.apache.http.entity.StringEntity;
import org.apache.http.impl.client.CloseableHttpClient;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.io.IOException;
import java.io.InputStreamReader;
import java.net.URL;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.List;

public class RemoteEmbeddingStrategy implements EmbeddingStrategy {
    private static final Logger logger = LoggerFactory.getLogger(RemoteEmbeddingStrategy.class);

    static final int MAX_FILES_PER_BATCH = 1900;
    static final int MAX_TOKENS_PER_BATCH = 210_000;
    static final int MAX_TOKENS_PER_FILE = 8100;
    private static final int TRIM_LINES = 30;
    private static final int MAX_RETRIES = 5;
    static final long RETRY_BASE_MS = 1000;
    static final double DEFAULT_RATE_LIMIT_TOKENS_PER_SEC = 150_000;

    protected long retryBaseMs() { return RETRY_BASE_MS; }

    private static final ObjectMapper objectMapper = new ObjectMapper();

    private final URL endpoint;
    private final String model;
    private final int dims;
    private final String apiKey;
    private final CloseableHttpClient client;
    private final Tokenizer tokenizer;
    private final RateLimiter rateLimiter;

    public RemoteEmbeddingStrategy(URL endpoint, String model, int dims, String apiKey,
            CloseableHttpClient client, Tokenizer tokenizer) {
        this(endpoint, model, dims, apiKey, client, tokenizer, DEFAULT_RATE_LIMIT_TOKENS_PER_SEC);
    }

    RemoteEmbeddingStrategy(URL endpoint, String model, int dims, String apiKey,
            CloseableHttpClient client, Tokenizer tokenizer, double rateLimitTokensPerSec) {
        this.endpoint = endpoint;
        this.model = model;
        this.dims = dims;
        this.apiKey = apiKey;
        this.client = client;
        this.tokenizer = tokenizer;
        this.rateLimiter = RateLimiter.create(rateLimitTokensPerSec);
    }

    @Override
    public String modelName() {
        return model;
    }

    @Override
    public int dimensions() {
        return dims;
    }

    @Override
    public List<FileEmbeddingResult> embed(List<FileToEmbed> files) throws IOException {
        List<FileEmbeddingResult> results = new ArrayList<>();
        List<FileToEmbed> batch = new ArrayList<>();
        int batchTokens = 0;

        for (FileToEmbed file : files) {
            if (file.content == null || file.content.isBlank()) continue;
            FileToEmbed trimmed = trimToTokenLimit(file);
            if (trimmed.content == null || trimmed.content.isBlank()) continue;
            int fileTokens = tokenizer.isAccurate() ? tokenizer.countTokens(trimmed.content) : 0;

            boolean batchFull = batch.size() >= MAX_FILES_PER_BATCH
                    || (tokenizer.isAccurate() && batchTokens + fileTokens > MAX_TOKENS_PER_BATCH);

            if (!batch.isEmpty() && batchFull) {
                results.addAll(flushBatch(batch, batchTokens));
                batch.clear();
                batchTokens = 0;
            }
            batch.add(trimmed);
            batchTokens += fileTokens;
        }

        if (!batch.isEmpty()) {
            results.addAll(flushBatch(batch, batchTokens));
        }
        return results;
    }

    private List<FileEmbeddingResult> flushBatch(List<FileToEmbed> batch, int tokenCount) throws IOException {
        if (tokenizer.isAccurate()) {
            rateLimiter.acquire(Math.max(1, tokenCount));
        }
        return embedBatch(batch);
    }

    /** Drops trailing TRIM_LINES lines until content fits within MAX_TOKENS_PER_FILE, matching server behavior. */
    private FileToEmbed trimToTokenLimit(FileToEmbed file) {
        if (!tokenizer.isAccurate()) return file;
        if (tokenizer.countTokens(file.content) <= MAX_TOKENS_PER_FILE) return file;

        List<String> lines = new ArrayList<>(Arrays.asList(file.content.split("\n", -1)));
        while (!lines.isEmpty() && tokenizer.countTokens(String.join("\n", lines)) > MAX_TOKENS_PER_FILE) {
            int removeCount = Math.min(TRIM_LINES, lines.size());
            lines = lines.subList(0, lines.size() - removeCount);
        }
        return new FileToEmbed(file.fileName, String.join("\n", lines), file.blobSha);
    }

    private List<FileEmbeddingResult> embedBatch(List<FileToEmbed> batch) throws IOException {
        String[] inputs = new String[batch.size()];
        for (int i = 0; i < batch.size(); i++) {
            inputs[i] = batch.get(i).content;
        }

        JSEmbeddingRequest requestBody = new JSEmbeddingRequest();
        requestBody.model = model;
        requestBody.input = inputs;

        String json = objectMapper.writeValueAsString(requestBody);

        JSEmbeddingResponse response;
        try {
            response = executeWithRetry(json);
        } catch (IOException e) {
            // NoopTokenizer can't pre-count; split on 400 too_many_tokens as a last resort
            if (!tokenizer.isAccurate() && batch.size() > 1
                    && e.getMessage() != null && e.getMessage().contains("too_many_tokens")) {
                logger.warn("too_many_tokens for batch of {}; splitting in half", batch.size());
                int mid = batch.size() / 2;
                List<FileEmbeddingResult> combined = new ArrayList<>();
                combined.addAll(embedBatch(batch.subList(0, mid)));
                combined.addAll(embedBatch(batch.subList(mid, batch.size())));
                return combined;
            }
            throw e;
        }

        List<FileEmbeddingResult> results = new ArrayList<>();
        for (JSEmbeddingResponse.EmbeddingData data : response.data) {
            FileToEmbed src = batch.get(data.index);
            float[] normalized = l2Normalize(data.embedding);
            results.add(new FileEmbeddingResult(src.fileName, src.blobSha, normalized));
        }
        return results;
    }

    private JSEmbeddingResponse executeWithRetry(String json) throws IOException {
        IOException lastException = null;
        for (int attempt = 0; attempt <= MAX_RETRIES; attempt++) {
            if (attempt > 0) {
                long delayMs = retryBaseMs() << (attempt - 1);
                logger.warn("Retrying embedding request (attempt {}/{}), waiting {}ms", attempt, MAX_RETRIES, delayMs);
                try {
                    Thread.sleep(delayMs);
                } catch (InterruptedException e) {
                    Thread.currentThread().interrupt();
                    throw new IOException("Interrupted during retry backoff", e);
                }
            }

            HttpPost request = new HttpPost(endpoint.toExternalForm());
            request.setHeader("Content-Type", "application/json");
            request.setHeader("Authorization", "Bearer " + apiKey);
            request.setEntity(new StringEntity(json, StandardCharsets.UTF_8));

            try (CloseableHttpResponse response = client.execute(request)) {
                int code = response.getStatusLine().getStatusCode();
                if (code >= 500 || code == 429) {
                    String body = CharStreams.toString(
                        new InputStreamReader(response.getEntity().getContent(), StandardCharsets.UTF_8));
                    lastException = new IOException(String.format(
                        "Embedding request to %s failed (attempt %d): %s%n%s",
                        endpoint, attempt + 1, response.getStatusLine(), body));
                    continue;
                }
                if (code >= 400) {
                    String body = CharStreams.toString(
                        new InputStreamReader(response.getEntity().getContent(), StandardCharsets.UTF_8));
                    throw new IOException(String.format(
                        "Embedding request to %s failed: %s%n%s", endpoint, response.getStatusLine(), body));
                }
                try (JsonParser parser = new JsonFactory().createParser(response.getEntity().getContent())) {
                    return objectMapper.readValue(parser, JSEmbeddingResponse.class);
                }
            }
        }
        throw new IOException("Embedding request to " + endpoint + " failed after " + MAX_RETRIES + " retries", lastException);
    }

    private static float[] l2Normalize(float[] v) {
        double sumSq = 0;
        for (float x : v) sumSq += (double) x * x;
        if (sumSq == 0) return v;
        float norm = (float) Math.sqrt(sumSq);
        float[] out = new float[v.length];
        for (int i = 0; i < v.length; i++) out[i] = v[i] / norm;
        return out;
    }

    // --- Jackson DTOs ---

    static class JSEmbeddingRequest {
        @JsonProperty public String model;
        @JsonProperty public String[] input;
    }

    @JsonIgnoreProperties(ignoreUnknown = true)
    static class JSEmbeddingResponse {
        @JsonProperty public List<EmbeddingData> data;

        @JsonIgnoreProperties(ignoreUnknown = true)
        static class EmbeddingData {
            @JsonProperty public int index;
            @JsonProperty public float[] embedding;
        }
    }
}
