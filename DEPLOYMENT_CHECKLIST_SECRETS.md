# Secrets Management Deployment Checklist

**Last Updated:** April 7, 2026  
**Status:** ✓ Implementation Complete

## Pre-Deployment Verification

### 1. Environment Setup
- [ ] Copy `.env.security.template` to `.env.local`
- [ ] Run `python scripts/init_secrets.py` to generate strong secrets
- [ ] Verify `.env.local` has mode 600: `ls -la .env.local`
- [ ] Load environment: `export $(cat .env.local | xargs)`
- [ ] Test: `python -c "from core.secret_manager import get_manager; get_manager().get_or_raise('CSRF_SECRET_KEY')"`

### 2. Code Validation
- [ ] Run `python scripts/verify_dont_leak_secrets.py` to check for hardcoded secrets
- [ ] Run `python scripts/audit_secrets.py --strict` to audit infrastructure
- [ ] All audit checks pass (0 errors, preferably 0 warnings)
- [ ] No `.env` files in git history: `git log --name-status | grep '.env'` (should be empty)

### 3. Git Configuration
- [ ] `.gitignore` includes `.env`, `*.key`, `*.pem`, `secrets/`
- [ ] Pre-commit hook installed: `cat .git/hooks/pre-commit | grep verify_dont_leak_secrets`
- [ ] Pre-commit hook is executable: `ls -la .git/hooks/pre-commit`
- [ ] Test pre-commit: Try to stage `.env.local` (should fail)

### 4. Secret Manager Health
- [ ] Required secrets configured (CSRF_SECRET_KEY, DASHBOARD_SECRET_KEY, LEDGER_HMAC_KEY)
- [ ] Optional secrets configured for enabled features:
  - [ ] GPU override: GPU_OVERRIDE_PASSWORD
  - [ ] Gemini: GEMINI_API_KEYS
  - [ ] Roboflow: ROBOFLOW_API_KEY
  - [ ] Payment: RAZORPAY_KEY_* (if using payments)
  - [ ] Ingest/WebSocket auth: INGEST_HMAC_SECRET, API_BRIDGE_AUTH_TOKEN, ORCHESTRATOR_AUTH_TOKEN
  - [ ] Fleet halt control: FLEET_HALT_TOKEN
- [ ] Test manager: `python scripts/init_secrets.py --test` passes

### 5. File Permissions
- [ ] `.env.local` mode: 600 (rw-------)
- [ ] `scripts/verify_dont_leak_secrets.py` is executable
- [ ] `scripts/init_secrets.py` is executable
- [ ] `scripts/audit_secrets.py` is executable

### 6. Dependency Integration
- [ ] All deprecated secret access removed from codebase
- [ ] All modules use `SecretManager.get()` or `get_manager()`
- [ ] No hardcoded defaults for secrets (fail-fast on missing)
- [ ] Payloads/responses never log secret values

## Deployment Steps

### Local Development
```bash
# 1. Set up secrets
python scripts/init_secrets.py

# 2. Load environment
export $(cat .env.local | xargs)

# 3. Run application
python app.py

# 4. Audit on commit
git add .
# (pre-commit hook runs automatically)
```

### Docker Deployment
```dockerfile
# Pass secrets via environment variables
FROM python:3.11
WORKDIR /app
COPY . .

# These come from build args or secrets, never hardcoded
ARG CSRF_SECRET_KEY
ARG DASHBOARD_SECRET_KEY
ARG GEMINI_API_KEYS

ENV CSRF_SECRET_KEY=${CSRF_SECRET_KEY}
ENV DASHBOARD_SECRET_KEY=${DASHBOARD_SECRET_KEY}
ENV GEMINI_API_KEYS=${GEMINI_API_KEYS}

# ... rest of Dockerfile
```

Run with:
```bash
docker build \
  --build-arg CSRF_SECRET_KEY="$(cat .env.local | grep CSRF)" \
  --build-arg DASHBOARD_SECRET_KEY="$(cat .env.local | grep DASHBOARD)" \
  --build-arg GEMINI_API_KEYS="$(cat .env.local | grep GEMINI)" \
  -t nlp-app .
```

### Kubernetes Deployment
```yaml
# 1. Create secret from .env.local
kubectl create secret generic nlp-secrets --from-env-file=.env.local

# 2. Reference in Pod spec
apiVersion: v1
kind: Pod
metadata:
  name: nlp-app
spec:
  containers:
  - name: app
    image: nlp-app:latest
    envFrom:
    - secretRef:
        name: nlp-secrets
```

### CI/CD Pipeline (GitHub Actions)
```yaml
# .github/workflows/deploy.yml
name: Deploy to Production

on: [push]

jobs:
  deploy:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      
      - name: Load secrets
        env:
          CSRF_SECRET_KEY: ${{ secrets.CSRF_SECRET_KEY }}
          DASHBOARD_SECRET_KEY: ${{ secrets.DASHBOARD_SECRET_KEY }}
          GEMINI_API_KEYS: ${{ secrets.GEMINI_API_KEYS }}
        run: |
          # SecretManager picks these up from environment
          python app.py
```

## Security Verification Checklist

### Before Going Live
- [ ] No `.env` files visible in repository
- [ ] `.env.local` is git-ignored
- [ ] Pre-commit hook prevents accidental pushes
- [ ] Audit shows 0 errors
- [ ] All required secrets configured
- [ ] SecretManager validated in target environment
- [ ] Logs don't contain secret values (audit)
- [ ] API keys have appropriate scope/permissions
- [ ] TLS/HTTPS enabled if API_USE_HTTPS=true

### Ongoing Maintenance
- [ ] Check audit weekly: `python scripts/audit_secrets.py`
- [ ] Rotate API keys every 90 days
- [ ] Review access audit: `SecretManager.audit_summary()`
- [ ] Monitor for unauthorized access attempts
- [ ] Update .env.security.template with new required secrets
- [ ] Document where each secret comes from

## Troubleshooting

### Issue: Pre-commit hook not running
```bash
# Check hook exists and is executable
ls -la .git/hooks/pre-commit

# Reinstall
python scripts/init_secrets.py
```

### Issue: Secret not found at runtime
```bash
# Check environment
echo $CSRF_SECRET_KEY

# Check .env.local exists
cat .env.local | head

# Reload environment
export $(cat .env.local | xargs)
python app.py
```

### Issue: Accidentally committed a secret
```bash
# 1. Rotate the secret immediately
# 2. Remove from .env.local and .git/config
# 3. Rewrite history (if possible)
git filter-branch --tree-filter 'rm .env.local' HEAD
# OR (safer)
git reset HEAD~1  # Undo last commit
rm .env.local
git add -A
git commit -m "Remove secrets"
```

### Issue: Permission denied on .env.local
```bash
# Fix permissions
chmod 600 .env.local

# Verify
ls -la .env.local  # Should show: -rw------- 1 user group ...
```

## File Inventory

| File | Purpose | Git | Mode | Required |
|------|---------|-----|------|----------|
| `.env.local` | Local secrets (dev) | ✗ | 600 | ✓ |
| `.env.security.template` | Template/reference | ✓ | 644 | ✓ |
| `scripts/verify_dont_leak_secrets.py` | Pre-commit hook | ✓ | 755 | ✓ |
| `scripts/init_secrets.py` | Setup wizard | ✓ | 755 | ✓ |
| `scripts/audit_secrets.py` | Security audit | ✓ | 755 | ✓ |
| `core/secret_manager.py` | Manager impl | ✓ | 644 | ✓ |
| `SECRETS_MANAGEMENT.md` | Documentation | ✓ | 644 | ✓ |
| `.gitignore` | Ignore rules | ✓ | 644 | ✓ |

## Success Criteria

✓ All required secrets are environment-based (no hardcoded defaults)  
✓ `.env` files are git-ignored and never committed  
✓ Pre-commit hook prevents accidental leakage  
✓ SecretManager enforces validation (format, length, strength)  
✓ Audit logging tracks which secrets are accessed  
✓ All modules use centralized SecretManager  
✓ Deployment pipelines pass secrets securely  
✓ Security audit shows 0 errors  

---

**Ready for Deployment:** ✓ Yes
