package com.launchableinc.ingest.commits;

import com.fasterxml.jackson.annotation.JsonProperty;
import java.util.Map;

/** Response of collect/summaries. Folders that were not summarized are absent from dirSummaries. */
public class JSSummariesResponse {
  @JsonProperty public String repoSummary;

  /** One sentence per folder. Top-level files belong to the folder named "". */
  @JsonProperty public Map<String, String> dirSummaries;
}
