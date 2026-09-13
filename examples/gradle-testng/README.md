# Gradle + TestNG + CloudBees Smart Tests

This is a minimal Gradle and TestNG project that demonstrates CloudBees Smart
Tests predictive test selection. It has two test classes so you can see that a
subset runs only the selected class.

## Prerequisites

* JDK 17 or later
* CloudBees Smart Tests CLI authenticated for the target workspace

Run the whole suite:

```sh
./gradlew test
```

## CloudBees Smart Tests pipeline

The normal CI flow is:

```sh
# Verify credentials, then record the source revision for this build.
smart-tests verify
smart-tests record build --build "$CI_BUILD_ID" --source main=.

# Create and save a test-session identifier.
smart-tests record session \
  --build "$CI_BUILD_ID" \
  --test-suite gradle-testng \
  > smart-tests-session.txt

# Ask for selected TestNG classes. --bare is required: the adapter expects one
# fully-qualified class name per line, not Gradle --tests arguments.
smart-tests subset gradle \
  --session "$(cat smart-tests-session.txt)" \
  --target 80% \
  --bare \
  src/test/java \
  > smart-tests-subset.txt

# launchable-testng is on the test runtime classpath and reads this file.
LAUNCHABLE_SUBSET_FILE_PATH="$PWD/smart-tests-subset.txt" ./gradlew test

# Gradle produces JUnit XML reports even though the framework is TestNG.
smart-tests record tests gradle \
  --session "$(cat smart-tests-session.txt)" \
  build/test-results/test
```

Always run the final `record tests` command, including after a failing test
run. In CI, retain the Gradle exit status and record the reports before exiting
with that status.

```sh
set +e
LAUNCHABLE_SUBSET_FILE_PATH="$PWD/smart-tests-subset.txt" ./gradlew test
test_exit=$?

smart-tests record tests gradle \
  --session "$(cat smart-tests-session.txt)" \
  build/test-results/test

exit "$test_exit"
```

## Try selection without CloudBees Smart Tests

`demo-subset.txt` simulates the output produced by `smart-tests subset gradle
--bare`:

```sh
LAUNCHABLE_SUBSET_FILE_PATH="$PWD/demo-subset.txt" ./gradlew clean test
```

Only `AdditionTest` runs. Remove `LAUNCHABLE_SUBSET_FILE_PATH` to run all
tests again.

## Important details

* `launchable-testng` 1.3.0 reads `LAUNCHABLE_SUBSET_FILE_PATH`. The current
  CloudBees documentation calls this `SMART_TESTS_SUBSET_FILE_PATH`, but that
  variable is not read by the published adapter. Set the `LAUNCHABLE_` variable
  shown in this sample.
* `launchable-testng` is a TestNG listener. The `useTestNG` configuration in
  `build.gradle` registers it explicitly because Gradle does not discover
  TestNG listeners from `META-INF/services`. Do not add
  `--tests "$(cat smart-tests-subset.txt)"` to the Gradle command for this
  integration.
* `LAUNCHABLE_SUBSET_FILE_PATH` must be an absolute path or a path relative to
  the process that invokes Gradle.
* The file contains fully-qualified test class names, one per line.
