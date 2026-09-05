package com.launchableinc.ingest.commits;

import com.google.common.io.CharStreams;
import org.apache.http.client.methods.CloseableHttpResponse;
import org.apache.http.client.methods.HttpGet;
import org.apache.http.client.methods.HttpPost;
import org.apache.http.impl.client.CloseableHttpClient;

import java.io.Closeable;
import java.io.IOException;
import java.io.InputStreamReader;
import java.net.MalformedURLException;
import java.net.URL;
import java.nio.charset.StandardCharsets;

import static java.nio.charset.StandardCharsets.UTF_8;

/**
 * Wrapper around Apache HTTP client for our idiomatic use.
 *
 * <p>The way {@link CommitGraphCollector} uses HTTP client is highly idiomatic, for example
 * to raise an exception for every 4xx/5xx response. We'll wrap those idioms in this class
 * to keep {@link CommitGraphCollector} DRY and apply consistent behavior.
 */
public final class LaunchableHttpClient implements Closeable {
  final CloseableHttpClient core;

  public LaunchableHttpClient(CloseableHttpClient core) {
    this.core = core;
  }

  @Override
  public void close() throws IOException {
    core.close();
  }

  /**
   * GET with error handling.
   */
  public CloseableHttpResponse httpGet(URL url) throws IOException {
    return handleError(url, core.execute(new HttpGet(url.toExternalForm())));
  }

  /**
   * POST with error handling.
   */
  public CloseableHttpResponse httpPost(HttpPost request) throws IOException {
    return handleError(request.getURI().toURL(), core.execute(request));
  }

  /** Pass through {@link CloseableHttpResponse} but checks and throws an error. */
  private CloseableHttpResponse handleError(URL url, CloseableHttpResponse response)
    throws IOException {
    int code = response.getStatusLine().getStatusCode();
    if (code >= 400) {
      throw new IOException(
        String.format(
          "Failed to retrieve from %s: %s%n%s",
          url,
          response.getStatusLine(),
          CharStreams.toString(
            new InputStreamReader(
              response.getEntity().getContent(), UTF_8))));
    }
    return response;
  }
}
