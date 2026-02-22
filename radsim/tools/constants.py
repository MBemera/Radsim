"""Constants and configuration for RadSim tools.

RadSim Principle: Single Source of Truth for Configuration
"""

# =============================================================================
# SECURITY CONFIGURATION
# =============================================================================

# Commands requiring explicit user confirmation
DESTRUCTIVE_COMMANDS = {
    "rm",
    "rmdir",
    "del",
    "unlink",
    "shred",  # Deletion
    "sudo",
    "su",
    "chown",
    "chmod",  # Privileged
    "mv",  # Moving (can overwrite)
    "git push",
    "git reset",
    "git rebase",  # Git destructive
    "npm publish",
    "pip upload",  # Publishing
    "docker rm",
    "docker rmi",  # Container deletion
    "kubectl delete",  # Kubernetes deletion
}

# Catastrophic commands blocked at ALL security levels (no override)
ALWAYS_BLOCKED_COMMANDS = {
    "rm -rf /",
    "rm -rf /*",
    "rm -rf ~",
    "rm -rf ~/*",
    "mkfs",
    "mkfs.ext4",
    "mkfs.xfs",
    "dd if=/dev/zero",
    "dd if=/dev/random",
    ":(){ :|:& };:",
    "chmod -R 777 /",
    "> /dev/sda",
    "mv / /dev/null",
}

# Patterns that should never be written to
PROTECTED_PATTERNS = [
    ".env",
    ".env.*",
    "credentials",
    "secrets",
    ".git/config",
    "id_rsa",
    "id_ed25519",
    "*.pem",
    "*.key",
    "password",
    "token",
    # Cloud and infrastructure credentials
    ".aws/",
    ".aws/*",
    ".kube/",
    ".kube/*",
    ".ssh/",
    ".ssh/*",
    ".docker/",
    ".docker/*",
    # Certificate files
    "*.cert",
    "*.crt",
    # Package registry credentials
    ".npmrc",
    ".pypirc",
]

# =============================================================================
# SIZE LIMITS (named constants to avoid magic numbers)
# =============================================================================

MAX_FILE_SIZE = 100_000  # 100KB - Maximum file size to read
MAX_TRUNCATED_SIZE = 20_000  # 20KB - Maximum size for display
MAX_OUTPUT_SIZE = 50_000  # 50KB - Maximum shell output
MAX_ERROR_OUTPUT_SIZE = 10_000  # 10KB - Maximum error output
MAX_SEARCH_RESULTS = 100  # Maximum search results
MAX_DIRECTORY_ITEMS = 500  # Maximum directory listing items
MAX_FILES_TO_READ = 20  # Maximum files in read_many_files
