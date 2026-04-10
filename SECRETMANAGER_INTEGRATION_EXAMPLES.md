# SecretManager Integration Examples

Complete working examples showing how to use `SecretManager` in different contexts.

## 1. Basic Module Integration

### Pattern: Optional API (with graceful fallback)

```python
from core.secret_manager import get_manager

class MyService:
    def __init__(self):
        sm = get_manager()
        
        # Get optional secret, defaults to empty string
        self.api_key = sm.get("MYSERVICE_API_KEY")
        
        if not self.api_key:
            self.enabled = False
            print("MyService disabled (MYSERVICE_API_KEY not configured)")
        else:
            self.enabled = True
    
    def request(self, endpoint: str):
        if not self.enabled:
            raise RuntimeError("MyService is not configured")
        
        # Use self.api_key
        return requests.get(
            f"https://api.myservice.com/{endpoint}",
            headers={"Authorization": f"Bearer {self.api_key}"}
        )
```

Usage:
```python
service = MyService()
if service.enabled:
    response = service.request("data")
```

---

## 2. Required Secrets (Fail Fast)

### Pattern: Core infrastructure secret

```python
from core.secret_manager import get_manager

class DashboardAuth:
    def __init__(self):
        sm = get_manager()
        
        # This will raise if not configured
        # Fail at startup, not at runtime
        self.secret_key = sm.get_or_raise("DASHBOARD_SECRET_KEY")
    
    def generate_session_token(self, user_id: str) -> str:
        import secrets
        token = secrets.token_urlsafe(32)
        # Sign with secret_key
        return self._sign(token)
```

Usage:
```python
# If DASHBOARD_SECRET_KEY is missing, this will crash immediately
# (which is the desired behavior for critical secrets)
auth = DashboardAuth()
```

---

## 3. Multiple Secrets with Failover

### Pattern: AI API with automatic fallback

```python
from core.secret_manager import get_manager
from typing import Optional

class GeminiClient:
    def __init__(self):
        sm = get_manager()
        
        # Get comma-separated keys for failover
        keys_str = sm.get("GEMINI_API_KEYS")
        if not keys_str:
            # Fallback to single key (deprecated)
            single_key = sm.get("GEMINI_API_KEY")
            self.api_keys = [single_key] if single_key else []
        else:
            self.api_keys = [k.strip() for k in keys_str.split(",")]
        
        self.current_index = 0
        self.failures = {}
    
    def _call_gemini(self, prompt: str) -> Optional[str]:
        """Call Gemini with automatic key rotation."""
        if not self.api_keys:
            raise RuntimeError("No Gemini API keys configured")
        
        for attempt in range(len(self.api_keys)):
            key = self.api_keys[self.current_index]
            
            try:
                response = requests.post(
                    "https://api.gemini.google.com/v1/text",
                    json={"prompt": prompt},
                    headers={"Authorization": f"Bearer {key}"}
                )
                
                if response.status_code == 401:
                    # Key is invalid, move to next
                    self.failures[key] = "Invalid API key"
                    self.current_index = (self.current_index + 1) % len(self.api_keys)
                    continue
                
                response.raise_for_status()
                return response.json().get("result")
            
            except Exception as e:
                self.failures[key] = str(e)
                self.current_index = (self.current_index + 1) % len(self.api_keys)
        
        raise RuntimeError(f"All Gemini API keys failed: {self.failures}")
```

Usage:
```python
client = GeminiClient()
result = client._call_gemini("What is a pothole?")
# If first key fails, automatically tries second, etc.
```

---

## 4. Encryption/Decryption

### Pattern: Fernet-based data protection

```python
from core.secret_manager import get_manager
from cryptography.fernet import Fernet
from typing import Optional

class DataEncryptor:
    def __init__(self):
        sm = get_manager()
        key = sm.get("FERNET_KEY")
        
        if not key:
            # Create ephemeral key for this session
            import cryptography.fernet
            self.cipher = Fernet(cryptography.fernet.Fernet.generate_key())
            self.persistent = False
        else:
            self.cipher = Fernet(key.encode())
            self.persistent = True
    
    def encrypt(self, plaintext: str) -> str:
        """Encrypt plaintext to ciphertext."""
        return self.cipher.encrypt(plaintext.encode()).decode()
    
    def decrypt(self, ciphertext: str) -> str:
        """Decrypt ciphertext to plaintext."""
        try:
            return self.cipher.decrypt(ciphertext.encode()).decode()
        except Exception as e:
            raise ValueError(f"Decryption failed: {e}")
```

Usage:
```python
encryptor = DataEncryptor()
encrypted = encryptor.encrypt("sensitive_data")
print(f"Encrypted: {encrypted}")

decrypted = encryptor.decrypt(encrypted)
print(f"Decrypted: {decrypted}")
```

---

## 5. Payment Gateway Integration

### Pattern: Razorpay with secure credential management

```python
from core.secret_manager import get_manager
from typing import Optional

class RazorpayGateway:
    def __init__(self):
        sm = get_manager()
        
        self.key_id = sm.get("RAZORPAY_KEY_ID")
        self.key_secret = sm.get("RAZORPAY_KEY_SECRET")
        self.webhook_secret = sm.get("RAZORPAY_WEBHOOK_SECRET")
        
        if not (self.key_id and self.key_secret):
            self.enabled = False
            print("Razorpay disabled (credentials not configured)")
        else:
            self.enabled = True
            # Initialize Razorpay client
            import razorpay
            self.client = razorpay.Client(
                auth=(self.key_id, self.key_secret)
            )
    
    def create_order(self, amount_paise: int, description: str):
        if not self.enabled:
            raise RuntimeError("Razorpay is not enabled")
        
        # Never log the secrets!
        order = self.client.order.create({
            "amount": amount_paise,
            "currency": "INR",
            "description": description,
        })
        
        return order
    
    def verify_webhook(self, webhook_body: bytes, signature: str) -> bool:
        """Verify webhook signature using webhook secret."""
        import hmac
        import hashlib
        
        expected_signature = hmac.new(
            self.webhook_secret.encode(),
            webhook_body,
            hashlib.sha256
        ).hexdigest()
        
        return hmac.compare_digest(expected_signature, signature)
```

Usage:
```python
gateway = RazorpayGateway()

if gateway.enabled:
    order = gateway.create_order(
        amount_paise=99999,  # ₹999.99
        description="Pothole Detection License"
    )
    print(f"Order ID: {order['id']}")
```

---

## 6. Cloud Service Authentication

### Pattern: AWS S3 bucket access

```python
from core.secret_manager import get_manager
from typing import Optional

class S3Storage:
    def __init__(self, bucket_name: str):
        sm = get_manager()
        
        # AWS credentials from environment
        self.access_key = sm.get("AWS_ACCESS_KEY_ID")
        self.secret_key = sm.get("AWS_SECRET_ACCESS_KEY")
        self.region = sm.get("AWS_REGION") or "us-east-1"
        
        if not (self.access_key and self.secret_key):
            # Will try to use IAM roles if deployed on AWS
            import boto3
            self.s3 = boto3.client("s3", region_name=self.region)
        else:
            import boto3
            self.s3 = boto3.client(
                "s3",
                aws_access_key_id=self.access_key,
                aws_secret_access_key=self.secret_key,
                region_name=self.region,
            )
        
        self.bucket = bucket_name
    
    def upload(self, key: str, data: bytes):
        """Upload data to S3."""
        self.s3.put_object(
            Bucket=self.bucket,
            Key=key,
            Body=data,
        )
    
    def download(self, key: str) -> Optional[bytes]:
        """Download data from S3."""
        try:
            response = self.s3.get_object(Bucket=self.bucket, Key=key)
            return response["Body"].read()
        except self.s3.exceptions.NoSuchKey:
            return None
```

Usage:
```python
storage = S3Storage("my-pothole-models")
storage.upload("model/v1.onnx", model_bytes)
data = storage.download("model/v1.onnx")
```

---

## 7. TLS/HTTPS Configuration

### Pattern: Secure API server setup

```python
from core.secret_manager import get_manager
from pathlib import Path
import ssl

class SecureAPIServer:
    def __init__(self, host: str = "0.0.0.0", port: int = 8443):
        sm = get_manager()
        
        self.use_https = sm.get("API_USE_HTTPS") == "true"
        self.host = host
        self.port = port
        
        if self.use_https:
            cert_path = sm.get("API_TLS_CERT_PATH")
            key_path = sm.get("API_TLS_KEY_PATH")
            
            if not (cert_path and key_path):
                raise ValueError(
                    "TLS enabled but cert/key paths not configured"
                )
            
            if not (Path(cert_path).exists() and Path(key_path).exists()):
                raise FileNotFoundError(
                    f"TLS certificates not found: {cert_path}, {key_path}"
                )
            
            self.ssl_context = ssl.create_default_context(
                ssl.Purpose.CLIENT_AUTH
            )
            self.ssl_context.load_cert_chain(cert_path, key_path)
        else:
            self.ssl_context = None
    
    def start(self, app):
        """Start the server with optional HTTPS."""
        if self.use_https:
            app.run(
                host=self.host,
                port=self.port,
                ssl_context=self.ssl_context,
            )
        else:
            app.run(host=self.host, port=self.port)
```

Usage:
```python
from flask import Flask

app = Flask(__name__)

@app.route("/health")
def health():
    return {"status": "ok"}

server = SecureAPIServer(port=8443)
server.start(app)
```

---

## 8. Testing with Mock Secrets

### Pattern: Unit tests with fixture secrets

```python
import pytest
from core.secret_manager import get_manager

@pytest.fixture
def mock_secrets(monkeypatch):
    """Fixture to override secrets in tests."""
    test_secrets = {
        "CSRF_SECRET_KEY": "test-csrf-" + "x" * 28,
        "DASHBOARD_SECRET_KEY": "test-dashboard-" + "x" * 23,
        "GEMINI_API_KEYS": "test-key-1,test-key-2",
    }
    
    # Override get() method
    original_get = get_manager().get
    
    def mock_get(key: str, default: str = ""):
        return test_secrets.get(key, default)
    
    monkeypatch.setattr(get_manager(), "get", mock_get)
    
    return test_secrets

def test_dashboard_auth(mock_secrets):
    """Test auth with mock secrets."""
    from myapp.auth import DashboardAuth
    
    auth = DashboardAuth()
    # Uses mock_secrets["DASHBOARD_SECRET_KEY"]
    token = auth.generate_session_token("user123")
    assert len(token) > 0

def test_gemini_client(mock_secrets):
    """Test Gemini client with mock secrets."""
    from myapp.ai import GeminiClient
    
    client = GeminiClient()
    # Uses mock_secrets["GEMINI_API_KEYS"]
    assert len(client.api_keys) == 2
```

Usage:
```bash
pytest tests/test_myapp.py -v
# All tests run with mocked secrets, never need real keys!
```

---

## 9. Logging/Audit

### Pattern: Secure logging that never logs secrets

```python
import logging
from core.secret_manager import get_manager

class AuditLogger:
    def __init__(self):
        self.logger = logging.getLogger("audit")
        sm = get_manager()
        
        # Get audit secret for signing logs
        self.audit_secret = sm.get("AUDIT_LOG_SECRET")
    
    def log_access(self, user_id: str, resource: str, action: str):
        """Log resource access without revealing secrets."""
        import hashlib
        import time
        
        timestamp = time.time()
        
        # Sign the log entry
        message = f"{user_id}:{resource}:{action}:{timestamp}"
        signature = hashlib.sha256(
            (message + self.audit_secret).encode()
        ).hexdigest()
        
        # Log only the signature and metadata, never the secret
        self.logger.info({
            "user": user_id,
            "resource": resource,
            "action": action,
            "timestamp": timestamp,
            "signature": signature[:16],  # First 16 chars
        })
```

Usage:
```python
audit = AuditLogger()
audit.log_access("user123", "model", "download")
# Logs: {"user": "user123", "resource": "model", ...}
# Never logs: actual API keys, passwords, etc.
```

---

## 10. Configuration-Based Selection

### Pattern: Feature flags with secrets

```python
from core.secret_manager import get_manager
from typing import Dict, Any

class FeatureManager:
    def __init__(self):
        sm = get_manager()
        
        self.features: Dict[str, Dict[str, Any]] = {
            "payment": {
                "enabled": bool(sm.get("RAZORPAY_KEY_ID")),
                "provider": "razorpay",
            },
            "ai": {
                "enabled": bool(sm.get("GEMINI_API_KEYS")),
                "provider": "gemini",
            },
            "encryption": {
                "enabled": bool(sm.get("FERNET_KEY")),
                "method": "fernet",
            },
            "https": {
                "enabled": sm.get("API_USE_HTTPS") == "true",
                "port": 8443,
            },
        }
    
    def is_enabled(self, feature: str) -> bool:
        """Check if feature is available."""
        return self.features.get(feature, {}).get("enabled", False)
    
    def get_config(self, feature: str) -> Dict[str, Any]:
        """Get feature configuration."""
        return self.features.get(feature, {})
```

Usage:
```python
features = FeatureManager()

if features.is_enabled("payment"):
    # Use Razorpay gateway
    gateway = RazorpayGateway()
else:
    # Use alternative payment method
    gateway = StripeGateway()

if features.is_enabled("https"):
    # Start server on 8443 with TLS
    server.start_secure()
else:
    # Start plain HTTP
    server.start()
```

---

## Best Practices Summary

1. **Use `get()` for optional**: Returns empty string if not found
2. **Use `get_or_raise()` for required**: Fails fast at startup
3. **Never log secrets**: Only log success/failure, not values
4. **Rotate regularly**: Especially long-lived API keys
5. **Validate format**: Long enough, proper encoding, right provider
6. **Test with mocks**: Never use real secrets in tests
7. **Encrypt sensitive data**: Use Fernet for at-rest encryption
8. **Audit access**: Log who accessed what secret and when
9. **Fail gracefully**: Disable features if secrets missing
10. **Document integration**: Show examples like these for maintainability
