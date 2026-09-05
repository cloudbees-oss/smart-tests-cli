package com.launchableinc.ingest.embedding;

public class FileEmbeddingResult {
    public final String fileName;
    public final String blobSha;
    public final float[] embedding;

    public FileEmbeddingResult(String fileName, String blobSha, float[] embedding) {
        this.fileName = fileName;
        this.blobSha = blobSha;
        this.embedding = embedding;
    }
}
