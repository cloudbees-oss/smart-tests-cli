package com.launchableinc.ingest.commits;

import com.fasterxml.jackson.annotation.JsonIgnoreProperties;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.google.common.base.Strings;
import com.google.common.collect.ImmutableList;
import java.io.IOException;
import java.io.UncheckedIOException;
import java.io.UnsupportedEncodingException;
import java.net.URLEncoder;
import java.nio.charset.StandardCharsets;
import org.apache.http.Header;
import org.apache.http.client.methods.CloseableHttpResponse;
import org.apache.http.client.methods.HttpGet;
import org.apache.http.impl.client.CloseableHttpClient;
import org.apache.http.impl.client.HttpClientBuilder;
import org.apache.http.message.BasicHeader;
import org.kohsuke.args4j.CmdLineException;

public class GitHubIdTokenAuthenticator implements Authenticator {
  // Default audience Intake expects in an OIDC id-token (launchableinc.intake.oidc.audience).
  // Mirrors the Python CLI's DEFAULT_OIDC_AUDIENCE.
  static final String DEFAULT_OIDC_AUDIENCE = "https://app.cloudbees.io/smart-tests";
  // Header the CLI sends to opt into Intake's deprecated GitHub Actions OIDC path. Absent it, a
  // GitHub-issued token is verified through the generic OIDC path. Mirrors RESTAuthConverter.
  static final String LEGACY_GITHUB_OIDC_HEADER = "GitHub-OIDC-Legacy";

  private static final ObjectMapper objectMapper = new ObjectMapper();
  private final String idToken;
  private final boolean legacy;

  /**
   * Retrieves a GitHub Actions OIDC id-token via the runner's token endpoint.
   *
   * @param audience When non-empty, requested so the token's {@code aud} claim matches what
   *     Intake's generic OIDC path enforces. Pass {@code null}/empty for the legacy path, which
   *     never checks {@code aud}.
   * @param legacy When true, signals Intake to take the deprecated GitHub Actions OIDC path via the
   *     {@link #LEGACY_GITHUB_OIDC_HEADER} header; without it the token is verified through the
   *     generic path.
   */
  public GitHubIdTokenAuthenticator(String audience, boolean legacy) throws CmdLineException {
    this.legacy = legacy;
    String reqUrl = System.getenv("ACTIONS_ID_TOKEN_REQUEST_URL");
    String rtToken = System.getenv("ACTIONS_ID_TOKEN_REQUEST_TOKEN");
    if (Strings.isNullOrEmpty(reqUrl) || Strings.isNullOrEmpty(rtToken)) {
      throw new CmdLineException(
          "GitHub Actions OIDC tokens cannot be retrieved.Confirm that you have added necessary"
              + " permissions following "
              + "https://docs.github.com/en/actions/deployment/security-hardening-your-deployments/configuring-openid-connect-in-cloud-providers#adding-permissions-settings");
    }

    if (!Strings.isNullOrEmpty(audience)) {
      String sep = reqUrl.contains("?") ? "&" : "?";
      reqUrl = reqUrl + sep + "audience=" + encode(audience);
    }

    HttpGet request = new HttpGet(reqUrl);
    request.setHeader("Authorization", "Bearer " + rtToken);
    request.setHeader("Accept", "applicaiton/json; api-version=2.0");
    request.setHeader("Content-Type", "application/json");

    try (CloseableHttpClient client = HttpClientBuilder.create().useSystemProperties().build()) {
      try (CloseableHttpResponse resp = client.execute(request)) {
        if (resp.getStatusLine().getStatusCode() != 200) {
          throw new IOException(
              String.format("Failed to retrieve IdToken: %s", resp.getStatusLine()));
        }
        this.idToken =
            objectMapper.readValue(resp.getEntity().getContent(), IdTokenResponse.class).value;
      }
    } catch (IOException e) {
      throw new UncheckedIOException(e);
    }
  }

  @Override
  public ImmutableList<Header> getAuthenticationHeaders() {
    ImmutableList.Builder<Header> headers = ImmutableList.builder();
    headers.add(new BasicHeader("Authorization", "Bearer " + idToken));
    if (legacy) {
      headers.add(new BasicHeader(LEGACY_GITHUB_OIDC_HEADER, "1"));
    }
    return headers.build();
  }

  private static String encode(String value) {
    try {
      return URLEncoder.encode(value, StandardCharsets.UTF_8.name());
    } catch (UnsupportedEncodingException e) {
      // UTF-8 is always supported.
      throw new AssertionError(e);
    }
  }

  @JsonIgnoreProperties(ignoreUnknown = true)
  public static class IdTokenResponse {
    public String value;
  }
}
