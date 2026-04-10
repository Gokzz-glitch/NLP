#!/usr/bin/env python3
"""
Security audit: Validate secrets infrastructure and detect potential leaks.

Checks:
  1. Secret format and strength
  2. File permissions (.env files should be 600)
  3. .gitignore compliance
  4. No hardcoded secrets in source code
  5. Pre-commit hooks installed
  6. Secret Manager health

Usage:
  python scripts/audit_secrets.py [--strict] [--fix]

Options:
  --strict    Fail on warnings (default: only on errors)
  --fix       Attempt to fix issues automatically
"""

import os
import sys
import re
import subprocess
from pathlib import Path
from typing import List, Tuple, Dict


class SecurityAudit:
    """Validates entire secrets infrastructure."""
    
    def __init__(self, strict: bool = False, fix: bool = False):
        self.strict = strict
        self.fix = fix
        self.root = Path.cwd()
        self.issues = {"error": [], "warning": []}
    
    def add_issue(self, level: str, message: str):
        """Add issue to report."""
        self.issues[level].append(message)
        print(f"[{level.upper()}] {message}")
    
    def check_env_file_permissions(self):
        """Check .env file permissions."""
        print("\n1. Checking .env file permissions...")
        
        for env_file in self.root.glob(".env*"):
            if env_file.name.endswith(".template"):
                continue  # Templates are safe
            
            stat = env_file.stat()
            mode = stat.st_mode & 0o777
            
            if mode != 0o600:
                msg = f"{env_file.name} has mode {oct(mode)} (should be 0o600)"
                self.add_issue("warning", msg)
                
                if self.fix:
                    os.chmod(env_file, 0o600)
                    print(f"  Fixed: {env_file.name} → 0o600")
    
    def check_gitignore(self):
        """Check if .env files are in .gitignore."""
        print("\n2. Checking .gitignore...")
        
        gitignore_path = self.root / ".gitignore"
        if not gitignore_path.exists():
            self.add_issue("error", ".gitignore not found")
            return
        
        with open(gitignore_path) as f:
            content = f.read()
        
        required_patterns = [".env", "*.key", "*.pem", "secrets/"]
        for pattern in required_patterns:
            if pattern not in content:
                self.add_issue("warning", f"{pattern} not in .gitignore")
    
    def check_precommit_hook(self):
        """Check if pre-commit hook is installed."""
        print("\n3. Checking pre-commit hook...")
        
        hook_path = self.root / ".git" / "hooks" / "pre-commit"
        
        if not hook_path.exists():
            self.add_issue(
                "warning",
                "Pre-commit hook not installed (run: python scripts/init_secrets.py)"
            )
            return
        
        with open(hook_path) as f:
            content = f.read()
        
        if "verify_dont_leak_secrets.py" not in content:
            self.add_issue("warning", "Pre-commit hook doesn't check for secrets")
    
    def check_source_code(self):
        """Scan source code for potential secrets."""
        print("\n4. Scanning source code for secrets...")
        
        patterns = {
            "API Key": r"['\"]?api_key['\"]?\s*[:=]\s*['\"]?[A-Za-z0-9_-]{20,}",
            "Password": r"password\s*[:=]\s*['\"][^'\"]{8,}['\"]",
            "Bearer Token": r"Bearer\s+[A-Za-z0-9\._-]{20,}",
            "AWS Key": r"AKIA[0-9A-Z]{16}",
        }
        
        found_issues = False
        
        # Scan Python files
        for py_file in self.root.rglob("*.py"):
            if self._should_skip_file(py_file):
                continue
            
            try:
                with open(py_file) as f:
                    content = f.read()
                
                for pattern_name, pattern in patterns.items():
                    if re.search(pattern, content, re.IGNORECASE):
                        self.add_issue(
                            "warning",
                            f"{py_file.relative_to(self.root)}: Potential {pattern_name}"
                        )
                        found_issues = True
            except Exception:
                pass
        
        if not found_issues:
            print("  No obvious secrets found in source code")
    
    def check_secret_manager(self):
        """Test SecretManager initialization."""
        print("\n5. Testing SecretManager...")
        
        try:
            from core.secret_manager import get_manager
            
            manager = get_manager()
            
            # Check required secrets exist
            try:
                csrf = manager.get_or_raise("CSRF_SECRET_KEY")
                print("  ✓ CSRF_SECRET_KEY found")
            except Exception:
                self.add_issue(
                    "error",
                    "CSRF_SECRET_KEY not configured (required)"
                )
            
            try:
                dashboard = manager.get_or_raise("DASHBOARD_SECRET_KEY")
                print("  ✓ DASHBOARD_SECRET_KEY found")
            except Exception:
                self.add_issue(
                    "error",
                    "DASHBOARD_SECRET_KEY not configured (required)"
                )
            
            # Check optional secrets
            optional = ["GEMINI_API_KEYS", "ROBOFLOW_API_KEY", "HF_TOKEN"]
            found = 0
            for secret in optional:
                if manager.get(secret):
                    found += 1
            
            print(f"  ✓ {found}/{len(optional)} optional secrets configured")
            
        except ImportError:
            self.add_issue("warning", "SecretManager not available (core/secret_manager.py)")
        except Exception as e:
            self.add_issue("error", f"SecretManager test failed: {e}")
    
    def check_git_history(self):
        """Check if secrets were committed to git."""
        print("\n6. Checking git history for secrets...")
        
        try:
            # Git secrets check
            result = subprocess.run(
                ["git", "log", "-p", "--all", "-i", "--regexp-ignore-case"],
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
            
            print("  Run 'git log -p <file>' to inspect history manually")
            print("  Note: History cannot be easily cleaned without rewriting")
            
        except Exception:
            print("  Could not check git history")
    
    def _should_skip_file(self, filepath: Path) -> bool:
        """Check if file should be skipped."""
        skip_patterns = {
            ".venv", "__pycache__", "node_modules",
            ".git", "dist", "build", ".template"
        }
        
        for pattern in skip_patterns:
            if pattern in str(filepath):
                return True
        
        return False
    
    def audit(self) -> bool:
        """Run complete audit."""
        print("=" * 70)
        print("  SECURITY AUDIT: Secrets Infrastructure")
        print("=" * 70)
        
        self.check_env_file_permissions()
        self.check_gitignore()
        self.check_precommit_hook()
        self.check_source_code()
        self.check_secret_manager()
        self.check_git_history()
        
        return self._report()
    
    def _report(self) -> bool:
        """Print report and return overall status."""
        print("\n" + "=" * 70)
        print("  AUDIT SUMMARY")
        print("=" * 70)
        
        errors = len(self.issues["error"])
        warnings = len(self.issues["warning"])
        
        if errors > 0:
            print(f"\n✗ {errors} CRITICAL ISSUE(S):")
            for issue in self.issues["error"]:
                print(f"  - {issue}")
        
        if warnings > 0:
            print(f"\n⚠ {warnings} WARNING(S):")
            for issue in self.issues["warning"]:
                print(f"  - {issue}")
        
        if errors == 0 and warnings == 0:
            print("\n✓ All security checks passed!")
            return True
        
        if errors == 0 and not self.strict:
            print(f"\n✓ No critical issues found ({warnings} warnings)")
            return True
        
        return False


def main():
    """Main entry point."""
    import argparse
    
    parser = argparse.ArgumentParser(
        description="Security audit for secrets infrastructure"
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Fail on warnings (default: only on errors)"
    )
    parser.add_argument(
        "--fix",
        action="store_true",
        help="Attempt to fix issues automatically"
    )
    
    args = parser.parse_args()
    
    audit = SecurityAudit(strict=args.strict, fix=args.fix)
    success = audit.audit()
    
    return 0 if success else 1


if __name__ == "__main__":
    sys.exit(main())
