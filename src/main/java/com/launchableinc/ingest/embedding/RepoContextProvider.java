package com.launchableinc.ingest.embedding;

import java.io.IOException;
import java.util.List;

public interface RepoContextProvider {
    Summaries getSummaries(List<FileToEmbed> files) throws IOException;
}
