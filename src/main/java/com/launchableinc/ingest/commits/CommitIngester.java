package com.launchableinc.ingest.commits;

import com.google.common.annotations.VisibleForTesting;
import java.io.File;
import java.io.IOException;
import java.net.MalformedURLException;
import java.net.URL;
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
public class CommitIngester {
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
      name = "-max-days",
      usage = "The maximum number of days to collect commits retroactively.")
  public int maxDays = 30;

  @Option(name = "-audit", usage = "Whether to output the audit log or not")
  public boolean audit;

  @Option(name = "-enable-timeout", usage = "Enable timeout for the HTTP requests")
  public boolean enableTimeout;

  private Authenticator authenticator;

  @VisibleForTesting String launchableToken = null;

  public CommitIngester() throws CmdLineException, MalformedURLException {}

  public static void main(String[] args) throws Exception {
    CommitIngester ingester = new CommitIngester();
    CmdLineParser parser = new CmdLineParser(ingester);
    try {
      parser.parseArgument(args);
      ingester.run();
    } catch (CmdLineException e) {
      // signals error meant to be gracefully handled
      System.err.println(e.getMessage());
      System.exit(2);
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

        if (System.getenv("EXPERIMENTAL_GITHUB_OIDC_TOKEN_AUTH") != null) {
          authenticator = new GitHubIdTokenAuthenticator();
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
      cgc.transfer(endpoint, authenticator, enableTimeout);
      int numCommits = cgc.getCommitsSent();
      int numFiles = cgc.getFilesSent();
      System.out.printf("Launchable transferred %d more %s and %d more %s from repository %s%n",
          numCommits, plural(numCommits, "commit"),
          numFiles, plural(numFiles, "file"),
          repo);
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
