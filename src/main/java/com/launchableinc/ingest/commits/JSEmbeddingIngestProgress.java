package com.launchableinc.ingest.commits;

import com.fasterxml.jackson.annotation.JsonIgnoreProperties;
import com.fasterxml.jackson.annotation.JsonProperty;
import java.util.List;

/** Response of GET collect/embeddings/work/{id}. */
@JsonIgnoreProperties(ignoreUnknown = true)
public class JSEmbeddingIngestProgress {
  @JsonProperty public BackgroundWorkStatus status;

  /** How many files the server stored. */
  @JsonProperty public int ingestedCount;

  /** Files the server refused, with the reason. */
  @JsonProperty public List<RejectedFile> rejectedFiles;

  @JsonIgnoreProperties(ignoreUnknown = true)
  public static class RejectedFile {
    @JsonProperty public String fileName;
    @JsonProperty public String reason;
  }
}
