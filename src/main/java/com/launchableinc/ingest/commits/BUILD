package(
    default_visibility = ["//visibility:public"],
)

java_library(
    name = "commits",
    srcs = glob(["*.java"]),
    deps = [
        "//src/main/java/com/launchableinc/ingest/embedding",
        "@maven//:args4j_args4j",
        "@maven//:com_fasterxml_jackson_core_jackson_annotations",
        "@maven//:com_fasterxml_jackson_core_jackson_core",
        "@maven//:com_fasterxml_jackson_core_jackson_databind",
        "@maven//:com_google_guava_guava",
        "@maven//:commons_io_commons_io",
        "@maven//:org_apache_commons_commons_compress",
        "@maven//:org_apache_httpcomponents_httpclient",
        "@maven//:org_apache_httpcomponents_httpcore",
        "@maven//:org_eclipse_jgit_org_eclipse_jgit",
        "@maven//:org_slf4j_slf4j_api",
    ],
)

java_binary(
    name = "exe",
    main_class = "com.launchableinc.ingest.commits.Main",
    runtime_deps = [
        ":commits",
        "@maven//:org_slf4j_slf4j_jdk14",
    ],
)
