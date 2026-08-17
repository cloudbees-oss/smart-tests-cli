package com.launchableinc.ingest.embedding;

public class FileToEmbed {
    public final String fileName;
    public final String content;
    public final String blobSha;

    public FileToEmbed(String fileName, String content, String blobSha) {
        this.fileName = fileName;
        this.content = content;
        this.blobSha = blobSha;
    }
}
