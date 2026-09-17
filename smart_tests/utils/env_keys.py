import os

REPORT_ERROR_KEY = "SMART_TESTS_REPORT_ERROR"
TOKEN_KEY = "SMART_TESTS_TOKEN"
# OIDC id-token presented by a CI pipeline (e.g. a Jenkins-minted RS256 JWT). Used by
# `smart-tests verify --oidc` for credential-free bootstrap and as the bearer for subsequent
# workspace-scoped calls. See authentication.authentication_headers().
OIDC_TOKEN_KEY = "SMART_TESTS_OIDC_TOKEN"
ORGANIZATION_KEY = "SMART_TESTS_ORGANIZATION"
WORKSPACE_KEY = "SMART_TESTS_WORKSPACE"
BASE_URL_KEY = "SMART_TESTS_BASE_URL"
# Opt in to the generic GitHub Actions OIDC flow: the CLI fetches the GitHub id-token and presents
# it like any other OIDC token. Intake verifies it against trusted_oidc_subjects (self-serve in the
# webapp) instead of the deprecated trusted_github_repositories path. See authentication_headers().
GITHUB_OIDC_KEY = "SMART_TESTS_GITHUB_OIDC_TOKEN_AUTH"
# Deprecated opt in to the legacy GitHub Actions OIDC flow (repository-claim matching). Kept working
# for backward compatibility; when set, the CLI signals Intake to use the legacy path via a header.
LEGACY_GITHUB_OIDC_KEY = "EXPERIMENTAL_GITHUB_OIDC_TOKEN_AUTH"
# Audience the GitHub id-token must be minted for so the generic OIDC path's aud check passes.
# Overridable for non-production Intake environments.
OIDC_AUDIENCE_KEY = "SMART_TESTS_OIDC_AUDIENCE"
SKIP_TIMEOUT_RETRY = "SMART_TESTS_SKIP_TIMEOUT_RETRY"
COMMIT_TIMEOUT = "SMART_TESTS_COMMIT_TIMEOUT"
SKIP_CERT_VERIFICATION = "SMART_TESTS_SKIP_CERT_VERIFICATION"
SESSION_DIR_KEY = "SMART_TESTS_SESSION_DIR"
CALLER_KEY = "SMART_TESTS_CALLER"

# Legacy token key for backward compatibility
LEGACY_TOKEN_KEY = "LAUNCHABLE_TOKEN"

# GitHub Actions matrix as JSON, e.g. SMART_TEST_GITHUB_ACTIONS_MATRIX='{"shard":"1","os":"ubuntu"}'
MATRIX_KEY = "SMART_TEST_GITHUB_ACTIONS_MATRIX"


def get_token():
    """Get token with backward compatibility for LAUNCHABLE_TOKEN."""
    return os.getenv(TOKEN_KEY) or os.getenv(LEGACY_TOKEN_KEY)


def detect_ci_provider() -> str:
    if os.environ.get("GITHUB_ACTIONS"):
        return "github-actions"
    if os.environ.get("JENKINS_URL"):
        return "jenkins"
    if os.environ.get("CIRCLECI"):
        return "circleci"
    if os.environ.get("CODEBUILD_BUILD_ID"):
        return "codebuild"
    return ""
