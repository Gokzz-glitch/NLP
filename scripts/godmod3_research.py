import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from urllib import error, request


def _request_json(method: str, url: str, payload=None, headers=None):
    data = None
    req_headers = {"Content-Type": "application/json"}
    if headers:
        req_headers.update(headers)

    if payload is not None:
        data = json.dumps(payload).encode("utf-8")

    req = request.Request(url=url, data=data, headers=req_headers, method=method)
    try:
        with request.urlopen(req, timeout=30) as resp:
            raw = resp.read().decode("utf-8")
            return resp.status, json.loads(raw) if raw else {}
    except error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        try:
            return exc.code, json.loads(body)
        except Exception:
            return exc.code, {"error": body}


def check_connection(base_url: str, godmode_key: str):
    health_status, health = _request_json("GET", f"{base_url}/v1/health")
    if health_status != 200:
        return False, {"stage": "health", "status": health_status, "details": health}

    tier_headers = {"Authorization": f"Bearer {godmode_key}"}
    tier_status, tier = _request_json("GET", f"{base_url}/v1/tier", headers=tier_headers)
    if tier_status != 200:
        return False, {"stage": "tier", "status": tier_status, "details": tier}

    return True, {"health": health, "tier": tier}


def run_research_query(base_url: str, godmode_key: str, openrouter_key: str, model: str, query: str):
    headers = {"Authorization": f"Bearer {godmode_key}"}
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": query}],
    }
    if openrouter_key:
        payload["openrouter_api_key"] = openrouter_key

    status, result = _request_json("POST", f"{base_url}/v1/chat/completions", payload=payload, headers=headers)
    return status, result


def save_result(query: str, result: dict):
    out_dir = Path("g:/My Drive/NLP/logs/research")
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_path = out_dir / f"godmod3_research_{ts}.json"
    out_path.write_text(json.dumps({"query": query, "result": result}, indent=2), encoding="utf-8")
    return str(out_path)


def _default_research_mode() -> str:
    mode = os.getenv("GODMODE_RESEARCH_MODE", "classic").strip().lower()
    return mode if mode in {"classic", "ultraplinian"} else "classic"


def _default_model_for_mode(mode: str) -> str:
    if mode == "classic":
        return os.getenv("GODMODE_CLASSIC_MODEL", "openai/gpt-4o").strip()
    return os.getenv("GODMODE_MODEL", "ultraplinian/fast").strip()


def main():
    parser = argparse.ArgumentParser(description="Connect and query local G0DM0D3 for research")
    parser.add_argument("--query", type=str, help="Research question to send")
    parser.add_argument("--mode", type=str, choices=["classic", "ultraplinian"], default=_default_research_mode())
    parser.add_argument("--model", type=str, default="", help="Explicit model override; default depends on --mode")
    parser.add_argument("--base-url", type=str, default=os.getenv("GODMODE_BASE_URL", "http://127.0.0.1:7860"))
    parser.add_argument("--check-only", action="store_true", help="Only verify health+tier connectivity")
    parser.add_argument("--save", action="store_true", help="Save full response JSON to logs/research")
    args = parser.parse_args()

    selected_model = args.model.strip() or _default_model_for_mode(args.mode)

    godmode_key = os.getenv("GODMODE_API_KEY") or os.getenv("GODMODE_KEY")
    openrouter_key = os.getenv("OPENROUTER_API_KEY")

    if not godmode_key:
        print("ERROR: Missing GODMODE_API_KEY in environment")
        sys.exit(1)

    try:
        ok, details = check_connection(args.base_url.rstrip("/"), godmode_key)
    except Exception as exc:
        print(f"SKIP: Godmod3 endpoint unavailable ({exc})")
        sys.exit(0)

    if not ok:
        print(f"SKIP: Godmod3 connection check failed at {details.get('stage')} (status={details.get('status')})")
        print(json.dumps(details.get("details", {}), indent=2))
        sys.exit(0)

    tier = details["tier"]
    print(
        f"CONNECTED: tier={tier.get('tier')} | "
        f"research_access={tier.get('features', {}).get('research_access')} | "
        f"mode={args.mode} | model={selected_model}"
    )

    if args.check_only:
        return

    if not args.query:
        print("ERROR: --query is required unless --check-only is used")
        sys.exit(1)

    status, result = run_research_query(
        base_url=args.base_url.rstrip("/"),
        godmode_key=godmode_key,
        openrouter_key=openrouter_key,
        model=selected_model,
        query=args.query,
    )

    if status != 200:
        print(f"ERROR: Research request failed (status={status})")
        print(json.dumps(result, indent=2))
        err = result.get("error", {}) if isinstance(result, dict) else {}
        code = err.get("code") if isinstance(err, dict) else None
        if (status == 500 or code == "missing_api_key") and not openrouter_key:
            print("HINT: Set OPENROUTER_API_KEY in your shell before running this command.")
            print("HINT: Example (PowerShell): $env:OPENROUTER_API_KEY='sk-or-v1-...'")
        sys.exit(1)

    content = (
        result.get("choices", [{}])[0]
        .get("message", {})
        .get("content", "")
    )
    print("RESEARCH RESULT:\n")
    print(content)

    if args.save:
        path = save_result(args.query, result)
        print(f"\nSAVED: {path}")


if __name__ == "__main__":
    main()
