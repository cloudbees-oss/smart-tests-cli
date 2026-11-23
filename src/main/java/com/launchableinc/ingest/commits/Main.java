package com.launchableinc.ingest.commits;

import com.google.common.annotations.VisibleForTesting;
import com.google.common.base.Strings;
import java.io.File;
import java.io.IOException;
import java.net.MalformedURLException;
import java.net.URL;
import java.util.function.Function;
import java.util.logging.Logger;
import java.util.logging.Level;
import org.eclipse.jgit.api.Git;
import org.eclipse.jgit.lib.Repository;
import org.eclipse.jgit.lib.RepositoryBuilder;
import org.eclipse.jgit.util.FS;
import org.kohsuke.args4j.Argument;
import org.kohsuke.args4j.CmdLineException;
import org.kohsuke.args4j.CmdLineParser;
import org.kohsuke.args4j.Option;

/** Driver for {@link CommitGraphCollector}. */
public class Main {
  @Argument(required = true, metaVar = "NAME", usage = "Uniquely identifies this repository within the workspace", index = 0)
  public String name;

  @Argument(required = true, metaVar = "PATH", usage = "Path to Git repository", index = 1)
  public File repo;

  @Option(name = "-org", usage = "Organization ID")
  public String org;

  @Option(name = "-ws", usage = "Workspace ID")
  public String ws;

  @Option(name = "-endpoint", usage = "Endpoint to send the data to.")
  public URL url = new URL("https://api.mercury.launchableinc.com/intake/");

  @Option(name = "-dry-run", usage = "Instead of actually sending data, print what it would do.")
  public boolean dryRun;

  @Option(name = "-skip-cert-verification", usage = "Bypass SSL certification verification.")
  public boolean skipCertVerification;

  @Option(name = "-commit-message", usage = "Collect commit messages")
  public boolean commitMessage;

  @Option(name = "-files", usage = "Collect files")
  public boolean collectFiles;

  @Option(
      name = "-client-embedding",
      usage = "Enable client-side embedding mode")
  public boolean clientEmbedding;

  // The model details below come from the server's collect/options. They are not secret, so they
  // can be on the command line. The endpoint and the API key are read from the environment.
  @Option(name = "-embedding-provider", usage = "Provider of the embedding model, e.g. OpenAI")
  public String embeddingProvider;

  @Option(name = "-embedding-model-name", usage = "Name of the embedding model, e.g. text-embedding-3-small")
  public String embeddingModelName;

  @Option(name = "-embedding-model-id", usage = "The server's ID of the embedding model")
  public int embeddingModelId;

  @Option(name = "-embedding-dimensions", usage = "Number of entries in each embedding vector")
  public int embeddingDimensions;

  /** Where environment variables come from. Replaced in tests. */
  @VisibleForTesting Function<String, String> getenv = System::getenv;

  @Option(
      name = "-max-days",
      usage = "The maximum number of days to collect commits retroactively.")
  public int maxDays = 30;

  @Option(name = "-audit", usage = "Whether to output the audit log or not")
  public boolean audit;

  @Option(name = "-enable-timeout", usage = "Enable timeout for the HTTP requests")
  public boolean enableTimeout;

  private Authenticator authenticator;

  @VisibleForTesting String launchableToken = null;

  public Main() throws CmdLineException, MalformedURLException {}

  /**
   * Exit status when client-side embedding cannot go on. The Python CLI tells it apart from a
   * failure to read the git repository.
   */
  static final int EXIT_EMBEDDING_FAILED = 3;

  /** Environment variables that carry the customer's LLM endpoint and key. Keep in sync with env_keys.py. */
  static final String EMBEDDING_ENDPOINT_ENV = "SMART_TESTS_EMBEDDING_ENDPOINT";

  static final String EMBEDDING_API_KEY_ENV = "SMART_TESTS_EMBEDDING_API_KEY";

  public static void main(String[] args) throws Exception {
    Main ingester = new Main();
    CmdLineParser parser = new CmdLineParser(ingester);
    try {
      parser.parseArgument(args);
      ingester.run();
    } catch (CmdLineException e) {
      // signals error meant to be gracefully handled
      System.err.println(e.getMessage());
      System.exit(2);
    } catch (EmbeddingRunFailedException e) {
      // also meant to be gracefully handled: the message says what is wrong, a stack trace would not
      System.err.println(e.getMessage());
      System.exit(EXIT_EMBEDDING_FAILED);
    }
  }

  /**
   * @deprecated Here to keep backward compatibility.
   */
  @Deprecated
  @Option(name = "-no-commit-message", usage = "Do not collect commit messages", hidden = true)
  public void setNoCommitMessage(boolean b) {
    commitMessage = !b;
  }

  /** Ensures all the configuration is properly in place. */
  private void parseConfiguration() throws CmdLineException {
    String apiToken = launchableToken;
    if (launchableToken == null) {
      apiToken = System.getenv("SMART_TESTS_TOKEN");
    }
    if (apiToken == null || apiToken.isEmpty()) {
      if (System.getenv("GITHUB_ACTIONS") != null) {
        String o = System.getenv("SMART_TESTS_ORGANIZATION");
        if (org == null && o == null) {
          throw new CmdLineException("SMART_TESTS_ORGANIZATION env variable is not set");
        }

        String w = System.getenv("SMART_TESTS_WORKSPACE");
        if (ws == null && w == null) {
          throw new CmdLineException("SMART_TESTS_WORKSPACE env variable is not set");
        }

        if (org == null) {
          this.org = o;
        }

        if (ws == null) {
          this.ws = w;
        }

        if (!Strings.isNullOrEmpty(System.getenv("SMART_TESTS_GITHUB_OIDC_TOKEN_AUTH"))) {
          // Generic GitHub Actions OIDC: fetch the id-token minted for the Smart Tests audience and
          // present it like any other OIDC token. Intake routes by `iss` to the generic verifier
          // and matches the normalized `repo:OWNER/REPO` subject against trusted_oidc_subjects. The
          // audience is required because the generic path enforces `aud` for GitHub's issuer.
          String audience = System.getenv("SMART_TESTS_OIDC_AUDIENCE");
          if (Strings.isNullOrEmpty(audience)) {
            audience = GitHubIdTokenAuthenticator.DEFAULT_OIDC_AUDIENCE;
          }
          authenticator = new GitHubIdTokenAuthenticator(audience, false);
        } else if (!Strings.isNullOrEmpty(System.getenv("EXPERIMENTAL_GITHUB_OIDC_TOKEN_AUTH"))) {
          // Deprecated legacy GitHub Actions OIDC: Intake matches the `repository` claim against
          // trusted_github_repositories. The legacy path never checks `aud`, so no audience is
          // requested; the legacy header tells Intake to take the legacy branch.
          System.err.println(
              "EXPERIMENTAL_GITHUB_OIDC_TOKEN_AUTH enables the deprecated GitHub Actions OIDC flow."
                  + " Migrate by registering your repository as a Trusted OIDC subject and switching"
                  + " to SMART_TESTS_GITHUB_OIDC_TOKEN_AUTH=1. See "
                  + "https://docs.cloudbees.com/docs/cloudbees-smart-tests/latest/send-data-to-smart-tests/set-up-smart-tests/migration-to-github-oidc-auth");
          authenticator = new GitHubIdTokenAuthenticator(null, true);
        } else {
          authenticator = new GitHubActionsAuthenticator();
        }
        return;
      }

      throw new CmdLineException("SMART_TESTS_TOKEN env variable is not set");
    }

    this.parseLaunchableToken(apiToken);
  }

  @VisibleForTesting
  void run() throws CmdLineException, IOException {
    if (skipCertVerification) {
      SSLBypass.install();
    }
    parseConfiguration();

    URL endpoint = new URL(url, String.format("organizations/%s/workspaces/%s/commits/", org, ws));
    try (Repository db =
        new RepositoryBuilder().setFS(FS.DETECTED).findGitDir(repo).setMustExist(true).build()) {
      Git git = Git.wrap(db);
      CommitGraphCollector cgc = new CommitGraphCollector(name, git.getRepository());
      cgc.setMaxDays(maxDays);
      cgc.setAudit(audit);
      cgc.setDryRun(dryRun);
      cgc.collectCommitMessage(commitMessage);
      cgc.collectFiles(collectFiles);
      cgc.setClientEmbedding(clientEmbedding);
      EmbeddingConfig embeddingConfig = buildEmbeddingConfig();
      BatchEmbedder embedder = buildEmbedder(embeddingConfig);
      cgc.setEmbedding(embeddingConfig, embedder);
      try {
        cgc.transfer(endpoint, authenticator, enableTimeout);
      } catch (IOException e) {
        // A fatal embedding error happens on a worker thread and arrives wrapped as
        // IOException -> ExecutionException -> EmbeddingException, so look down the chain of causes for it.
        EmbeddingRunFailedException runFailed = findCause(e, EmbeddingRunFailedException.class);
        if (runFailed != null) {
          throw runFailed;
        }
        EmbeddingException embeddingFailure = findCause(e, EmbeddingException.class);
        if (embeddingFailure == null) {
          throw e;
        }
        throw embeddingRunFailed(embeddingFailure.getMessage(), e);
      } finally {
        if (embedder != null) {
          embedder.close();
        }
      }
      int numCommits = cgc.getCommitsSent();
      if (clientEmbedding) {
        int numEmbedded = cgc.getEmbeddedFiles();
        int numSkipped = cgc.getSkippedFiles();
        String skipped =
            numSkipped == 0
                ? ""
                : String.format(" (%d %s skipped, will be retried next run)", numSkipped, plural(numSkipped, "file"));
        System.out.printf("Smart Tests transferred %d more %s and uploaded embeddings for %d %s%s from repository %s%n",
            numCommits, plural(numCommits, "commit"),
            numEmbedded, plural(numEmbedded, "file"),
            skipped,
            repo);
      } else {
        int numFiles = cgc.getFilesSent();
        System.out.printf("Smart Tests transferred %d more %s and %d more %s from repository %s%n",
            numCommits, plural(numCommits, "commit"),
            numFiles, plural(numFiles, "file"),
            repo);
      }
    }
  }

  private static EmbeddingRunFailedException embeddingRunFailed(String reason, Throwable cause) {
    return new EmbeddingRunFailedException(
        "Client-side embedding failed: " + reason + "\nFix the problem and run record commit again.", cause);
  }

  private static <T extends Throwable> T findCause(Throwable e, Class<T> type) {
    for (Throwable t = e; t != null; t = t.getCause() == t ? null : t.getCause()) {
      if (type.isInstance(t)) {
        return type.cast(t);
      }
    }
    return null;
  }

  /**
   * Gathers what is needed to embed files with the customer's endpoint.
   *
   * @return null if embedding is not needed
   * @throws EmbeddingRunFailedException if the endpoint or the API key is not set, or the endpoint
   *     cannot be used, for example because it is not a URL. That is found before anything is sent, so no server credits are spent
   */
  private EmbeddingConfig buildEmbeddingConfig() throws EmbeddingRunFailedException {
    if (!collectFiles || !clientEmbedding) {
      return null;
    }
    String embeddingEndpoint = getenv.apply(EMBEDDING_ENDPOINT_ENV);
    String apiKey = getenv.apply(EMBEDDING_API_KEY_ENV);
    if (Strings.isNullOrEmpty(embeddingEndpoint) || Strings.isNullOrEmpty(apiKey)) {
      throw embeddingRunFailed(EMBEDDING_ENDPOINT_ENV + " or " + EMBEDDING_API_KEY_ENV + " is not set in the environment", null);
    }
    String problem = EmbeddingAdapters.endpointProblem(embeddingEndpoint);
    if (problem != null) {
      throw embeddingRunFailed(problem, null);
    }
    if (EmbeddingAdapters.sendsUnencrypted(embeddingEndpoint)) {
      System.err.println(
          "Warning: " + EMBEDDING_ENDPOINT_ENV + " is not an https:// URL, so the API key and the contents of your files"
              + " are sent unencrypted.");
    }
    return new EmbeddingConfig(
        embeddingProvider, embeddingModelName, embeddingDimensions, embeddingModelId, embeddingEndpoint, apiKey);
  }

  /**
   * @return null if there is nothing to embed
   * @throws EmbeddingRunFailedException if the provider or model is not supported
   */
  private BatchEmbedder buildEmbedder(EmbeddingConfig config) throws EmbeddingRunFailedException {
    if (config == null) {
      return null;
    }
    try {
      return BatchEmbedder.create(config);
    } catch (UnsupportedEmbeddingException e) {
      throw embeddingRunFailed(e.getMessage(), e);
    }
  }

  private String plural(int count, String noun) {
    if (count == 1) {
      return noun;
    } else {
      return noun + "s";
    }
  }

  private void parseLaunchableToken(String token) throws CmdLineException {
    if (token.startsWith("v1:")) {
      String[] v = token.split(":");
      if (v.length != 3) {
        throw new IllegalStateException("Malformed SMART_TESTS_TOKEN");
      }
      v = v[1].split("/");
      if (v.length != 2) {
        throw new IllegalStateException("Malformed SMART_TESTS_TOKEN");
      }

      // for backward compatibility, allow command line options to take precedence
      if (org == null) {
        org = v[0];
      }
      if (ws == null) {
        ws = v[1];
      }
    } else {
      // "v0" token doesn't contain org/ws, so they need to be explicitly configured
      if (org == null) {
        throw new CmdLineException("Organization must be specified with the -org option");
      }
      if (ws == null) {
        throw new CmdLineException("Workspace must be specified with the -ws option");
      }
    }

    authenticator = new TokenAuthenticator(token);
  }

  static {
    // JGit uses high logging level for errors that it recovers, and those messages are confusing
    // to users. So let's shut them off
    Logger logger = Logger.getLogger("org.eclipse.jgit");
    logger.setLevel(Level.OFF);
  }
}
