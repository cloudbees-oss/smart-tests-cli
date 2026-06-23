package com.launchableinc.ingest.commits;

import org.junit.runner.RunWith;
import org.junit.runners.Suite;
import org.junit.runners.Suite.SuiteClasses;

@RunWith(Suite.class)
@SuiteClasses({
    CommitGraphCollectorTest.class,
    MainTest.class,
    FileChunkStreamerTest.class,
    SSLBypassTest.class,
    ProgressReportingConsumerTest.class
})
public class AllTests {}
