package com.launchableinc.ingest.commits;

import com.fasterxml.jackson.core.JsonFactory;
import com.fasterxml.jackson.core.JsonGenerator;
import com.fasterxml.jackson.core.JsonParser;
import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ObjectNode;
import com.google.common.collect.ImmutableList;
import com.google.common.io.CharStreams;
import com.google.common.util.concurrent.MoreExecutors;
import org.apache.commons.compress.archivers.tar.TarArchiveEntry;
import org.apache.commons.compress.archivers.tar.TarArchiveInputStream;
import org.apache.http.Header;
import org.apache.http.HttpResponse;
import org.apache.http.client.config.RequestConfig;
import org.apache.http.client.methods.CloseableHttpResponse;
import org.apache.http.client.methods.HttpGet;
import org.apache.http.client.methods.HttpPost;
import org.apache.http.entity.ContentProducer;
import org.apache.http.entity.EntityTemplate;
import org.apache.http.impl.client.CloseableHttpClient;
import org.apache.http.impl.client.HttpClientBuilder;
import org.eclipse.jgit.diff.DiffAlgorithm.SupportedAlgorithm;
import org.eclipse.jgit.diff.DiffEntry;
import org.eclipse.jgit.errors.ConfigInvalidException;
import org.eclipse.jgit.errors.InvalidObjectIdException;
import org.eclipse.jgit.errors.MissingObjectException;
import org.eclipse.jgit.lib.ConfigConstants;
import org.eclipse.jgit.lib.FileMode;
import org.eclipse.jgit.lib.ObjectId;
import org.eclipse.jgit.lib.ObjectReader;
import org.eclipse.jgit.lib.PersonIdent;
import org.eclipse.jgit.lib.Repository;
import org.eclipse.jgit.revwalk.RevCommit;
import org.eclipse.jgit.revwalk.RevSort;
import org.eclipse.jgit.revwalk.RevWalk;
import org.eclipse.jgit.revwalk.filter.CommitTimeRevFilter;
import org.eclipse.jgit.revwalk.filter.OrRevFilter;
import org.eclipse.jgit.submodule.SubmoduleWalk;
import org.eclipse.jgit.treewalk.TreeWalk;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.io.ByteArrayInputStream;
import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.io.InputStreamReader;
import java.io.OutputStream;
import java.io.UncheckedIOException;
import java.net.URL;
import java.nio.charset.StandardCharsets;
import java.time.Duration;
import java.util.ArrayList;
import java.util.Collection;
import java.util.Collections;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.Objects;
import java.util.Set;
import java.util.Vector;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Future;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.function.Consumer;
import java.util.function.Supplier;
import java.util.zip.GZIPOutputStream;

import static com.google.common.collect.ImmutableList.*;
import static java.util.Arrays.*;

/**
 * Compares what commits the local repository and the remote repository have, then send delta over.
 */
public class CommitGraphCollector {
  private static final Logger logger = LoggerFactory.getLogger(CommitGraphCollector.class);
  static final ObjectMapper objectMapper = new ObjectMapper();
  private static final int HTTP_TIMEOUT_MILLISECONDS = 15_000;
  /**
   * Repository header is sent using this reserved file name
   */
  static final String HEADER_FILE = ".launchable";

  private final String rootName;

  /**
   * Root repository to start processing.
   *
   * <p>Sub modules form a tree structure rooted at this repository.
   */
  private final Repository root;

  private AtomicInteger commitsSent = new AtomicInteger(), filesSent = new AtomicInteger();

  private boolean collectCommitMessage, collectFiles;

  private int maxDays;

  private boolean reportAllFiles;

  private boolean audit;

  private boolean dryRun;

  private boolean warnMissingObject;

  private String dryRunPrefix() {
    if (!dryRun) {
      return "";
    }
    return "(DRY RUN) ";
  }

  private boolean outputAuditLog() {
    return audit || dryRun;
  }

  public CommitGraphCollector(String name, Repository git) {
    this.rootName = name;
    this.root = git;
  }

  /** How many commits did we transfer? */
  public int getCommitsSent() {
    return commitsSent.get();
  }

  public int getFilesSent() {
    return filesSent.get();
  }

  private String dumpHeaderAsJson(Header[] headers) throws JsonProcessingException {
    ObjectNode header = objectMapper.createObjectNode();
    for (Header h : headers) {
      header.put(h.getName(), h.getValue());
    }
    return objectMapper.writeValueAsString(header);
  }

  /** Transfers the commits to the remote endpoint. */
  public void transfer(URL service, Authenticator authenticator, boolean enableTimeout) throws IOException {
    URL latestUrl;
    HttpClientBuilder builder =
            HttpClientBuilder.create()
                    .useSystemProperties()
                    .setDefaultHeaders(authenticator.getAuthenticationHeaders());
    if (enableTimeout) {
      RequestConfig config = RequestConfig.custom()
              .setConnectTimeout(HTTP_TIMEOUT_MILLISECONDS)
              .setConnectionRequestTimeout(HTTP_TIMEOUT_MILLISECONDS)
              .setSocketTimeout(HTTP_TIMEOUT_MILLISECONDS).build();
      builder.setDefaultRequestConfig(config);
    }
    try (CloseableHttpClient client = builder.build()) {
      latestUrl = new URL(service, "latest");
      if (outputAuditLog()) {
        System.err.printf(
            "AUDIT:launchable:%ssend request method:get path: %s%n", dryRunPrefix(), latestUrl);
      }
      CloseableHttpResponse latestResponse = client.execute(new HttpGet(latestUrl.toExternalForm()));
      ImmutableList<ObjectId> advertised = getAdvertisedRefs(handleError(latestUrl, latestResponse));
      honorControlHeaders(latestResponse);

      // every time a new stream is needed, supply ByteArrayOutputStream, and when the data is all
      // written, turn around and ship that over
      transfer(
        advertised,
        (ContentProducer commits) -> sendCommits(service, client, commits),
        new TreeReceiverImpl(service, client),
        (ContentProducer files) -> sendFiles(service, client, files),
        256);
    }
  }

  private void sendCommits(URL service, CloseableHttpClient client, ContentProducer commits) throws IOException {
    URL url = new URL(service, "collect");
    HttpPost request = new HttpPost(url.toExternalForm());
    request.setHeader("Content-Type", "application/json");
    request.setHeader("Content-Encoding", "gzip");
    request.setEntity(new EntityTemplate(os -> commits.writeTo(new GZIPOutputStream(os))));

    if (outputAuditLog()) {
      System.err.printf(
          "AUDIT:launchable:%ssend request method:post path:%s headers:%s"
              + " args:",
          dryRunPrefix(), url, dumpHeaderAsJson(request.getAllHeaders()));
      commits.writeTo(System.err);
      System.err.println();
    }
    if (dryRun) {
      return;
    }
    handleError(url, client.execute(request)).close();
  }

  private void sendFiles(URL service, CloseableHttpClient client, ContentProducer files) throws IOException {
    URL url = new URL(service, "collect/files");
    HttpPost request = new HttpPost(url.toExternalForm());
    request.setHeader("Content-Type", "application/octet-stream");
    // no content encoding, since .tar.gz is considered content
    request.setEntity(new EntityTemplate(os -> files.writeTo(new GZIPOutputStream(os))));

    if (outputAuditLog()) {
      System.err.printf(
          "AUDIT:launchable:%ssend request method:post path:%s headers:%s args:",
          dryRunPrefix(), url, dumpHeaderAsJson(request.getAllHeaders()));

      // TODO: inefficient to buffer everything in memory just to read it back
      ByteArrayOutputStream baos = new ByteArrayOutputStream();
      files.writeTo(baos);
      TarArchiveInputStream tar =
          new TarArchiveInputStream(
              new ByteArrayInputStream(baos.toByteArray()),
              "UTF-8");
      TarArchiveEntry entry;
      boolean first = true;
      while ((entry = tar.getNextTarEntry()) != null) {
        System.err.printf(entry.getName());
        if (first) {
          first = false;
        } else {
          System.err.print(", ");
        }
      }
      System.err.println();
    }
    if (dryRun) {
      return;
    }
    handleError(url, client.execute(request)).close();
  }

  private void honorControlHeaders(HttpResponse response) {
    // When a user incorrectly configures shallow clone, the incremental nature of commit collection
    // makes it really hard for us and users to collaboratively reset and repopulate the commit data.
    // This server-side override mechanism makes it easier.
    Header h = response.getFirstHeader("X-Max-Days");
    if (h!=null) {
      maxDays = Integer.parseInt(h.getValue());
    }
    // File transfer is supposed to work incrementally, but we are investigating the problem where
    // not all files get collected prior to commit collection, resulting in incomplete data on the server side.
    // As a temporary mitigation, allow the server to request all files to be reported.
    h = response.getFirstHeader("X-Report-All-Files");
    if (h!=null) {
      reportAllFiles = true;
    }
  }

  private ImmutableList<ObjectId> getAdvertisedRefs(HttpResponse response) throws IOException {
    JsonParser parser = new JsonFactory().createParser(response.getEntity().getContent());
    String[] ids = objectMapper.readValue(parser, String[].class);
    return stream(ids)
        .map(
            s -> {
              try {
                return ObjectId.fromString(s);
              } catch (InvalidObjectIdException e) {
                // if the server sends us a bogus data, don't penalize users, silently drop that
                return null;
              }
            })
        .filter(Objects::nonNull)
        .collect(toImmutableList());
  }

  /**
   * Writes delta between local commits to the advertised to JSON stream.
   *
   * @param commitSender Commits are written to streams provided by this {@link Supplier}, in the given
   *     chunk size.
   * @param treeReceiver Receives file names (aka 'tree' in Git speak) that the CLI thinks the server needs,
   *                     and respond with those that the server actually needs.
   * @param fileSender   Receives the actual contents of the files that the server needs.
   */
  public void transfer(
    Collection<ObjectId> advertised, IOConsumer<ContentProducer> commitSender, TreeReceiver treeReceiver, IOConsumer<ContentProducer> fileSender, int chunkSize)
      throws IOException {
    ByRepository r = new ByRepository(root, rootName);
    /*
      Parallelization

        TreeReceiver is blocking, so the big block in transfer should run in parallel
        - That gets CommitChunkStreamer and FileChunkStreamer invoked concurrently.
        - caller wants to wait for the response to FileChunkStreamer then collect commits,
          so this should be designed nicely
        - commit collection is very fast, so maybe we just need to do this after the whole join

        - otherwise, we create a file queue and let threads wait for completion of their portions, which is complicated

        we also need one CLI invocation to handle all repositories.

        - header needs to be sent out per chunk. that suggests one stream per repo.

        Maybe better to just focus on how to do decent progress reporting
        [task #1: 10/35] [task #2: 5/20] ...

        Or maybe we can maintain the current "whoever came at the right time to report" scheme
        by maintaining the running sum + current workload. AtomicInteger can keep track.

        Summary:
        fork/join, so that tasks can be forked
        the work is happening one thread, one repo. file transfer is buffered and flipped for counting
        file sender to be invoked concurrently
        two sets of AtomcInteger counters to maintain files to transfer + files transferred
        thread local chunk streamers

        CommitChunkStreamer - we'll create one per thread.
          or maybe not. The point of this is to batch things up, so it benefits from seeing
          data from multiple threads. flushing is a problem, because it's synchronous. remove flushing.
          buffer together, then at a batch, fork
          -> that breaks the parent commit first guarantee from this perspective, best to keep one repository, one thread,
             just do those in parallel. This bites us back if we have tons of repo each small. To solve this,
             every thread maintains its own pool, flushing if it gets too big, but consolidate the remaining work to
             the global queue. But that seems too much.

          -> let's just one have synchronized instance with one queue, where the act of writing
             blocks all produceers. simplest way to guarantee ordering. IOW no concurrent write, which
             is sufficient for now, since this is not the real bottleneck.
        FileChunkStreamer - one per thread, in order to deal with header. create header per chunk
        ProgressReportingConsumer - one per thread, but update common AtomicIntegers for counting,
          then steal worker to report.

        submodule walk is fast enough, we can afford to do it twice

        for each 'r' in parallel {
          collect files
        }
        for each 'r' in parallel {
          collect commits
        }

        mixing serial and parallel complicates the close op, so let's just do it in parallel, and have
        CommitChunkStreamer serialize the whole thing back down to one.

        ----
        take 2

        for each 'r' in parallel:
          recursively find submodules, use ExecutorService to submit tasks for each of them, closing repos at the end
          but this makes `close` complicated

     */

//    ExecutorService es = Executors.newFixedThreadPool(4);
    // for debugging
    ExecutorService es = MoreExecutors.newDirectExecutorService();

    ProgressReporter<VirtualFile> pr = new ProgressReporter<>(VirtualFile::path, Duration.ofSeconds(3));
    try {
      if (collectFiles) {
        // record all the necessary BLOBs first, before attempting to record its commit.
        // this way, if the file collection fails, the server won't see this commit, so the future
        // "record commit" invocation will retry the file collection, thereby making the behavior idempotent.
        r.forEachSubModule(es, br -> {
          // TODO: file transfer can be parallelized more aggressively, where we send chunks in parallel
          try (FileChunkStreamer fs = new FileChunkStreamer(fileSender, chunkSize);
               ProgressReporter<VirtualFile>.Consumer fsr = pr.newConsumer(fs)) {
            br.collectFiles(advertised, treeReceiver, fsr);
          }
        });
      }
      r.forEachSubModule(es, br -> {
        // we need to send commits in the topological order, so any parallelization within a repository
        // is probably not worth the effort.
        // TODO: If we process a repository and that doesn't create enough commits
        // to form a full chunk, then it makes sense to concatenate them with other commits from other repositories.
        // Even when # of repos is large, incremental transfer typically only produces a small amount of commits
        // per repo, so this will considerably reduce the connection setup / tear down overhead.
        try (CommitChunkStreamer cs = new CommitChunkStreamer(commitSender, chunkSize)) {
          br.collectCommits(advertised, cs);
        }
      });
    } finally {
      es.shutdown();
    }
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
                      response.getEntity().getContent(), StandardCharsets.UTF_8))));
    }
    return response;
  }

  public void collectCommitMessage(boolean commitMessage) {
    this.collectCommitMessage = commitMessage;
  }

  public void setMaxDays(int days) {
    this.maxDays = days;
  }

  public void setAudit(boolean audit) {
    this.audit = audit;
  }

  public void setDryRun(boolean dryRun) {
    this.dryRun = dryRun;
  }

  public void collectFiles(boolean collectFiles) {
    this.collectFiles = collectFiles;
  }

  /** Process commits per repository. */
  final class ByRepository implements AutoCloseable {
    /** Names that uniquely identifies this Git repository among other Git repositories collected for the workspace. */
    private final String name;
    private final Repository git;

    private final ObjectReader objectReader;
    private final Set<ObjectId> shallowCommits;

    ByRepository(Repository git, String name) throws IOException {
      this.name = name;
      this.git = git;
      this.objectReader = git.newObjectReader();
      this.shallowCommits = objectReader.getShallowCommits();
    }

    void forEachSubModule(ExecutorService threadPool, IOConsumer<ByRepository> consumer) throws IOException {
      for (Future<?> f : forEachSubModuleAsync(threadPool, consumer)) {
        try {
          f.get();
        } catch (Exception e) {
          throw new IOException("Failed to process a repository", e);
        }
      }
    }

    /**
     * Recursively iterate all the sub-modules and apply the given consumer to them asynchronously, using the given
     * thread pool.
     *
     * <p>
     * The way this function mixes (1) synchronous call to consumer with {@code this}, (2) use thread pool to recursively
     * process submodules might be a bit hard to follow. This was motivated by the fact that {@link ByRepository} for
     * sub-modules need to be closed, while {@code this} shouldn't be closed.
     *
     * @return all the async jobs that are forked off, to allow the caller to wait for their completion.
     */
    Collection<Future<?>> forEachSubModuleAsync(ExecutorService threadPool, IOConsumer<ByRepository> consumer) throws IOException {
      Vector<Future<?>> jobs = new Vector<>();
      /*
         Git submodule support
         =====================

         In a fully general version of the problem, every commit we are walking might point to
         different sub-module at different commit, so we should be walking over all of those.
         That will require us to resolve sub-modules, since there's no guarantee that those submodules
         are cloned and available.

         Here, we solve a weaker version of this, that works well enough for `launchable build record`
         and obtain commits needed to determine the subject.

         That is, find submodules that are available in the working tree (thus `!isBare()`), and
         collect all the commits from those repositories.
      */
      if (!git.isBare()) {
        try (SubmoduleWalk swalk = SubmoduleWalk.forIndex(git)) {
          while (swalk.next()) {
            Repository subRepo = swalk.getRepository();
            if (subRepo != null) {
              try {
                ByRepository br = new ByRepository(subRepo, name + "/" + swalk.getModulesPath());
                jobs.add(threadPool.submit(() -> {
                  try {
                    jobs.addAll(br.forEachSubModuleAsync(threadPool, consumer));
                    return null;
                  } finally {
                    br.close();
                    subRepo.close();
                  }
                }));
              } catch (ConfigInvalidException e) {
                throw new IOException("Invalid Git submodule configuration: " + git.getDirectory(), e);
              }
            }
          }
        }
      }

      consumer.accept(this);

      return jobs;
    }

    private void parseEachCommit(RevWalk walk, Collection<ObjectId> advertised, IOConsumer<RevCommit> consumer) throws IOException {
      for (ObjectId id : advertised) {
        try {
          RevCommit c = walk.parseCommit(id);
          consumer.accept(c);
        } catch (MissingObjectException e) {
          // it's possible that the server advertises a commit we don't have.
          //
          // TODO: how does git-push handles the case when the client doesn't recognize commits?
          // Unless it tries to negotiate further what commits they have in common,
          // git-upload-pack can end up creating a big pack with lots of redundant objects
          //
          // think about a case when a client is pushing a new branch against
          // the master branch that moved on the server.
        }
      }
    }

    /**
     * Records all the necessary BLOBs first
     */
    void collectFiles(Collection<ObjectId> advertised, TreeReceiver treeReceiver, FlushableConsumer<VirtualFile> fileReceiver) throws IOException {
      try (TreeWalk treeWalk = new TreeWalk(git)) {
        ObjectId headId = git.resolve("HEAD");
        RevCommit start = git.parseCommit(headId);
        treeWalk.addTree(start.getTree());

        if (!reportAllFiles) {
          // to optimize data transfer, skip files that the server has already seen
          // i.e., files that are present in any of the advertised commits
          // if the reportAllFiles flag is on, then skip this optimization on the client side.
          // treeReceiver will still provide an opportunity for the server to be selective.
          try (RevWalk walk = new RevWalk(git)) {
            parseEachCommit(walk, advertised, c -> treeWalk.addTree(c.getTree()));
          }
        }


        int c = treeWalk.getTreeCount();

        OUTER:
        while (treeWalk.next()) {
          ObjectId head = treeWalk.getObjectId(0);
          for (int i = 1; i < c; i++) {
            if (head.equals(treeWalk.getObjectId(i))) {
              // file at the head is identical to one of the uninteresting commits,
              // meaning we have already seen this file/directory on the server.
              // if it is a dir, there's no need to visit this whole subtree, so skip over
              continue OUTER;
            }
          }

          if (treeWalk.isSubtree()) {
            treeWalk.enterSubtree();
          } else {
            if ((treeWalk.getFileMode(0).getBits() & FileMode.TYPE_MASK) == FileMode.TYPE_FILE) {
              GitFile f = new GitFile(name, treeWalk.getPathString(), head, objectReader);
              // to avoid excessive data transfer, skip files that are too big
              if (f.size() < 1024 * 1024 && f.isText() && !f.path.equals(HEADER_FILE)) {
                treeReceiver.accept(f);
              }
            }
          }
        }

        // Now let the server select the files it actually wants to see
        List<VirtualFile> files = new ArrayList<>(treeReceiver.response());

        // Note(Konboi): To balance the order, since words like "test" and "spec" tend to appear
        // toward the end in alphabetical sorting.
        if (!files.isEmpty()) {
          fileReceiver.accept(buildHeader(start));
          filesSent.incrementAndGet();

          Collections.shuffle(files);
          for (VirtualFile f : files) {
            fileReceiver.accept(f);
            filesSent.incrementAndGet();
          }
        }

        fileReceiver.flush();
      }
    }

    /**
     * Creates a per repository "header" file as a {@link VirtualFile}.
     * Currently, this is just the list of files in the repository.
     */
    private VirtualFile buildHeader(RevCommit start) throws IOException {
      ByteArrayOutputStream os = new ByteArrayOutputStream();
      try (JsonGenerator w = new JsonFactory().createGenerator(os)) {
        w.setCodec(objectMapper);
        w.writeStartObject();
        w.writeArrayFieldStart("tree");

        try (TreeWalk tw = new TreeWalk(git)) {
          tw.addTree(start.getTree());
          tw.setRecursive(true);

          while (tw.next()) {
            w.writeStartObject();
            w.writeStringField("path", tw.getPathString());
            w.writeEndObject();
          }
        }

        w.writeEndArray();
        w.writeEndObject();
      }
      return VirtualFile.from(name, HEADER_FILE, ObjectId.zeroId(), os.toByteArray());
    }

    void collectCommits(Collection<ObjectId> advertised, Consumer<JSCommit> commitReceiver) throws IOException {
      try (RevWalk walk = new RevWalk(git)) {
        // walk reverse topological order, so that older commits get added to the server earlier.
        // This way, the connectivity of the commit graph will be always maintained
        walk.sort(RevSort.TOPO);
        walk.sort(RevSort.REVERSE, true);
        // also combine this with commit time based ordering, so that we can stop walking when we
        // find old enough commits AFAICT, this is no-op in JGit and it always sorts things in
        // commit time order, but it is in the contract, so I'm assuming we shouldn't rely on the
        // implementation optimization that's currently enabling this all the time
        walk.sort(RevSort.COMMIT_TIME_DESC, true);

        ObjectId headId = git.resolve("HEAD");
        walk.markStart(walk.parseCommit(headId));

        // don't walk commits too far back.
        // for our purpose of computing CUT, these are unlikely to contribute meaningfully
        // and it drastically cuts down the initial commit consumption of a new large repository.
        // ... except we do want to capture the head commit, as that makes it easier to spot integration problems
        // when `record build` and `record commit` are separated.

        // two RevFilters are order sensitive. This is because CommitTimeRevFilter.after doesn't return false to
        // filter things out, it throws StopWalkException to terminate the walk, never giving a chance for the other
        // branch of OR to be evaluated. So we need to put ObjectRevFilter first.
        walk.setRevFilter(
            OrRevFilter.create(
              new ObjectRevFilter(headId),
              CommitTimeRevFilter.after(System.currentTimeMillis() - TimeUnit.DAYS.toMillis(maxDays))));

        parseEachCommit(walk, advertised, walk::markUninteresting);

        // walk the commits, transform them, and send them to the commitReceiver
        for (RevCommit c : walk) {
          commitReceiver.accept(transform(c));
          commitsSent.incrementAndGet();
        }
      }
    }

    private JSCommit transform(RevCommit r) throws IOException {
      JSCommit c = new JSCommit();
      c.setCommitHash(r.name());
      c.setMessage(collectCommitMessage ? r.getFullMessage() : "");

      PersonIdent author = r.getAuthorIdent();
      c.setAuthorEmailAddress(JSCommit.hashEmail(author.getEmailAddress()));
      c.setAuthorWhen(author.getWhen().getTime());
      c.setAuthorTimezoneOffset(author.getTimeZoneOffset());

      PersonIdent committer = r.getCommitterIdent();
      c.setCommitterEmailAddress(JSCommit.hashEmail(committer.getEmailAddress()));
      c.setCommitterWhen(committer.getWhen().getTime());
      c.setCommitterTimezoneOffset(committer.getTimeZoneOffset());

      // Change the on-memory config for the diff algorithm.
      // CGit supports patience diff while JGit doesn't. Since the FileBasedRepository reads the
      // user's .gitconfig, if a user sets this
      // algorithm, JGit causes a failure. Changing this on-memory avoids this.
      git.getConfig()
          .setEnum(
              ConfigConstants.CONFIG_DIFF_SECTION,
              null,
              ConfigConstants.CONFIG_KEY_ALGORITHM,
              SupportedAlgorithm.HISTOGRAM);


      if (shallowCommits.contains(r)) {
        c.setShallow(true);
        warnMissingObject();
      }

      for (RevCommit p : r.getParents()) {
        CountingDiffFormatter diff = new CountingDiffFormatter(git);
        List<DiffEntry> files = diff.scan(p.getTree(), r.getTree());
        List<JSFileChange> changes = new ArrayList<>();
        for (DiffEntry de : files) {
          try {
            changes.add(diff.process(de));
          } catch (MissingObjectException e) {
            // in a partially cloned repository, BLOBs might be unavailable and that'd result in MissingObjectException
            System.err.printf("Warning: %s is missing. Skipping diff calculation for %s -> %s%n",
                e.getObjectId().abbreviate(7).name(),
                p.abbreviate(7).name(),
                r.abbreviate(7).name()
            );
            warnMissingObject();
          } catch (IOException e) {
            logger.warn("Failed to process a change to a file", e);
          }
        }
        c.getParentHashes().put(p.name(), changes);
      }

      return c;
    }

    private void warnMissingObject() {
      if (!warnMissingObject) {
        warnMissingObject = true;
        System.err.println("See https://www.launchableinc.com/missing-git-object-during-commit-collection");
      }
    }

    @Override
    public void close() {
      objectReader.close();
    }
  }

  private class TreeReceiverImpl implements TreeReceiver {
    private final List<VirtualFile> files = new ArrayList<>();
    private final URL service;
    private final CloseableHttpClient client;

    public TreeReceiverImpl(URL service, CloseableHttpClient client) {
      this.service = service;
      this.client = client;
    }

    private void writeJsonTo(OutputStream os) throws IOException {
      try (JsonGenerator w = new JsonFactory().createGenerator(os)) {
        w.setCodec(objectMapper);
        w.writeStartObject();
        w.writeArrayFieldStart("tree");

        for (VirtualFile commit : files) {
          w.writeStartObject();
          w.writeFieldName("path");
          w.writeString(commit.path());
          w.writeFieldName("blob");
          w.writeString(commit.blob().name());
          w.writeEndObject();
        }

        w.writeEndArray();
        w.writeEndObject();
      }
    }

    @Override
    public Collection<VirtualFile> response() {
      try {
        URL url = new URL(service, "collect/tree");
        HttpPost request = new HttpPost(url.toExternalForm());
        request.setHeader("Content-Type", "application/json");
        request.setHeader("Content-Encoding", "gzip");
        request.setEntity(new EntityTemplate(raw -> {
          try (OutputStream os = new GZIPOutputStream(raw)) {
            writeJsonTo(os);
          }
        }));

        if (outputAuditLog()) {
          System.err.printf(
              "AUDIT:launchable:%ssend request method:post path:%s headers:%s args:",
              dryRunPrefix(), url, dumpHeaderAsJson(request.getAllHeaders()));
          writeJsonTo(System.err);
          System.err.println();
        }

        // even in dry run, this method needs to execute in order to show what files we'll be collecting
        try (CloseableHttpResponse response = handleError(url, client.execute(request));
             JsonParser parser = new JsonFactory().createParser(response.getEntity().getContent())) {
            return select(objectMapper.readValue(parser, String[].class));
        }
      } catch (IOException e) {
        throw new UncheckedIOException(e);
      } finally {
        files.clear();
      }
    }

    private List<VirtualFile> select(String[] response) {
      Map<String,VirtualFile> filesByPath = new HashMap<>();
      for (VirtualFile f : files) {
        filesByPath.put(f.path(), f);
      }

      List<VirtualFile> selected = new ArrayList<>();
      for (String path : response) {
        VirtualFile f = filesByPath.get(path);
        if (f!=null) {
          selected.add(f);
        }
      }

      return selected;
    }

    @Override
    public void accept(VirtualFile f) {
      files.add(f);
    }
  }
}
