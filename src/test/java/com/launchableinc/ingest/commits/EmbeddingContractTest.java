package com.launchableinc.ingest.commits;

import static com.google.common.truth.Truth.assertThat;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import java.util.ArrayList;
import java.util.Iterator;
import java.util.List;
import org.junit.Test;

/** Pins down the JSON that goes to and comes from the Smart Tests server for client-side embedding. */
public class EmbeddingContractTest {
  private static final ObjectMapper MAPPER = CommitGraphCollector.objectMapper;

  @Test
  public void anUploadedFileHasExactlyTheFieldsTheServerExpects() {
    JsonNode json = MAPPER.valueToTree(new FileEmbedding("src/a.txt", "abc123def456", new float[] {0.5f, 0.25f}));

    List<String> fields = new ArrayList<>();
    for (Iterator<String> names = json.fieldNames(); names.hasNext(); ) {
      fields.add(names.next());
    }
    assertThat(fields).containsExactly("fileName", "blobSha", "embedding");
    assertThat(json.get("fileName").asText()).isEqualTo("src/a.txt");
    assertThat(json.get("blobSha").asText()).isEqualTo("abc123def456");
    assertThat(json.get("embedding").get(1).asDouble()).isEqualTo(0.25);
  }

  @Test
  public void readsTheServersIngestStatusAndIgnoresFieldsItDoesNotKnow() throws Exception {
    JSEmbeddingIngestProgress status =
        MAPPER.readValue(
            "{\"status\":\"SUCCEEDED\",\"ingestedCount\":3,\"somethingNew\":true,"
                + "\"rejectedFiles\":[{\"fileName\":\"a.txt\",\"reason\":\"not unit length\",\"extra\":1}]}",
            JSEmbeddingIngestProgress.class);

    assertThat(status.status).isEqualTo(BackgroundWorkStatus.SUCCEEDED);
    assertThat(status.ingestedCount).isEqualTo(3);
    assertThat(status.rejectedFiles).hasSize(1);
    assertThat(status.rejectedFiles.get(0).fileName).isEqualTo("a.txt");
    assertThat(status.rejectedFiles.get(0).reason).isEqualTo("not unit length");
  }

  @Test
  public void readsTheSummaries() throws Exception {
    JSSummariesResponse summaries =
        MAPPER.readValue(
            "{\"repoSummary\":\"A test repo\",\"dirSummaries\":{\"\":\"Top level\",\"src\":\"Sources\"}}",
            JSSummariesResponse.class);

    assertThat(summaries.repoSummary).isEqualTo("A test repo");
    assertThat(summaries.dirSummaries).containsExactly("", "Top level", "src", "Sources");
  }
}
