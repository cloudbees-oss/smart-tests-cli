package com.launchableinc.ingest.commits;

import com.launchableinc.ingest.embedding.EmbeddingStrategy;
import com.launchableinc.ingest.embedding.FileToEmbed;
import com.launchableinc.ingest.embedding.FileEmbeddingResult;
import com.fasterxml.jackson.core.JsonFactory;
import com.fasterxml.jackson.core.JsonGenerator;
import com.fasterxml.jackson.core.JsonParser;
import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ObjectNode;
import com.google.common.collect.ImmutableList;
import org.apache.commons.compress.archivers.tar.TarArchiveEntry;
import org.apache.commons.compress.archivers.tar.TarArchiveInputStream;
import org.apache.commons.io.IOUtils;
import org.apache.http.Header;
import org.apache.http.HttpResponse;
import org.apache.http.client.config.RequestConfig;
import org.apache.http.client.methods.CloseableHttpResponse;
import org.apache.http.client.methods.HttpPost;
import org.apache.http.entity.ContentProducer;
import org.apache.http.entity.EntityTemplate;
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
import java.io.FileInputStream;
import java.io.FileOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.io.InputStreamReader;
import java.io.OutputStream;
import java.io.UncheckedIOException;
import java.net.URL;
import java.time.Duration;
import java.util.ArrayList;
import java.util.Collection;
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

import static com.google.common.collect.ImmutableList.toImmutableList;
import static java.util.Arrays.stream;

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
  private static final String APPLICATION_JSON = "application/json";
  private static final int PROGRESS_REPORT_INTERVAL = 3000;

  private final String rootName;

  /**
   * Root repository to start processing.
   *
   * <p>Sub modules form a tree structure rooted at this repository.
   */
  private final Repository root;

  private final AtomicInteger commitsSent = new AtomicInteger(), filesSent = new AtomicInteger();

  private boolean collectCommitMessage, collectFiles;

  private int maxDays;

  private EmbeddingStrategy embeddingStrategy;

  private boolean reportAllFiles;

  private boolean audit;

  private boolean dryRun;

  private boolean warnMissingObject;

  /**
   * Reports the # of file transfers, which is the most time-consuming part.
   */
  private final ProgressReporter fileTransferProgressReporter = new ProgressReporter(Duration.ofMillis(PROGRESS_REPORT_INTERVAL));


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
    try (LaunchableHttpClient client = new LaunchableHttpClient(builder.build())) {
      latestUrl = new URL(service, "latest");
      if (outputAuditLog()) {
        System.err.printf(
            "AUDIT:launchable:%ssend request method:get path: %s%n", dryRunPrefix(), latestUrl);
      }
      CloseableHttpResponse latestResponse = client.httpGet(latestUrl);
      ImmutableList<ObjectId> advertised = getAdvertisedRefs(latestResponse);
      honorControlHeaders(latestResponse);

      if (embeddingStrategy != null) {
        transferWithEmbeddings(advertised, service, client);
      } else {
        // every time a new stream is needed, supply ByteArrayOutputStream, and when the data is all
        // written, turn around and ship that over
        transfer(
          advertised,
          (ContentProducer commits) -> sendCommits(service, client, commits),
          new TreeReceiverImpl(service, client),
          (ContentProducer files) -> sendFiles(service, client, files),
          1024);
      }
    }
  }

  private void sendCommits(URL service, LaunchableHttpClient client, ContentProducer commits) throws IOException {
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
    client.httpPost(request).close();
  }

  private void sendFiles(URL service, LaunchableHttpClient client, ContentProducer files) throws IOException {
    URL url = new URL(service, "collect/files");
    HttpPost request = new HttpPost(url.toExternalForm());
    request.setHeader("Content-Type", "application/octet-stream");
    request.setHeader("Accept", "application/json; mode=async");
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

    int workId = readResponse(client.httpPost(request), JSAsyncFileCollectionResponse.class).workId;
    URL workUrl = new URL(service, "collect/files/work/" + workId);
    int filesProcessed = 0;
    while (true) {
      try {
        Thread.sleep(PROGRESS_REPORT_INTERVAL);
      } catch (InterruptedException e) {
        // not expecting this to happen, sufficient to fail
        throw new IOException();
      }
      JSAsyncFileCollectionProgress status = readResponse(client.httpGet(workUrl), JSAsyncFileCollectionProgress.class);
      for (; filesProcessed<status.filesProcessed; filesProcessed++) {
        fileTransferProgressReporter.incrementCompleted();
      }
      switch (status.status) {
      case IN_PROGRESS:
        break;  // keep polling
      case SUCCEEDED:
        return;
      case FAILED:
      case ABANDONED:
        throw new IOException("File collection (workId="+workId+") failed: " + status.status);
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

  private ImmutableList<ObjectId> getAdvertisedRefs(CloseableHttpResponse response) throws IOException {
    String[] ids = readResponse(response, String[].class);
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
      Concurrency design
      ==================

      The work ahead of us is:
        - for each repository
          - send all the files we need to send
          - then record commits

      Commit recording has to happen after file sending, to ensure the server is in possession of all the files
      relevant to the commits being recorded. This constraint allows for two places of parallelism:
        1. process multiple repositories in parallel
        2. within a repository, send (or "collect") files in parallel

      We exploit both of them. But by using two pools. The "scan" pool is used to parallelize the outer loop of
      "for each repository". The "transfer" pool is used to parallelize file collection network I/O with the server.

      Those are matched M:N -- any scan thread can hand over work to any available transfer thread. This way,
      the user gets speed boost, whether it's a single massive repo or a lot of small repos.
      The separate transfer pool limit cap the concurrent server connections, to avoid overwhelming the server.

      Both thread pool are bounded, meaning the work producer gets blocked until the work consumer keeps up.
      This creates natural work throttling, keeping overall memory consumption in check
     */

    ExecutorService scanPool = new BoundedExecutorService(4);
//    ExecutorService scanPool = MoreExecutors.newDirectExecutorService(); // for debugging
    ExecutorService transferPool = new BoundedExecutorService(4);

    try {
      r.forEachSubModule(scanPool, br -> {
        if (collectFiles) {
          // record all the necessary BLOBs first, before attempting to record its commit.
          // this way, if the file collection fails, the server won't see this commit, so the future
          // "record commit" invocation will retry the file collection, thereby making the behavior idempotent.

          // ConcurrentConsumer parallelizes file sending within a repository. When it leads the try block
          // it ensures all the submissions have completed.
          try (ConcurrentConsumer<ContentProducer> parallel = new ConcurrentConsumer<>(fileSender, transferPool);
               FileChunkStreamer fs = new FileChunkStreamer(r::buildHeader, parallel, chunkSize);
               FlushableConsumer<VirtualFile> fsr = fileTransferProgressReporter.newProducer(fs)) {
            br.collectFiles(advertised, treeReceiver, fsr);
          }
        }

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
      scanPool.shutdown();
      transferPool.shutdown();
    }
  }

  /**
   * Embedding mode: collects files via the tree handshake, embeds them, uploads vectors.
   * Commits are sent normally. TAR file upload is skipped.
   */
  private void transferWithEmbeddings(ImmutableList<ObjectId> advertised, URL service, LaunchableHttpClient client) throws IOException {
    EmbeddingUploader uploader = new EmbeddingUploader();
    EmbeddingFileConsumer embeddingConsumer = new EmbeddingFileConsumer(
        embeddingStrategy, uploader, service, client);

    ByRepository r = new ByRepository(root, rootName);
    ExecutorService scanPool = new BoundedExecutorService(4);
    ExecutorService transferPool = new BoundedExecutorService(4);

    try {
      r.forEachSubModule(scanPool, br -> {
        try (ConcurrentConsumer<ContentProducer> parallel = new ConcurrentConsumer<>((ContentProducer cp) -> {}, transferPool);
             FlushableConsumer<VirtualFile> fsr = fileTransferProgressReporter.newProducer(embeddingConsumer)) {
          br.collectFiles(advertised, new TreeReceiverImpl(service, client), fsr);
        }

        try (CommitChunkStreamer cs = new CommitChunkStreamer((ContentProducer commits) -> sendCommits(service, client, commits), 1024)) {
          br.collectCommits(advertised, cs);
        }
      });
    } finally {
      scanPool.shutdown();
      transferPool.shutdown();
    }

    if (!embeddingConsumer.pending.isEmpty()) {
      embeddingConsumer.flush();
    }
  }

  /** Accumulates VirtualFile objects, converts to FileToEmbed, and on flush calls embed + upload. */
  private class EmbeddingFileConsumer implements FlushableConsumer<VirtualFile> {
    private final EmbeddingStrategy strategy;
    private final EmbeddingUploader uploader;
    private final URL service;
    private final LaunchableHttpClient client;
    final List<FileToEmbed> pending = new ArrayList<>();

    EmbeddingFileConsumer(EmbeddingStrategy strategy, EmbeddingUploader uploader,
                          URL service, LaunchableHttpClient client) {
      this.strategy = strategy;
      this.uploader = uploader;
      this.service = service;
      this.client = client;
    }

    @Override
    public void accept(VirtualFile f) {
      try {
        ByteArrayOutputStream baos = new ByteArrayOutputStream((int) Math.min(f.size(), 1024 * 1024));
        f.writeTo(baos);
        String content = baos.toString("UTF-8");
        pending.add(new FileToEmbed(f.path(), content, f.blob().name()));
      } catch (IOException e) {
        throw new UncheckedIOException(e);
      }
    }

    @Override
    public void flush() throws IOException {
      if (pending.isEmpty()) return;
      List<FileEmbeddingResult> results = strategy.embed(pending);
      uploader.upload(service, client, results, strategy.modelName(), strategy.dimensions());
      pending.clear();
      filesSent.addAndGet(results.size());
    }

    @Override
    public void close() throws IOException {
      flush();
    }
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

  public void setEmbeddingStrategy(EmbeddingStrategy embeddingStrategy) {
    this.embeddingStrategy = embeddingStrategy;
  }

  /** Process commits per repository. */
  final class ByRepository implements AutoCloseable {
    /** Names that uniquely identifies this Git repository among other Git repositories collected for the workspace. */
    private final String name;
    private final Repository git;

    private final ObjectReader objectReader;
    private final ThreadLocal<ObjectReader> readers;
    private final Set<ObjectId> shallowCommits;
    private final ObjectId headId;

    ByRepository(Repository git, String name) throws IOException {
      this.name = name;
      this.git = git;
      this.objectReader = git.newObjectReader();
      this.shallowCommits = objectReader.getShallowCommits();
      this.headId = git.resolve("HEAD");
      this.readers = ThreadLocal.withInitial(objectReader::newReader);
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
              GitFile f = new GitFile(name, treeWalk.getPathString(), head, readers::get);
              // to avoid excessive data transfer, skip files that are too big
              if (f.size() < 1024 * 1024 && f.isText() && !f.path.equals(HEADER_FILE)) {
                treeReceiver.accept(f);
              }
            }
          }
        }

        // Now let the server select the files it actually wants to see
        Collection<VirtualFile> files = treeReceiver.response();

        for (VirtualFile f : files) {
          fileReceiver.accept(f);
          filesSent.incrementAndGet();
        }

        fileReceiver.flush();
      }
    }

    /**
     * Creates a per repository "header" file as a {@link VirtualFile}.
     * Currently, this is just the list of files in the repository.
     */
    VirtualFile buildHeader(List<VirtualFile> files) throws IOException {
      ByteArrayOutputStream os = new ByteArrayOutputStream();
      try (JsonGenerator w = new JsonFactory().createGenerator(os)) {
        w.setCodec(objectMapper);
        w.writeStartObject();
        {
          w.writeArrayFieldStart("tree");
          try (TreeWalk tw = new TreeWalk(git)) {
            tw.addTree(git.parseCommit(headId).getTree());
            tw.setRecursive(true);

            while (tw.next()) {
              w.writeStartObject();
              w.writeStringField("path", tw.getPathString());
              w.writeEndObject();
            }
          }
          w.writeEndArray();

          w.writeArrayFieldStart("inThisChunk");
          for (VirtualFile f : files) {
            w.writeStartObject();
            w.writeStringField("path", f.path());
            w.writeEndObject();
          }
          w.writeEndArray();
        }
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
    private final LaunchableHttpClient client;

    public TreeReceiverImpl(URL service, LaunchableHttpClient client) {
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
        request.setHeader("Content-Type", APPLICATION_JSON);
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
        return select(readResponse(client.httpPost(request), String[].class));
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

  /**
   * To assist troubleshooting, captue the network response into a local file and then replay.
   */
  private InputStream maybeDump(InputStream content, String env) throws IOException {
    String file = System.getenv(env);
    if (file==null) {
      return content;
    }
    // write the content to a file for debugging purpose, but still return the content so that the program can continue
    try (OutputStream out = new FileOutputStream(file)) {
      IOUtils.copy(content, out);
    }
    content.close();

    return new FileInputStream(file);
  }
}
