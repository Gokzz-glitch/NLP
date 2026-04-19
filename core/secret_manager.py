"""
Centralized Secure Secrets Management System
=============================================

This module provides secure handling of all API keys, credentials, and sensitive data.
All secrets MUST be provided via environment variables; no hardcoded defaults.

Usage:
    from core.secret_manager import SecretManager
    sm = SecretManager()
    api_key = sm.get("GEMINI_API_KEY", required=True)
"""

import os
import secrets
import string
import logging
from pathlib import Path
from typing import Dict, List, Optional
from dotenv import load_dotenv

try:
    import keyring  # type: ignore
except Exception:  # pragma: no cover - optional dependency fallback
    keyring = None

logger = logging.getLogger(__name__)
load_dotenv()

KEYRING_SERVICE = "smartsalai-nlp"
SECURE_VAULT_PLACEHOLDERS = {"SECURE_VAULT_ACTIVE", "dummy-local-key"}

# All required secrets (environment variable names)
REQUIRED_SECRETS = {
    # Authentication & Security
    "CSRF_SECRET_KEY": {"description": "CSRF token secret", "min_length": 32},
    "DASHBOARD_SECRET_KEY": {"description": "Dashboard auth secret", "min_length": 32},
    "GPU_OVERRIDE_PASSWORD": {"description": "GPU override password", "min_length": 16},
    
    # Payment Gateway
    "RAZORPAY_KEY_ID": {"description": "Razorpay API key ID", "min_length": 10},
    "RAZORPAY_KEY_SECRET": {"description": "Razorpay API key secret", "min_length": 20},
    "RAZORPAY_WEBHOOK_SECRET": {"description": "Razorpay webhook secret", "min_length": 20},
    
    # Third-party APIs
    "GEMINI_API_KEY": {"description": "Google Gemini API key", "min_length": 10},
    "GEMINI_API_KEYS": {"description": "Comma-separated Gemini API keys", "min_length": 10},
    "ROBOFLOW_API_KEY": {"description": "Roboflow API key", "min_length": 10},
    
    # Encryption
    "FERNET_KEY": {"description": "Fernet encryption key", "min_length": 44},
    
    # TLS/HTTPS
    "API_TLS_CERT_PATH": {"description": "Path to TLS certificate", "min_length": 5},
    "API_TLS_KEY_PATH": {"description": "Path to TLS private key", "min_length": 5},
}

OPTIONAL_SECRETS = {
    "HF_TOKEN": {"description": "Hugging Face API token"},
    "HF_REPO_ID": {"description": "Hugging Face model repo ID"},
    "GODMODE_API_KEY": {"description": "G0DM0D3 API key"},
    "OPENROUTER_API_KEY": {"description": "OpenRouter API key"},
    "GITHUB_TOKEN": {"description": "GitHub personal access token"},
    "GITHUB_REPO": {"description": "GitHub repository (owner/repo)"},
    "INGEST_HMAC_SECRET": {"description": "Telemetry ingest HMAC secret"},
    "API_BRIDGE_AUTH_TOKEN": {"description": "API bridge WebSocket auth token"},
    "ORCHESTRATOR_AUTH_TOKEN": {"description": "Orchestrator WebSocket auth token"},
    "LEDGER_HMAC_KEY": {"description": "Knowledge ledger HMAC key"},
    "FLEET_HALT_TOKEN": {"description": "Global fleet halt authorization token"},
}


class SecretNotFoundError(RuntimeError):
    """Raised when a required secret is missing."""
    pass


class SecretValidationError(ValueError):
    """Raised when a secret fails validation."""
    pass


class SecretManager:
    """
    Centralized secrets manager with validation and audit logging.
    
    Features:
    - Enforce required secrets at startup
    - Validate secret format and strength
    - Audit access to sensitive data
    - No fallbacks or defaults for critical secrets
    """
    
    def __init__(self, strict_mode: bool = True):
        """
        Args:
            strict_mode: If True, missing required secrets raise errors immediately.
        """
        self.strict_mode = strict_mode
        self._accessed_secrets: Dict[str, int] = {}
        self._missing_secrets: List[str] = []
        self._audit_log = logger.getChild("audit")
        
        if strict_mode:
            self._validate_required_secrets()
    
    def _validate_required_secrets(self) -> None:
        """Validate that all required secrets are available and valid."""
        # For non-production: GPU_OVERRIDE_PASSWORD is optional
        # For production: RAZORPAY and HTTPS certs are optional
        # But CSRF and DASHBOARD are always required
        
        always_required = [
            "CSRF_SECRET_KEY",
            "DASHBOARD_SECRET_KEY",
        ]
        
        missing = []
        for secret_name in always_required:
            value = self._resolve_secret(secret_name)
            if not value:
                missing.append(secret_name)
        
        if missing:
            msg = f"Required secrets missing: {', '.join(missing)}. " \
                  "Set these environment variables before starting."
            raise RuntimeError(msg)
        
        # Validate formats
        for secret_name in always_required:
            self._validate_secret(secret_name)
        
        logger.info("✓ All required secrets validated")
    
    def _validate_secret(self, secret_name: str, value: Optional[str] = None) -> None:
        """Validate a secret's format and strength."""
        if value is None:
            value = self._resolve_secret(secret_name)
        
        if not value:
            return  # Skip validation for missing optional secrets
        
        spec = REQUIRED_SECRETS.get(secret_name) or OPTIONAL_SECRETS.get(secret_name)
        if not spec:
            return  # Unknown secret, skip validation
        
        min_len = spec.get("min_length", 0)
        if len(value) < min_len:
            raise SecretValidationError(
                f"{secret_name} is too short ({len(value)} chars, need {min_len})"
            )

    def _resolve_secret(self, secret_name: str) -> str:
        """Resolve secret from env first, then OS keyring for placeholder values."""
        value = os.getenv(secret_name, "").strip()

        if value and value not in SECURE_VAULT_PLACEHOLDERS:
            return value

        if keyring is None:
            return ""

        try:
            vault_value = keyring.get_password(KEYRING_SERVICE, secret_name) or ""
            return vault_value.strip()
        except Exception as exc:
            logger.debug("Keyring read failed for %s: %s", secret_name, exc)
            return ""
    
    def get(self, secret_name: str, required: bool = False) -> str:
        """
        Retrieve a secret from environment.
        
        Args:
            secret_name: Name of the secret (env var name)
            required: If True, raises error if not found
        
        Returns:
            Secret value or empty string if not found and not required
        
        Raises:
            SecretNotFoundError: If required=True and secret not found
        """
        value = self._resolve_secret(secret_name)
        
        if not value:
            if required:
                raise SecretNotFoundError(
                    f"Required secret not found: {secret_name}. "
                    f"Set {secret_name} in environment."
                )
            return ""
        
        # Validate
        try:
            self._validate_secret(secret_name, value)
        except SecretValidationError as e:
            logger.error(f"Secret validation failed for {secret_name}: {e}")
            if required:
                raise
            return ""
        
        # Audit access
        self._accessed_secrets[secret_name] = self._accessed_secrets.get(secret_name, 0) + 1
        self._audit_log.debug(f"Accessed secret: {secret_name}")
        
        return value
    
    def get_or_raise(self, secret_name: str) -> str:
        """Get secret or raise error if not found."""
        return self.get(secret_name, required=True)
    
    def get_multiple(self, secret_names: List[str], required: bool = False) -> Dict[str, str]:
        """Get multiple secrets at once."""
        return {name: self.get(name, required=required) for name in secret_names}
    
    def list_missing(self) -> List[str]:
        """List all missing required secrets."""
        missing = []
        for secret_name in REQUIRED_SECRETS:
            if not os.getenv(secret_name, "").strip():
                missing.append(secret_name)
        return missing
    
    def audit_summary(self) -> Dict:
        """Return audit summary of secret access."""
        return {
            "total_accessed": sum(self._accessed_secrets.values()),
            "unique_secrets": len(self._accessed_secrets),
            "access_counts": dict(self._accessed_secrets),
        }


def get_secret(key_name: str, default: str = None) -> str:
    """
    Legacy compatibility function. 
    
    DEPRECATED: Use SecretManager instead.
    This function is kept for backwards compatibility only.
    """
    logger.warning(
        f"get_secret() is deprecated. Use SecretManager().get('{key_name}') instead."
    )
    
    # Special handling for DASHBOARD_SECRET_KEY (legacy)
    if key_name == "DASHBOARD_SECRET_KEY":
        value = get_manager(strict_mode=False).get(key_name, required=False)
        if value:
            return value
        
        # Try legacy .dashboard_secret file
        secret_file = Path(".dashboard_secret")
        if secret_file.exists():
            with open(secret_file, "r") as f:
                value = f.read().strip()
                if value:
                    logger.warning(
                        f"Using legacy {secret_file}. "
                        "Please set DASHBOARD_SECRET_KEY in .env instead."
                    )
                    return value
        
        # If still not found, error out
        raise RuntimeError(
            f"Required secret not found: {key_name}. "
            "Please set DASHBOARD_SECRET_KEY in environment."
        )
    
    # For other secrets, use SecretManager
    sm = SecretManager(strict_mode=False)
    return sm.get(key_name, required=False) or default


def set_secret(key_name: str, value: str, sync_env: bool = True) -> None:
    """Store a secret in OS keyring and optionally mark env as vault-backed."""
    if not key_name:
        raise ValueError("key_name is required")
    if not value:
        raise ValueError(f"Cannot store empty secret for {key_name}")
    if keyring is None:
        raise RuntimeError("keyring package is unavailable; install keyring to store secrets")

    keyring.set_password(KEYRING_SERVICE, key_name, value)
    if sync_env:
        os.environ[key_name] = "SECURE_VAULT_ACTIVE"


# Global instance for convenient access
_global_manager: Optional[SecretManager] = None


def get_manager(strict_mode: bool = True) -> SecretManager:
    """Get or create the global SecretManager instance."""
    global _global_manager
    if _global_manager is None:
        _global_manager = SecretManager(strict_mode=strict_mode)
    return _global_manager
