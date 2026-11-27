package com.launchableinc.ingest.commits;

/** Makes a provider's vector acceptable to collect/embeddings, which checks length and unit norm. */
class EmbeddingVectors {
  private EmbeddingVectors() {}

  /** The server accepts a vector whose length is within this distance of 1 (EmbeddingIngestValidator). */
  private static final double UNIT_NORM_TOLERANCE = 1e-3;

  /**
   * Scales the vector to length 1.
   *
   * @return the normalized vector, or null if it is unusable: missing, not exactly {@code
   *     dimensions} long, containing NaN or infinity, or all zeros
   */
  static float[] normalize(float[] vector, int dimensions) {
    return prepare(vector, dimensions, true);
  }

  /**
   * Gets a model's vector ready to upload.
   *
   * @param scaleToUnit true to always scale to length 1. False keeps the vector as the model
   *     returned it when its length is already within the server's tolerance of 1, and scales it
   *     only when it is not, because the server would reject it otherwise
   * @return the vector to upload, or null if it is unusable: missing, not exactly {@code
   *     dimensions} long, containing NaN or infinity, or all zeros
   */
  static float[] prepare(float[] vector, int dimensions, boolean scaleToUnit) {
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
    if (!scaleToUnit && Math.abs(norm - 1.0) <= UNIT_NORM_TOLERANCE) {
      return vector.clone();
    }
    float[] result = new float[vector.length];
    for (int i = 0; i < vector.length; i++) {
      result[i] = (float) (vector[i] / norm);
    }
    return result;
  }
}
