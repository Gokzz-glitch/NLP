"""HTTPS/TLS Security Configuration for FastAPI"""

import os
import ssl
from pathlib import Path


class TLSConfig:
    """Manage HTTPS/TLS configuration for FastAPI endpoints."""
    
    def __init__(self):
        self.use_https = os.getenv("API_USE_HTTPS", "true").lower() in {"1", "true", "yes"}
        self.cert_path = os.getenv("API_TLS_CERT_PATH", "").strip()
        self.key_path = os.getenv("API_TLS_KEY_PATH", "").strip()
        self.require_https = os.getenv("API_REQUIRE_HTTPS_REDIRECT", "true").lower() in {"1", "true", "yes"}
        
    def validate(self) -> None:
        """Validate TLS configuration if HTTPS is enabled."""
        if not self.use_https:
            return  # HTTP-only mode (development only)
        
        if not self.cert_path or not self.key_path:
            raise RuntimeError(
                "API_USE_HTTPS=true but certificate paths not provided. "
                "Set API_TLS_CERT_PATH and API_TLS_KEY_PATH or set API_USE_HTTPS=false"
            )
        
        if not Path(self.cert_path).exists():
            raise FileNotFoundError(f"TLS certificate not found: {self.cert_path}")
        if not Path(self.key_path).exists():
            raise FileNotFoundError(f"TLS key not found: {self.key_path}")
    
    def get_ssl_context(self):
        """Get SSL/TLS context for uvicorn server."""
        if not self.use_https:
            return None
        
        self.validate()
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.load_cert_chain(self.cert_path, self.key_path)
        # Enforce TLS 1.2+
        ctx.options |= ssl.OP_NO_TLSv1 | ssl.OP_NO_TLSv1_1
        return ctx
    
    def get_redirect_middleware_config(self):
        """Get HTTPS redirect middleware configuration."""
        if not self.require_https:
            return None
        
        return {
            "enabled": True,
            "code": 301,  # Permanent redirect
        }


# V020 FIX: Middleware to enforce HTTPS
def https_redirect_middleware(app):
    """Add middleware to redirect HTTP to HTTPS."""
    from fastapi.middleware.httpsredirect import HTTPSRedirectMiddleware
    
    config = TLSConfig()
    if config.require_https and config.use_https:
        app.add_middleware(HTTPSRedirectMiddleware)
    return app
