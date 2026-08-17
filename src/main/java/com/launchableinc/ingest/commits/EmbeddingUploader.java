package com.launchableinc.ingest.commits;

import com.fasterxml.jackson.annotation.JsonProperty;
import com.fasterxml.jackson.core.JsonFactory;
import com.fasterxml.jackson.core.JsonParser;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.launchableinc.ingest.embedding.FileEmbeddingResult;
import org.apache.http.client.methods.CloseableHttpResponse;
import org.apache.http.client.methods.HttpPost;
import org.apache.http.entity.StringEntity;

import java.io.IOException;
import java.net.URL;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.List;

/**
 * Uploads a batch of file embeddings to the server and polls until the async work completes.
 *
 * POST  .../collect/embeddings  → { "workId": N }
 * GET   .../collect/files/work/{workId}  (existing poll endpoint, shared with TAR upload)
 */
class EmbeddingUploader {
    private static final int POLL_INTERVAL_MS = 3000;
    private static final ObjectMapper objectMapper = new ObjectMapper();

    void upload(URL service, LaunchableHttpClient client,
                List<FileEmbeddingResult> results,
                String model, int dimensions) throws IOException {
        URL url = new URL(service, "collect/embeddings");

        JSEmbeddingCollectionRequest req = new JSEmbeddingCollectionRequest();
        req.model = model;
        req.dimensions = dimensions;
        req.files = new ArrayList<>(results.size());
        for (FileEmbeddingResult r : results) {
            JSFileEmbedding fe = new JSFileEmbedding();
            fe.fileName = r.fileName;
            fe.blobSha = r.blobSha;
            fe.embedding = r.embedding;
            req.files.add(fe);
        }

        HttpPost request = new HttpPost(url.toExternalForm());
        request.setHeader("Content-Type", "application/json");
        request.setHeader("Accept", "application/json; mode=async");
        request.setEntity(new StringEntity(objectMapper.writeValueAsString(req), StandardCharsets.UTF_8));

        int workId = readResponse(client.httpPost(request), JSAsyncFileCollectionResponse.class).workId;
        URL workUrl = new URL(service, "collect/files/work/" + workId);

        while (true) {
            try {
                Thread.sleep(POLL_INTERVAL_MS);
            } catch (InterruptedException e) {
                throw new IOException("Interrupted while waiting for embedding upload", e);
            }
            JSAsyncFileCollectionProgress status =
                    readResponse(client.httpGet(workUrl), JSAsyncFileCollectionProgress.class);
            switch (status.status) {
                case IN_PROGRESS:
                    break;
                case SUCCEEDED:
                    return;
                case FAILED:
                case ABANDONED:
                    throw new IOException("Embedding upload (workId=" + workId + ") failed: " + status.status);
            }
        }
    }

    private <T> T readResponse(CloseableHttpResponse response, Class<T> type) throws IOException {
        try (JsonParser parser = new JsonFactory().createParser(response.getEntity().getContent())) {
            return objectMapper.readValue(parser, type);
        } finally {
            response.close();
        }
    }

    static class JSEmbeddingCollectionRequest {
        @JsonProperty public String model;
        @JsonProperty public int dimensions;
        @JsonProperty public List<JSFileEmbedding> files;
    }

    static class JSFileEmbedding {
        @JsonProperty public String fileName;
        @JsonProperty public String blobSha;
        @JsonProperty public float[] embedding;
    }
}
