#!/bin/bash
# Update the bundled OpenAPI schema from mothership dev server
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CLI_DIR="$(dirname "$SCRIPT_DIR")"
SCHEMA_FILE="$CLI_DIR/smart_tests/schema/openapi-schema.json"
# Override with SCHEMA_PORT if the dev server runs on another port
SCHEMA_PORT="${SCHEMA_PORT:-8081}"
API_DOCS_URL="http://localhost:$SCHEMA_PORT/intake/v3/api-docs"

echo "Fetching OpenAPI schema from local dev server..."

# Check if mothership is running
if ! curl -s -f "$API_DOCS_URL" > /dev/null 2>&1; then
    echo "Error: Mothership dev server not running at localhost:$SCHEMA_PORT"
    echo "Please start it with: cd mothership && bazel run //src/main/java/com/launchableinc/mercury/intake"
    exit 1
fi

# Create schema directory if it doesn't exist
mkdir -p "$(dirname "$SCHEMA_FILE")"

# Fetch and save schema
curl -s "$API_DOCS_URL" > "$SCHEMA_FILE"

# Validate and format the JSON with proper indentation and trailing newline
python3 << PYTHON_EOF
import json

with open("$SCHEMA_FILE", 'r') as f:
    schema = json.load(f)

# Write back with proper formatting
with open("$SCHEMA_FILE", 'w') as f:
    json.dump(schema, f, indent=2)
    f.write('\n')  # Add trailing newline
PYTHON_EOF

echo "✓ Schema updated successfully: $SCHEMA_FILE"
echo ""

# Show what changed
if git diff --quiet "$SCHEMA_FILE" 2>/dev/null; then
    echo "No changes detected in schema"
else
    echo "Changes detected:"
    git diff --stat "$SCHEMA_FILE" 2>/dev/null || echo "(Not a git repository)"
    echo ""
    echo "Review with: git diff $SCHEMA_FILE"
    echo "Commit with: git add $SCHEMA_FILE && git commit -m 'Update OpenAPI schema'"
fi
