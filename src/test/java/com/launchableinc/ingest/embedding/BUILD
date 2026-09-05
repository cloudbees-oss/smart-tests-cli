java_test(
    name = "EmbeddingTests",
    srcs = glob(["*.java"]),
    test_class = "com.launchableinc.ingest.embedding.EmbeddingAllTests",
    deps = [
        "//src/main/java/com/launchableinc/ingest/embedding",
        "@maven//:com_google_truth_truth",
        "@maven//:junit_junit",
        "@maven//:org_apache_httpcomponents_httpclient",
        "@maven//:org_mock_server_mockserver_junit_rule_no_dependencies",
    ],
)
