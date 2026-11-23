package com.launchableinc.ingest.commits;

/** Makes a provider's vector acceptable to collect/embeddings, which checks length and unit norm. */
class EmbeddingVectors {
  private EmbeddingVectors() {}

  /**
   * Scales the vector to length 1.
   *
   * @return the normalized vector, or null if it is unusable: missing, not exactly {@code
   *     dimensions} long, containing NaN or infinity, or all zeros
   */
  static float[] normalize(float[] vector, int dimensions) {
    if (vector == null || vector.length != dimensions) {
      return null;
    }
    double sumOfSquares = 0;
    for (float x : vector) {
      if (Float.isNaN(x) || Float.isInfinite(x)) {
        return null;
      }
      sumOfSquares += (double) x * x;
    }
    double norm = Math.sqrt(sumOfSquares);
    if (norm == 0 || Double.isInfinite(norm)) {
      return null;
    }
    float[] result = new float[vector.length];
    for (int i = 0; i < vector.length; i++) {
      result[i] = (float) (vector[i] / norm);
    }
    return result;
  }
}
