"""
Agent 8 — SentinelGuardian (Conversation Director + Self-Healer)
=================================================================
Every 5 minutes:
        1. Asks a fixed real-world evaluator question directed at all other agents.
        2. Each agent reads it (via check_and_respond_to_broadcast()) and replies.
    3. Simultaneously monitors for agent health issues and resolves them.

Communication model uses the shared knowledge_ledger.db as the message bus:
  Agent8  → finding_type="broadcast_question"
        Agent1-14 → finding_type="broadcast_response"
"""

import asyncio
import json
import logging
import os
import sqlite3
import time
from datetime import datetime
from typing import Any, Dict, List, Optional

from core.knowledge_ledger import ledger
from agents.system_agents import BaseAgent

logger = logging.getLogger("Agent8-SentinelGuardian")

# ── Health thresholds ────────────────────────────────────────────────────────
AGENT_INTERVALS = {
    "Agent1-IndustryResearch": 30,
    "Agent2-ModelScout":       45,
    "Agent3-CodeOpt":          60,
    "Agent4-SSLLoop":          35,
    "Agent5-RAG":              40,
    "Agent6-DatasetBench":     50,
    "Agent7-GPUThermal":       10,
    "Agent9-ContextCurator":   55,
    "Agent10-CoordinationPlanner": 65,
    "Agent11-BenchmarkResearch": 30,
    "Agent12-DeploymentResearch": 32,
    "Agent13-DatasetResearch": 34,
    "Agent14-SafetyResearch": 36,
    "Agent15-SmokeTest": 38,
    "Agent16-RegressionTest": 40,
    "Agent17-PerformanceTest": 42,
    "Agent18-DataQualityTest": 44,
    "Agent19-APIContractTest": 46,
    "Agent20-UIResponsiveTest": 48,
    "Agent21-FailureInjectionTest": 50,
    "Agent22-SecuritySanityTest": 52,
    "Agent23-TrainingLoopTest": 54,
    "Agent24-TelemetryTest": 56,
    "Agent25-ReleaseReadinessTest": 58,
}
STALL_MULTIPLIER = 5
MAX_DB_KB        = 1_000

EVALUATOR_QUESTION = (
    "Rulebook-first review: evaluate this project out of 100 across all fields, "
    "but prioritize Rulebook.md requirements first. Cover offline functionality, "
    "open-source priority, low-network robustness, low-VRAM edge deployment, and "
    "global applicability. Compare it with previous innovations, say whether it is "
    "worth selecting, explain what is genuinely new, and then give the strongest "
    "possible rejection reasons if any remain."
)


class SentinelGuardian(BaseAgent):
    """Agent 8 — asks evaluator question every 5 minutes, heals issues, synthesises insights."""

    def __init__(self):
        super().__init__("Agent8-SentinelGuardian", sleep_interval=15)
        self._resolved_cache: Dict[str, float] = {}
        self._last_question_time: float = 0.0
        self._question_round: int = 0
        self._last_synthesis: float = 0.0
        self._question_interval_sec: int = int(os.getenv("SENTINEL_QUESTION_INTERVAL_SEC", "300"))
        self.db_path = os.path.join(
            os.path.dirname(os.path.dirname(__file__)), "knowledge_ledger.db"
        )

    async def run(self):
        logger.info("🛡️  [Agent8] SentinelGuardian online — directing conversation + healing")
        ledger.log_finding(self.name, "broadcast_question", {
            "round": 0,
            "question": "All agents — Sentinel Guardian is online. Who is ready? Reply with your status.",
            "asked_at": datetime.now().isoformat(),
        })
        while True:
            try:
                await self.iteration()
            except Exception as exc:
                logger.error(f"[Agent8] iteration error: {exc}")
            await asyncio.sleep(self.sleep_interval)

    async def iteration(self):
        now = time.time()
        tasks = [
            self._maybe_broadcast_question(now),
            self._check_stalls(now),
            self._check_gpu_stuck(now),
            self._check_db_size(now),
        ]
        if now - self._last_synthesis > 180:
            tasks.append(self._synthesise_cross_agent(now))
        await asyncio.gather(*tasks)

    # ── CONVERSATION: Broadcast question every 5 minutes ─────────────────────
    async def _maybe_broadcast_question(self, now: float):
        if now - self._last_question_time < self._question_interval_sec:
            return
        self._last_question_time = now
        self._question_round += 1

        question = self._craft_question(self._question_round)
        ledger.log_finding(self.name, "broadcast_question", {
            "round":    self._question_round,
            "question": question,
            "asked_at": datetime.now().isoformat(),
        })
        logger.info(f"[Agent8] 📢 Round {self._question_round} question: {question[:80]}…")

    def _craft_question(self, rnd: int) -> str:
        return EVALUATOR_QUESTION

    # ── HEALTH: Stalled agents ───────────────────────────────────────────────
    async def _check_stalls(self, now: float):
        for agent_id, interval in AGENT_INTERVALS.items():
            rows = ledger.get_findings(agent_name=agent_id, limit=1)
            elapsed = (now - self._parse_ts(rows[0]["timestamp"])) if rows else float("inf")
            threshold = interval * STALL_MULTIPLIER
            issue_key = f"stall:{agent_id}"
            if elapsed > threshold and self._can_fire(issue_key, now, 600):
                self._mark_resolved(issue_key, now)
                ledger.log_finding(self.name, "health_alert", {
                    "agent":          agent_id,
                    "issue":          "STALL",
                    "silent_seconds": round(elapsed, 1),
                    "action":         "Wake nudge injected into ledger.",
                    "fix":            f"Agent {agent_id} should re-trigger its iteration loop.",
                })
                logger.warning(f"[Agent8] STALL: {agent_id} silent {elapsed:.0f}s — nudge logged")

    # ── HEALTH: GPU stuck paused ─────────────────────────────────────────────
    async def _check_gpu_stuck(self, now: float):
        rows = ledger.get_findings(agent_name="Agent7-GPUThermal", limit=1)
        if not rows:
            return
        content = rows[0].get("content", {})
        is_paused = content.get("is_paused", False)
        temp      = content.get("current_temp", 0)
        age       = now - self._parse_ts(rows[0]["timestamp"])
        if is_paused and temp < 68 and age < 120 and self._can_fire("gpu_stuck", now, 300):
            self._mark_resolved("gpu_stuck", now)
            ledger.log_finding(self.name, "health_alert", {
                "agent":  "Agent7-GPUThermal",
                "issue":  "GPU_STUCK_PAUSED",
                "temp_c": temp,
                "action": "Force-resume signal emitted to ledger.",
            })
            ledger.log_finding("Agent7-GPUThermal", "sentinel_command", {
                "cmd": "FORCE_RESUME", "temp": temp, "from": self.name,
            })

    # ── HEALTH: DB bloat ─────────────────────────────────────────────────────
    async def _check_db_size(self, now: float):
        if not os.path.exists(self.db_path):
            return
        size_kb = os.path.getsize(self.db_path) / 1024
        if size_kb > MAX_DB_KB and self._can_fire("db_bloat", now, 1800):
            self._mark_resolved("db_bloat", now)
            try:
                conn = sqlite3.connect(self.db_path, timeout=10)
                conn.execute(
                    "DELETE FROM agent_logs WHERE timestamp < datetime('now', '-24 hours') "
                    "AND finding_type NOT IN ('ssl_strategy','model_candidate','synergistic_insight','broadcast_question','broadcast_response','benchmark_research','deployment_research','dataset_research','safety_research','context_brief','coordination_plan','testing_smoke','testing_regression','testing_performance','testing_data_quality','testing_api_contract','testing_ui_responsive','testing_failure_injection','testing_security_sanity','testing_training_loop','testing_telemetry','testing_release_readiness')"
                )
                deleted = conn.execute("SELECT changes()").fetchone()[0]
                conn.execute("VACUUM")
                conn.commit()
                conn.close()
                new_kb = os.path.getsize(self.db_path) / 1024
                ledger.log_finding(self.name, "db_maintenance", {
                    "before_kb": round(size_kb, 1),
                    "after_kb":  round(new_kb, 1),
                    "rows_pruned": deleted,
                })
                logger.info(f"[Agent8] DB pruned {size_kb:.0f}→{new_kb:.0f} KB")
            except Exception as exc:
                logger.error(f"[Agent8] DB prune error: {exc}")

    # ── Cross-agent synthesis ────────────────────────────────────────────────
    async def _synthesise_cross_agent(self, now: float):
        self._last_synthesis = now
        inputs = {}
        for aid in [
            "Agent1-IndustryResearch",
            "Agent2-ModelScout",
            "Agent3-CodeOpt",
            "Agent4-SSLLoop",
            "Agent5-RAG",
            "Agent6-DatasetBench",
            "Agent7-GPUThermal",
            "Agent8-SentinelGuardian",
            "Agent9-ContextCurator",
            "Agent10-CoordinationPlanner",
            "Agent11-BenchmarkResearch",
            "Agent12-DeploymentResearch",
            "Agent13-DatasetResearch",
            "Agent14-SafetyResearch",
            "Agent15-SmokeTest",
            "Agent16-RegressionTest",
            "Agent17-PerformanceTest",
            "Agent18-DataQualityTest",
            "Agent19-APIContractTest",
            "Agent20-UIResponsiveTest",
            "Agent21-FailureInjectionTest",
            "Agent22-SecuritySanityTest",
            "Agent23-TrainingLoopTest",
            "Agent24-TelemetryTest",
            "Agent25-ReleaseReadinessTest",
        ]:
            rows = ledger.get_findings(agent_name=aid, limit=1)
            if rows:
                inputs[aid] = rows[0]["content"]
        if len(inputs) < 2:
            return
        parts = []
        for aid, content in inputs.items():
            snippet = ""
            if isinstance(content, dict):
                for k in ["godmod_decision", "godmod_strategy", "notebooklm_context",
                          "godmod_validation", "bottleneck", "action"]:
                    if content.get(k):
                        snippet = str(content[k])[:100]
                        break
            if snippet:
                parts.append(f"{aid.split('-')[0]}: {snippet}")
        synthesis = ("Synthesised SmartSalai strategy across agents — " + " | ".join(parts) +
                     ". Recommended: INT8 quantisation + LoRA fine-tuning on scouted model, "
                 "guided by Agent4 SSL curriculum, constrained by Agent5 DriveLegal rules, "
                 "and coordinated by the full agent roster.")
        ledger.log_finding(self.name, "cross_agent_synthesis", {
            "sources":   list(inputs.keys()),
            "synthesis": synthesis,
        })

    # ── Helpers ───────────────────────────────────────────────────────────────
    def _parse_ts(self, ts_str: str) -> float:
        try:
            s = ts_str.replace(" ", "T")
            if not s.endswith("Z") and "+" not in s:
                s += "+00:00"
            from datetime import timezone
            dt = datetime.fromisoformat(s)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.timestamp()
        except Exception:
            return 0.0

    def _can_fire(self, key: str, now: float, cooldown: float) -> bool:
        return (now - self._resolved_cache.get(key, 0)) > cooldown

    def _mark_resolved(self, key: str, now: float):
        self._resolved_cache[key] = now


if __name__ == "__main__":
    import sys
    sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
    from dotenv import load_dotenv
    load_dotenv()
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    asyncio.run(SentinelGuardian().run())
