#!/usr/bin/env python3
"""Auto-commit and push repository changes on a fixed interval."""

from __future__ import annotations

import argparse
import logging
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Optional, Tuple


def configure_logging(log_file: Path) -> None:
    log_file.parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | [GIT_PUSH_AGENT] %(message)s",
        handlers=[
            logging.FileHandler(log_file, encoding="utf-8"),
            logging.StreamHandler(sys.stdout),
        ],
    )


def run_git(repo_root: Path, *args: str) -> Tuple[int, str, str]:
    proc = subprocess.run(
        ["git", "-C", str(repo_root), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    return proc.returncode, proc.stdout.strip(), proc.stderr.strip()


def ensure_git_repo(repo_root: Path) -> None:
    code, out, err = run_git(repo_root, "rev-parse", "--is-inside-work-tree")
    if code != 0 or out.lower() != "true":
        raise RuntimeError(f"Not a git repository: {repo_root}\n{err}")


def get_current_branch(repo_root: Path) -> str:
    code, out, _ = run_git(repo_root, "rev-parse", "--abbrev-ref", "HEAD")
    if code != 0 or not out:
        return "main"
    return out


def get_changes(repo_root: Path) -> str:
    code, out, err = run_git(repo_root, "status", "--porcelain")
    if code != 0:
        raise RuntimeError(f"Failed to read git status: {err}")
    return out


def push_once(repo_root: Path, message_prefix: str) -> None:
    changes = get_changes(repo_root)
    if not changes:
        logging.info("No changes detected. Skipping commit/push.")
        return

    logging.info("Changes detected. Preparing commit.")

    code, _, err = run_git(repo_root, "add", "-A")
    if code != 0:
        raise RuntimeError(f"git add failed: {err}")

    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    commit_message = f"{message_prefix} {timestamp}"

    code, out, err = run_git(repo_root, "commit", "-m", commit_message)
    if code != 0:
        if "nothing to commit" in (out + "\n" + err).lower():
            logging.info("Nothing to commit after staging. Skipping push.")
            return
        raise RuntimeError(f"git commit failed: {err or out}")

    logging.info("Commit created: %s", commit_message)

    branch = get_current_branch(repo_root)
    code, out, err = run_git(repo_root, "push")
    if code != 0:
        logging.warning("git push failed. Retrying with upstream setup for branch '%s'.", branch)
        code2, out2, err2 = run_git(repo_root, "push", "-u", "origin", branch)
        if code2 != 0:
            raise RuntimeError(f"git push failed: {err or out}\nRetry failed: {err2 or out2}")

    logging.info("Push successful on branch '%s'.", branch)


def parse_args() -> argparse.Namespace:
    repo_default = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description="Auto-commit and push changes every N seconds.")
    parser.add_argument("--repo", default=str(repo_default), help="Repository root path")
    parser.add_argument("--interval-sec", type=int, default=3600, help="Push interval in seconds")
    parser.add_argument("--message-prefix", default="auto: hourly snapshot", help="Commit message prefix")
    parser.add_argument("--once", action="store_true", help="Run one commit/push cycle and exit")
    parser.add_argument(
        "--log-file",
        default=str(repo_default / "logs" / "git_hourly_push_agent.log"),
        help="Path to log file",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    repo_root = Path(args.repo).resolve()
    log_file = Path(args.log_file).resolve()

    configure_logging(log_file)
    logging.info("Starting git push agent | repo=%s | interval=%ss", repo_root, args.interval_sec)

    try:
        ensure_git_repo(repo_root)
    except Exception as exc:
        logging.error("Startup check failed: %s", exc)
        return 1

    while True:
        try:
            push_once(repo_root, args.message_prefix)
        except Exception as exc:
            logging.error("Push cycle failed: %s", exc)

        if args.once:
            logging.info("One-shot mode complete.")
            return 0

        logging.info("Sleeping for %s seconds.", args.interval_sec)
        time.sleep(max(10, args.interval_sec))


if __name__ == "__main__":
    raise SystemExit(main())
