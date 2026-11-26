package com.launchableinc.ingest.commits;

import org.junit.runner.RunWith;
import org.junit.runners.Suite;
import org.junit.runners.Suite.SuiteClasses;

@RunWith(Suite.class)
@SuiteClasses({
    BatchEmbedderTest.class,
    BatchingConsumerTest.class,
    BoundedExecutorServiceTest.class,
    ClientEmbeddingConsumerTest.class,
    CommitGraphCollectorTest.class,
    ConcurrentConsumerTest.class,
    EmbeddingAdaptersTest.class,
    EmbeddingContractTest.class,
    EmbeddingTextTest.class,
    EmbeddingVectorsTest.class,
    FileChunkStreamerTest.class,
    JtokkitTokenCounterTest.class,
    MainTest.class,
    ModelProfilesTest.class,
    OpenAiCompatibleAdapterTest.class,
    SSLBypassTest.class,
    GitFileTest.class,
    ProgressReporterTest.class
})
public class AllTests {}
