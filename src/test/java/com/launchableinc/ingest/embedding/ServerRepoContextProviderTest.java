package com.launchableinc.ingest.embedding;

import static com.google.common.truth.Truth.assertThat;
import static org.junit.Assert.assertThrows;
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

import java.io.IOException;
import java.net.InetSocketAddress;
import java.net.URL;
import java.util.Arrays;
import java.util.Collections;
import java.util.List;

@RunWith(JUnit4.class)
public class ServerRepoContextProviderTest {

    @Rule public MockServerRule mockServerRule = new MockServerRule(this);
    private MockServerClient mockServerClient;

    @Test
    public void returnsSummariesFromServer() throws Exception {
        mockServerClient
            .when(request().withMethod("POST").withPath("/collect/summaries"))
            .respond(response()
                .withStatusCode(200)
                .withHeader("Content-Type", "application/json")
                .withBody("{\"repoSummary\":\"A Java repo\",\"dirSummaries\":{\"src\":\"Source files\",\"src/foo\":\"Foo package\"}}"));

        ServerRepoContextProvider provider = buildProvider("/collect/summaries");

        List<FileToEmbed> files = Arrays.asList(
            new FileToEmbed("src/A.java", "class A {}", "sha1"),
            new FileToEmbed("src/foo/B.java", "class B {}", "sha2"));

        Summaries summaries = provider.getSummaries(files);

        assertThat(summaries.repoSummary).isEqualTo("A Java repo");
        assertThat(summaries.dirSummaries).containsEntry("src", "Source files");
        assertThat(summaries.dirSummaries).containsEntry("src/foo", "Foo package");
    }

    @Test
    public void sendsFilePathsInRequestBody() throws Exception {
        mockServerClient
            .when(request()
                .withMethod("POST")
                .withPath("/collect/summaries")
                .withBody(org.mockserver.model.JsonBody.json(
                    "{\"tree\":[{\"path\":\"src/Foo.java\"},{\"path\":\"Bar.java\"}]}")))
            .respond(response()
                .withStatusCode(200)
                .withHeader("Content-Type", "application/json")
                .withBody("{\"repoSummary\":\"\",\"dirSummaries\":{}}"));

        ServerRepoContextProvider provider = buildProvider("/collect/summaries");

        provider.getSummaries(Arrays.asList(
            new FileToEmbed("src/Foo.java", "content", "sha1"),
            new FileToEmbed("Bar.java", "content", "sha2")));
        // If the body didn't match, mockserver would return 404 and the above would throw
    }

    @Test
    public void throwsOnNon2xx() throws Exception {
        mockServerClient
            .when(request().withMethod("POST").withPath("/collect/summaries"))
            .respond(response().withStatusCode(404).withBody("Not found"));

        ServerRepoContextProvider provider = buildProvider("/collect/summaries");

        assertThrows(IOException.class, () ->
            provider.getSummaries(Collections.singletonList(
                new FileToEmbed("A.java", "content", "sha1"))));
    }

    private ServerRepoContextProvider buildProvider(String path) throws Exception {
        InetSocketAddress addr = mockServerClient.remoteAddress();
        URL url = new URL(String.format("http://%s:%d%s", addr.getHostString(), addr.getPort(), path));
        CloseableHttpClient client = HttpClients.createDefault();
        return new ServerRepoContextProvider(url, client);
    }
}
