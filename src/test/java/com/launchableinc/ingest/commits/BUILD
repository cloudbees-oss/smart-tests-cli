java_test(
    name = "AllTests",
    srcs = glob(["*.java"]),
    deps = [
        "//src/main/java/com/launchableinc/ingest/commits",
        "@maven//:com_fasterxml_jackson_core_jackson_databind",
        "@maven//:com_google_guava_guava",
        "@maven//:com_google_truth_truth",
        "@maven//:commons_io_commons_io",
        "@maven//:junit_junit",
        "@maven//:org_apache_commons_commons_compress",
        "@maven//:org_apache_httpcomponents_httpclient",
        "@maven//:org_apache_httpcomponents_httpcore",
        "@maven//:org_eclipse_jgit_org_eclipse_jgit",
        "@maven//:org_mock_server_mockserver_junit_rule_no_dependencies",
    ],
)

sh_test(
    name = "java8-compat",
    srcs = ["java8-compat.sh"],
    data = [
        "//src/main/java/com/launchableinc/ingest/commits:exe_deploy.jar",
        "@maven//:org_jvnet_animal_sniffer",
    ],
)
