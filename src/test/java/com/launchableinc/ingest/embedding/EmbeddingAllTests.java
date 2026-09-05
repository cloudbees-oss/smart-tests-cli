package com.launchableinc.ingest.embedding;

import org.junit.runner.RunWith;
import org.junit.runners.Suite;
import org.junit.runners.Suite.SuiteClasses;

@RunWith(Suite.class)
@SuiteClasses({
    AugmentedEmbeddingStrategyTest.class,
    EmbeddingStrategyFactoryTest.class,
    RemoteEmbeddingStrategyTest.class,
    ServerRepoContextProviderTest.class,
})
public class EmbeddingAllTests {}
