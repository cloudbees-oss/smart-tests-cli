package com.launchableinc.ingest.embedding;

import com.fasterxml.jackson.annotation.JsonProperty;
import com.fasterxml.jackson.core.JsonFactory;
import com.fasterxml.jackson.core.JsonParser;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.google.common.io.CharStreams;
import org.apache.http.client.methods.CloseableHttpResponse;
import org.apache.http.client.methods.HttpPost;
import org.apache.http.entity.StringEntity;
import org.apache.http.impl.client.CloseableHttpClient;

import java.io.IOException;
import java.io.InputStreamReader;
import java.net.URL;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;

/**
 * Calls POST .../commits/collect/summaries to get server-generated repo and directory summaries.
 * The server returns 404 when augmentation is disabled for the workspace.
 */
public class ServerRepoContextProvider implements RepoContextProvider {
    private static final ObjectMapper objectMapper = new ObjectMapper();

    private final URL summariesUrl;
    private final CloseableHttpClient client;

    public ServerRepoContextProvider(URL summariesUrl, CloseableHttpClient client) {
        this.summariesUrl = summariesUrl;
        this.client = client;
    }

    @Override
    public Summaries getSummaries(List<FileToEmbed> files) throws IOException {
        JSRequest req = new JSRequest();
        req.tree = new ArrayList<>(files.size());
        for (FileToEmbed f : files) {
            JSTreeEntry e = new JSTreeEntry();
            e.path = f.fileName;
            req.tree.add(e);
        }

        HttpPost request = new HttpPost(summariesUrl.toExternalForm());
        request.setHeader("Content-Type", "application/json");
        request.setEntity(new StringEntity(objectMapper.writeValueAsString(req), StandardCharsets.UTF_8));

        try (CloseableHttpResponse response = client.execute(request)) {
            int code = response.getStatusLine().getStatusCode();
            if (code >= 400) {
                String body = CharStreams.toString(
                    new InputStreamReader(response.getEntity().getContent(), StandardCharsets.UTF_8));
                throw new IOException(String.format(
                    "Summaries request failed: %s%n%s", response.getStatusLine(), body));
            }
            try (JsonParser parser = new JsonFactory().createParser(response.getEntity().getContent())) {
                JSResponse resp = objectMapper.readValue(parser, JSResponse.class);
                return new Summaries(resp.repoSummary, resp.dirSummaries);
            }
        }
    }

    static class JSRequest {
        @JsonProperty public List<JSTreeEntry> tree;
    }

    static class JSTreeEntry {
        @JsonProperty public String path;
    }

    static class JSResponse {
        @JsonProperty public String repoSummary;
        @JsonProperty public Map<String, String> dirSummaries;
    }
}
