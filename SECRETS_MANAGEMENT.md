# Secrets Management Infrastructure

## Overview

All API keys, credentials, and sensitive data are now managed through a centralized `SecretManager` system that:

- ✓ Enforces environment variables (no hardcoded defaults)  
- ✓ Validates secret format and strength
- ✓ Provides audit logging of secret access
- ✓ Fails fast if required secrets are missing
- ✓ Supports multiple third-party APIs

## Required Secrets

### Core Security (Always Required)
- **CSRF_SECRET_KEY** (min 32 chars) — CSRF token generation
- **DASHBOARD_SECRET_KEY** (min 32 chars) — Dashboard authentication
- **LEDGER_HMAC_KEY** (min 32 chars) — Knowledge ledger HMAC signing key

### Optional but Recommended
- **GPU_OVERRIDE_PASSWORD** (min 16 chars) — GPU resource control
- **API_USE_HTTPS** — Enable HTTPS enforcement
- **API_TLS_CERT_PATH** — Path to TLS certificate
- **API_TLS_KEY_PATH** — Path to TLS private key
- **INGEST_HMAC_SECRET** — HMAC key for telemetry ingest
- **API_BRIDGE_AUTH_TOKEN** — WebSocket auth token for API bridge
- **ORCHESTRATOR_AUTH_TOKEN** — WebSocket auth token for Macha orchestrator
- **FLEET_HALT_TOKEN** — Authorization token for global halt endpoint

### Payment Processing (If using Razorpay)
- **RAZORPAY_KEY_ID** — Razorpay account key ID
- **RAZORPAY_KEY_SECRET** — Razorpay account secret
- **RAZORPAY_WEBHOOK_SECRET** — Webhook signature verification

### AI/ML APIs
- **GEMINI_API_KEY** — Google Gemini single API key
- **GEMINI_API_KEYS** — Comma-separated Gemini API keys (for failover)
- **ROBOFLOW_API_KEY** — Roboflow dataset management

### Encryption
- **FERNET_KEY** — Fernet symmetric encryption key (44 chars base64)

### Optional Cloud Services
- **HF_TOKEN** — Hugging Face API token
- **HF_REPO_ID** — Hugging Face model repository
- **GITHUB_TOKEN** — GitHub personal access token
- **GITHUB_REPO** — GitHub repository (owner/repo)

## Setup Instructions

### 1. Create .env File

```bash
# Copy the template
cp .env.security.template .env.local

# Edit with your actual secrets
editor .env.local

# Load into current shell
export $(cat .env.local | xargs)
```

### 2. Generate Strong Secrets

```bash
# CSRF_SECRET_KEY (32 chars)
python -c "import secrets; print(secrets.token_urlsafe(24))"

# DASHBOARD_SECRET_KEY (32 chars)
python -c "import secrets; print(secrets.token_urlsafe(24))"

# GPU_OVERRIDE_PASSWORD (16+ chars)
python -c "import secrets; print(secrets.token_urlsafe(12))"

# FERNET_KEY (automatically compatible)
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

### 3. Verify Secrets Are Loaded

```python
from core.secret_manager import get_manager

sm = get_manager()
print(sm.audit_summary())
```

## Usage in Code

### Option 1: Using SecretManager Directly (Recommended)

```python
from core.secret_manager import get_manager

# Get global manager instance
sm = get_manager()

# Get optional secret (returns empty string if not found)
api_key = sm.get("GEMINI_API_KEY")

# Get required secret (raises error if not found)
csrf_secret = sm.get_or_raise("CSRF_SECRET_KEY")

# Get multiple secrets at once
secrets = sm.get_multiple(["GEMINI_API_KEY", "ROBOFLOW_API_KEY"])
```

### Option 2: Using Specific Getters

```python
# Each service/component imports its own
from core.secret_manager import get_manager

class MyComponent:
    def __init__(self):
        sm = get_manager(strict_mode=False)
        self.api_key = sm.get("MYSERVICE_API_KEY")
        if not self.api_key:
            logger.warning("MYSERVICE_API_KEY not configured")
```

## Security Best Practices

### 1. Never Commit Secrets
- `.env` and `.env.local` are gitignored
- `.env.security.template` shows the structure only
- Use `verify_dont_leak_secrets.py` pre-commit hook

### 2. Rotate Credentials Regularly
- Use SecretManager to audit access: `sm.audit_summary()`
- Implement API key versioning (v1, v2, etc.)
- Use Razorpay's key rotation features

### 3. Validate Secret Strength
- Minimum lengths enforced by SecretManager
- Cryptographic randomness required
- No sequential or predictable values

### 4. Audit Access
```python
sm = get_manager()
audit = sm.audit_summary()
# Output:
# {
#     'total_accessed': 127,
#     'unique_secrets': 8,
#     'access_counts': {'GEMINI_API_KEY': 45, ...}
# }
```

## Key File Updates

The following files have been migrated to use SecretManager:

| File | API Key | Status |
|------|---------|--------|
| `agents/learner_agent.py` | GEMINI_API_KEYS | ✓ Updated |
| `agents/gen_voice.py` | GEMINI_API_KEY | ✓ Updated |
| `agents/driver_companion_agent.py` | GEMINI_API_KEY | ✓ Updated |
| `agents/active_learning_agent.py` | ROBOFLOW_API_KEY | ✓ Updated |
| `agents/api_bridge.py` | FERNET_KEY | ✓ Updated |
| `agents/ble_mesh_broker.py` | FERNET_KEY | ✓ Updated |
| `core/payment_gateway.py` | RAZORPAY_* | ✓ Updated |
| `core/tls_config.py` | API_TLS_* | ✓ Updated |
| `dashboard_api.py` | CSRF_SECRET_KEY | ✓ Updated |

## Troubleshooting

### Missing Secret Error
```
RuntimeError: Required secret not found: CSRF_SECRET_KEY
```
**Solution:** Set the environment variable before starting:
```bash
export CSRF_SECRET_KEY="your-secret-here"
```

### Secret Too Short Error
```
SecretValidationError: CSRF_SECRET_KEY is too short (10 chars, need 32)
```
**Solution:** Use a longer secret (min 32 characters):
```bash
export CSRF_SECRET_KEY="$(python -c 'import secrets; print(secrets.token_urlsafe(24))')"
```

### API Key Failing
**Check:** Is the secret properly formatted?
- Gemini: Usually starts with "AIza"
- Roboflow: Alpha-numeric key
- Razorpay: "rzp_test_" or "rzp_live_" prefix

## Integration with Deployment

### Docker
```dockerfile
# Pass secrets via environment variables
ENV CSRF_SECRET_KEY=${CSRF_SECRET_KEY}
ENV DASHBOARD_SECRET_KEY=${DASHBOARD_SECRET_KEY}
ENV GEMINI_API_KEYS=${GEMINI_API_KEYS}
```

### Kubernetes
```yaml
apiVersion: v1
kind: Secret
metadata:
  name: nlp-secrets
type: Opaque
stringData:
  CSRF_SECRET_KEY: "${CSRF_SECRET_KEY}"
  DASHBOARD_SECRET_KEY: "${DASHBOARD_SECRET_KEY}"
---
env:
  - name: CSRF_SECRET_KEY
    valueFrom:
      secretKeyRef:
        name: nlp-secrets
        key: CSRF_SECRET_KEY
```

### GitHub Secrets
```yaml
# .github/workflows/deploy.yml
env:
  CSRF_SECRET_KEY: ${{ secrets.CSRF_SECRET_KEY }}
  DASHBOARD_SECRET_KEY: ${{ secrets.DASHBOARD_SECRET_KEY }}
  GEMINI_API_KEYS: ${{ secrets.GEMINI_API_KEYS }}
```

## Audit & Compliance

### Access Logging
```python
import logging
logging.getLogger("core.secret_manager.audit").setLevel(logging.DEBUG)
# All secret access will be logged with timestamps
```

### HIPAA/GDPR Compliance
- Only required secrets are loaded
- Failed access attempts are logged
- Secrets are not cached in memory
- No plaintext logging of secret values

---

Generated: April 7, 2026
