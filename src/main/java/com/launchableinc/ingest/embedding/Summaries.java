package com.launchableinc.ingest.embedding;

import java.util.Map;

public class Summaries {
    public final String repoSummary;
    public final Map<String, String> dirSummaries;

    public Summaries(String repoSummary, Map<String, String> dirSummaries) {
        this.repoSummary = repoSummary;
        this.dirSummaries = dirSummaries;
    }
}
