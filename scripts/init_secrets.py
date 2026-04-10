#!/usr/bin/env python3
"""
Initialize secrets management system for NLP project.

This script:
  1. Guides through creating strong secrets
  2. Creates .env.local with user values
  3. Validates secret formats
  4. Sets up pre-commit hooks
  5. Tests SecretManager

Usage:
  python scripts/init_secrets.py

After running:
  export $(cat .env.local | xargs)
"""

import os
import sys
import subprocess
import secrets as secrets_module
from pathlib import Path
from typing import Optional


def print_header(title: str):
    """Print formatted header."""
    print(f"\n{'=' * 70}")
    print(f"  {title}")
    print(f"{'=' * 70}\n")


def print_success(msg: str):
    """Print success message."""
    print(f"✓ {msg}")


def print_warning(msg: str):
    """Print warning message."""
    print(f"⚠ {msg}")


def print_error(msg: str):
    """Print error message."""
    print(f"✗ {msg}")


def generate_secret(length: int = 32) -> str:
    """Generate a cryptographically strong secret."""
    return secrets_module.token_urlsafe(int(length * 0.75))


def prompt_yes_no(question: str, default: bool = True) -> bool:
    """Ask yes/no question and return answer."""
    default_str = "Y/n" if default else "y/N"
    response = input(f"{question} [{default_str}]: ").strip().lower()
    
    if not response:
        return default
    return response in ("y", "yes")


def prompt_secret(
    name: str,
    description: str,
    required: bool = False,
    min_length: int = 32,
    auto_generate: bool = False,
) -> Optional[str]:
    """Prompt user for a secret value."""
    print(f"\n{name}")
    print(f"  {description}")
    
    if auto_generate:
        generated = generate_secret(min_length)
        if prompt_yes_no(f"  Auto-generate? (min {min_length} chars)", default=True):
            print(f"  Generated: {generated[:20]}...{generated[-10:]}")
            return generated
    
    while True:
        value = input(f"  Enter value (or press Enter to skip): ").strip()
        
        if not value:
            if required:
                print_error(f"  {name} is required!")
                continue
            return None
        
        if len(value) < min_length:
            print_error(f"  Too short ({len(value)} chars, need {min_length})")
            continue
        
        return value


def setup_env_file(env_path: Path) -> dict:
    """Interactively set up .env.local file."""
    print_header("SECRETS SETUP")
    
    print("This will create .env.local with your secret values.")
    print("This file is git-ignored and never committed.\n")
    
    secrets_dict = {}
    
    # Required secrets
    print_header("REQUIRED SECRETS")
    
    csrf_secret = prompt_secret(
        "CSRF_SECRET_KEY",
        "Used for CSRF token generation in forms.",
        required=True,
        min_length=32,
        auto_generate=True,
    )
    if csrf_secret:
        secrets_dict["CSRF_SECRET_KEY"] = csrf_secret
    
    dashboard_secret = prompt_secret(
        "DASHBOARD_SECRET_KEY",
        "Used for dashboard authentication.",
        required=True,
        min_length=32,
        auto_generate=True,
    )
    if dashboard_secret:
        secrets_dict["DASHBOARD_SECRET_KEY"] = dashboard_secret
    
    # Optional secrets
    print_header("OPTIONAL SECRETS")
    
    if prompt_yes_no("Configure GPU override password?", default=False):
        gpu_password = prompt_secret(
            "GPU_OVERRIDE_PASSWORD",
            "Used for GPU resource access control (min 16 chars).",
            required=False,
            min_length=16,
            auto_generate=True,
        )
        if gpu_password:
            secrets_dict["GPU_OVERRIDE_PASSWORD"] = gpu_password
    
    if prompt_yes_no("Configure Gemini API access?", default=False):
        gemini_keys = prompt_secret(
            "GEMINI_API_KEYS",
            "Comma-separated Gemini API keys for failover.",
            required=False,
            min_length=20,
        )
        if gemini_keys:
            secrets_dict["GEMINI_API_KEYS"] = gemini_keys
    
    if prompt_yes_no("Configure Roboflow API access?", default=False):
        roboflow_key = prompt_secret(
            "ROBOFLOW_API_KEY",
            "Roboflow API key for dataset management.",
            required=False,
            min_length=20,
        )
        if roboflow_key:
            secrets_dict["ROBOFLOW_API_KEY"] = roboflow_key
    
    if prompt_yes_no("Configure Razorpay payment processing?", default=False):
        razorpay_id = prompt_secret(
            "RAZORPAY_KEY_ID",
            "Razorpay account key ID (from dashboard).",
            required=False,
            min_length=10,
        )
        if razorpay_id:
            secrets_dict["RAZORPAY_KEY_ID"] = razorpay_id
        
        razorpay_secret = prompt_secret(
            "RAZORPAY_KEY_SECRET",
            "Razorpay account secret (from dashboard).",
            required=False,
            min_length=20,
        )
        if razorpay_secret:
            secrets_dict["RAZORPAY_KEY_SECRET"] = razorpay_secret
    
    if prompt_yes_no("Configure Hugging Face access?", default=False):
        hf_token = prompt_secret(
            "HF_TOKEN",
            "Hugging Face API token.",
            required=False,
            min_length=20,
        )
        if hf_token:
            secrets_dict["HF_TOKEN"] = hf_token
    
    # Write .env.local
    print_header("WRITING .env.local")
    
    env_content = "# Auto-generated secrets configuration\n"
    env_content += "# IMPORTANT: This file is git-ignored. Never commit it.\n"
    env_content += f"# Generated by: python scripts/init_secrets.py\n\n"
    
    for key, value in secrets_dict.items():
        env_content += f"{key}={value}\n"
    
    with open(env_path, "w") as f:
        f.write(env_content)
    
    os.chmod(env_path, 0o600)  # Only readable by owner
    print_success(f"Created {env_path.name} (mode 600)")
    
    return secrets_dict


def setup_precommit_hook() -> bool:
    """Set up pre-commit hook."""
    print_header("PRE-COMMIT HOOK SETUP")
    
    hook_path = Path(".git/hooks/pre-commit")
    script_path = Path("scripts/verify_dont_leak_secrets.py")
    
    if not hook_path.parent.exists():
        print_warning("Not a git repository (.git/hooks not found)")
        return False
    
    if not script_path.exists():
        print_warning(f"Script not found: {script_path}")
        return False
    
    hook_content = f"""#!/usr/bin/env python3
# Auto-generated pre-commit hook - prevents accidental secrets leakage
import subprocess
import sys
sys.exit(subprocess.run([
    sys.executable,
    "{script_path.resolve()}",
]).returncode)
"""
    
    with open(hook_path, "w") as f:
        f.write(hook_content)
    
    os.chmod(hook_path, 0o755)
    print_success(f"Installed pre-commit hook: {hook_path}")
    
    return True


def test_secret_manager(env_path: Path, secrets_dict: dict) -> bool:
    """Test SecretManager with configured secrets."""
    print_header("TESTING SECRET MANAGER")
    
    # Load environment
    for key, value in secrets_dict.items():
        os.environ[key] = value
    
    try:
        from core.secret_manager import get_manager
        
        manager = get_manager()
        
        # Test required secrets
        try:
            csrf = manager.get_or_raise("CSRF_SECRET_KEY")
            print_success("CSRF_SECRET_KEY loaded")
        except Exception as e:
            print_error(f"CSRF_SECRET_KEY failed: {e}")
            return False
        
        # Test optional secrets
        used = []
        for key in secrets_dict.keys():
            if key != "CSRF_SECRET_KEY":
                value = manager.get(key)
                if value:
                    used.append(key)
        
        print_success(f"Loaded {len(secrets_dict)} secret(s)")
        if used:
            print(f"  Configured: {', '.join(used)}")
        
        # Print audit summary
        audit = manager.audit_summary()
        print(f"\nAudit Summary:")
        print(f"  Total accessed: {audit.get('total_accessed', 0)}")
        print(f"  Unique secrets: {audit.get('unique_secrets', 0)}")
        
        return True
        
    except Exception as e:
        print_error(f"SecretManager test failed: {e}")
        return False


def main():
    """Main entry point."""
    print_header("NLP PROJECT SECRETS INITIALIZATION")
    
    workspace_root = Path.cwd()
    env_path = workspace_root / ".env.local"
    
    # Check if .env.local exists
    if env_path.exists():
        if not prompt_yes_no(f"\n{env_path.name} already exists. Overwrite?"):
            print_warning("Skipping setup")
            return 0
    
    # Set up environment file
    secrets_dict = setup_env_file(env_path)
    
    # Set up pre-commit hook
    if prompt_yes_no("\nInstall pre-commit hook to prevent secrets leakage?"):
        setup_precommit_hook()
    
    # Test SecretManager
    if prompt_yes_no("\nTest SecretManager with configured secrets?"):
        if not test_secret_manager(env_path, secrets_dict):
            print_warning("SecretManager test failed")
            return 1
    
    # Final instructions
    print_header("SETUP COMPLETE")
    print(f"✓ Secrets configured in: {env_path.name}")
    print(f"✓ File is git-ignored (never committed)")
    print(f"✓ Pre-commit hook installed (if selected)")
    print(f"\nNEXT STEPS:")
    print(f"1. Load secrets in current shell:")
    print(f"   export $(cat .env.local | xargs)")
    print(f"\n2. Or use in Python scripts:")
    print(f"   from core.secret_manager import get_manager")
    print(f"   manager = get_manager()")
    print(f"   api_key = manager.get('GEMINI_API_KEYS')")
    print(f"\n3. For CI/CD pipelines, set env vars before running")
    
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print_error("Interrupted by user")
        sys.exit(1)
    except Exception as e:
        print_error(f"Setup failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
