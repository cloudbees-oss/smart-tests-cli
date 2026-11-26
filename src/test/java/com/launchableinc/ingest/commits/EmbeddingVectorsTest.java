package com.launchableinc.ingest.commits;

import static com.google.common.truth.Truth.assertThat;

import org.junit.Test;

public class EmbeddingVectorsTest {
  @Test
  public void scalesTheVectorToUnitLength() {
    assertThat(EmbeddingVectors.normalize(new float[] {3, 4}, 2)).usingTolerance(1e-6).containsExactly(0.6f, 0.8f).inOrder();
  }

  @Test
  public void theResultPassesTheServersUnitNormCheck() {
    float[] vector = EmbeddingVectors.normalize(new float[] {0.3f, -2.5f, 7.1f, 0.01f}, 4);

    double sumOfSquares = 0;
    for (float x : vector) {
      sumOfSquares += (double) x * x;
    }
    // the server accepts a length within 0.001 of 1
    assertThat(Math.abs(Math.sqrt(sumOfSquares) - 1.0)).isLessThan(1e-3);
  }

  @Test
  public void unusableVectorsAreRejected() {
    assertThat(EmbeddingVectors.normalize(null, 2)).isNull();
    assertThat(EmbeddingVectors.normalize(new float[] {1, 0, 0}, 2)).isNull(); // wrong size
    assertThat(EmbeddingVectors.normalize(new float[] {Float.NaN, 1}, 2)).isNull();
    assertThat(EmbeddingVectors.normalize(new float[] {Float.POSITIVE_INFINITY, 1}, 2)).isNull();
    assertThat(EmbeddingVectors.normalize(new float[] {0, 0}, 2)).isNull(); // cannot be scaled
  }
}
