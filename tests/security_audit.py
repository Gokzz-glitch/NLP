# tests/security_audit.py
import requests
import json
import sys

BASE_URL = "http://localhost:5555"
MASTER_KEY = "3407bfca-5371-4cb3-b71b-4fbafa81cc6b" # Placeholder for testing

def test_api_unauthorized():
    """Verify 401 on missing/invalid token"""
    print("ST-01: Probing Unauthorized Access...", end=" ")
    res = requests.get(f"{BASE_URL}/api/agents")
    if res.status_code == 401:
        print("PASS")
    else:
        print(f"FAIL (Got {res.status_code})")

def test_csrf_bypass():
    """Verify 403 on missing CSRF token for POST"""
    print("ST-02: Probing CSRF Protection...", end=" ")
    headers = {"Authorization": f"Bearer {MASTER_KEY}"}
    res = requests.post(f"{BASE_URL}/api/sos/cancel", headers=headers)
    if res.status_code == 403:
        print("PASS")
    else:
        print(f"FAIL (Got {res.status_code} - Expected 403)")

def test_xss_injection():
    """Verify finding content is sanitized or escaped (Logic level)"""
    print("ST-03: Probing XSS Sanitization...", end=" ")
    # This probes the API response to see if stored <script> remains unchanged
    # (Actual rendering is frontend, but backend must not encourage it)
    # We simulate an agent posting raw HTML/JS
    # In Edge-Sentinel, AgentBus already scrubs before ledger, let's verify.
    pass

if __name__ == "__main__":
    print("--- Edge-Sentinel: Professional Security Audit ---")
    try:
        test_api_unauthorized()
        test_csrf_bypass()
        print("--- Audit Complete ---")
    except Exception as e:
        print(f"ERROR: Could not reach Master API. Is dashboard_api.py running? ({e})")
