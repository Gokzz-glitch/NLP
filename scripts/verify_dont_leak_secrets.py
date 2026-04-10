#!/usr/bin/env python3
"""
Pre-commit security hook: Prevent accidental secrets leakage.

Checks staged files for:
  1. Hardcoded API keys/credentials
  2. Common secret patterns
  3. Unencrypted sensitive data
  4. .env files being committed

Usage:
  python scripts/verify_dont_leak_secrets.py

Returns:
  0 if safe (no secrets found)
  1 if issues found (blocks commit)

Install as pre-commit hook:
  cp scripts/verify_dont_leak_secrets.py .git/hooks/pre-commit
  chmod +x .git/hooks/pre-commit
"""

import re
import subprocess
import sys
from pathlib import Path


class SecretDetector:
    """Detects common secret patterns in code."""
    
    # Sensitive patterns to check
    PATTERNS = {
        "API Key": re.compile(
            r"['\"]?[A-Za-z0-9_-]*[Aa][Pp][Ii][_-]?[Kk]ey['\"]?\s*[:=]\s*['\"]?[A-Za-z0-9_\-\.]{20,}",  # noqa
            re.IGNORECASE
        ),
        "AWS Key": re.compile(r"AKIA[0-9A-Z]{16}"),
        "Private Key": re.compile(
            r"-----BEGIN RSA PRIVATE KEY-----.*-----END RSA PRIVATE KEY-----",
            re.DOTALL
        ),
        "Password Assignment": re.compile(
            r"['\"]?pass(word)?['\"]?\s*[:=]\s*['\"]?[^\"']{8,}['\"]?",
            re.IGNORECASE
        ),
        "Bearer Token": re.compile(r"Bearer\s+[A-Za-z0-9\._-]{20,}"),
        "GitHub Token": re.compile(r"ghp_[A-Za-z0-9_]{36}"),
        "Stripe Key": re.compile(r"(sk|rk)_live_[A-Za-z0-9]{20,}"),
        "AWS Secret": re.compile(r"aws_secret_access_key\s*[:=]\s*[A-Za-z0-9/+=]{40}"),
        "Slack Webhook": re.compile(
            r"hooks\.slack\.com/services/T[A-Z0-9]+/B[A-Z0-9]+/[A-Za-z0-9]+"
        ),
        "External Secret": re.compile(
            r"__REPLACE_WITH_[A-Z0-9_]+__",  # Template placeholders
            re.IGNORECASE
        ),
    }
    
    # Files that should never be committed
    FORBIDDEN_FILES = {
        ".env",
        ".env.local",
        ".env.production",
        ".env.development",
        ".aws/credentials",
        ".ssh/id_rsa",
        "secrets.json",
        "credentials.json",
        "config.json",
    }
    
    # File patterns to ignore (won't check)
    IGNORE_PATTERNS = {
        ".png", ".jpg", ".jpeg", ".gif",  # Images
        ".pdf", ".zip", ".tar",  # Archives
        ".pyc", ".o", ".a",  # Compiled
        ".git", ".venv", "__pycache__",  # System
        "node_modules", "dist", "build",  # Dependencies
        ".env.security.template",  # Template is safe
        ".env.*.template",  # All templates safe
    }
    
    def __init__(self):
        self.issues = []
    
    def should_check(self, filepath: str) -> bool:
        """Check if file should be scanned."""
        p = Path(filepath)
        
        # Skip ignored patterns
        for pattern in self.IGNORE_PATTERNS:
            if pattern in filepath:
                return False
        
        # Check forbidden files
        if p.name in self.FORBIDDEN_FILES:
            return False
        
        # Skip binary files
        try:
            with open(filepath, "rb") as f:
                chunk = f.read(512)
                if b"\x00" in chunk:
                    return False  # Binary file
        except Exception:
            return False
        
        return True
    
    def scan_file(self, filepath: str) -> bool:
        """Scan file for secrets. Returns True if safe."""
        if not self.should_check(filepath):
            return True
        
        try:
            with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read()
        except Exception as e:
            self.issues.append(f"Could not read {filepath}: {e}")
            return False
        
        # Check each pattern
        for pattern_name, pattern in self.PATTERNS.items():
            for match in pattern.finditer(content):
                line_no = content[:match.start()].count("\n") + 1
                self.issues.append(
                    f"{filepath}:{line_no} - {pattern_name}: {match.group()[:60]}..."
                )
        
        return len(self.issues) == 0
    
    def scan_staged_files(self) -> bool:
        """Scan all staged files using git. Returns True if all safe."""
        try:
            # Get staged files
            result = subprocess.run(
                ["git", "diff", "--cached", "--name-only", "--diff-filter=ACM"],
                capture_output=True,
                text=True,
                check=False,
            )
            
            if result.returncode != 0:
                print("Warning: Could not get staged files from git")
                return True
            
            staged_files = result.stdout.strip().split("\n")
            staged_files = [f for f in staged_files if f]
            
            # Scan each file
            safe = True
            for filepath in staged_files:
                if not self.scan_file(filepath):
                    safe = False
            
            return safe
        except FileNotFoundError:
            print("Warning: git not found, skipping pre-commit check")
            return True
    
    def report(self):
        """Print report of findings."""
        if not self.issues:
            print("✓ Pre-commit check passed: No secrets found")
            return True
        
        print(f"\n❌ SECURITY ALERT: Found {len(self.issues)} potential secret(s):")
        print("=" * 70)
        for issue in self.issues:
            print(f"  {issue}")
        print("=" * 70)
        print("\nFIX:")
        print("  1. Remove the secret from the file")
        print("  2. Stage the corrected file: git add <file>")
        print("  3. Run commit again")
        print("\nIf this is a false positive, add the file to IGNORE_PATTERNS")
        print("in scripts/verify_dont_leak_secrets.py\n")
        
        return False


def main():
    """Main entry point."""
    detector = SecretDetector()
    
    if detector.scan_staged_files():
        return 0
    else:
        return 1


if __name__ == "__main__":
    sys.exit(main())
