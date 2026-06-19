package com.launchableinc.ingest.commits;

import org.junit.runner.RunWith;
import org.junit.runners.Suite;
import org.junit.runners.Suite.SuiteClasses;

@RunWith(Suite.class)
@SuiteClasses({
    BoundedExecutorServiceTest.class,
    CommitGraphCollectorTest.class,
    ConcurrentConsumerTest.class,
    FileChunkStreamerTest.class,
    MainTest.class,
    SSLBypassTest.class,
    GitFileTest.class,
    ProgressReporterTest.class
})
public class AllTests {}
