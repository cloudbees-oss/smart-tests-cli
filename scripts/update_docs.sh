#!/bin/bash
# Fetch the latest docs from the docsite repository into smart_tests/docs/.
# Run via: uv run poe update-docs
set -euo pipefail

REPO="git@github.com:cloudbees/docsite-cloudbees-smart-tests.git"
DOCS_DST="$(dirname "$0")/../smart_tests/docs"

tmpdir=$(mktemp -d)
trap 'rm -rf "$tmpdir"' EXIT

git clone --depth=1 "$REPO" "$tmpdir"
rm -rf "$DOCS_DST"
cp -r "$tmpdir/docs" "$DOCS_DST"
echo "Docs updated at $DOCS_DST"

CLI_REFERENCE="$DOCS_DST/modules/references/pages/cli-reference.adoc"
"$(dirname "$0")/../tools/generate_reference.py" "$CLI_REFERENCE"
echo "Regenerated CLI reference tables in $CLI_REFERENCE"
