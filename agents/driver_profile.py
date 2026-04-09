"""
agents/driver_profile.py
SmartSalai — Per-Driver Memory & Profile Agent

Stores driving patterns, weaknesses, preferences (language, voice persona)
and chat history for each driver in a lightweight SQLite DB.  All public
methods are synchronous and thread-safe (single writer via DB connection
per call).
"""

from __future__ import annotations

import datetime
import json
import math
import sqlite3
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import List, Optional

# ---------------------------------------------------------------------------
# Constants / enums (plain strings so they serialise trivially to JSON/SQLite)
# ---------------------------------------------------------------------------

class VoicePersona:
    MALE   = "male"
    FEMALE = "female"
    CHILD  = "child"

class WeaknessCode:
    AGGRESSIVE_BRAKING  = "AGGRESSIVE_BRAKING"
    SPEEDING_TENDENCY   = "SPEEDING_TENDENCY"
    NEAR_MISS_PRONE     = "NEAR_MISS_PRONE"
    NIGHT_DRIVING       = "NIGHT_DRIVING"
    LANE_DISCIPLINE     = "LANE_DISCIPLINE"

# Thresholds that trigger a weakness flag
_THRESH_BRAKING        = 5    # aggressive braking events
_THRESH_SPEED_VIOL     = 3    # speed violations
_THRESH_CRITICAL_NM    = 3    # critical near-misses
_THRESH_NIGHT          = 10   # night sessions without incident flag

# ---------------------------------------------------------------------------
# Weakness advice strings (multilingual)
# ---------------------------------------------------------------------------

_WEAKNESS_ADVICE: dict[str, dict[str, str]] = {
    WeaknessCode.AGGRESSIVE_BRAKING: {
        "en": "Maintain a safe following distance to avoid harsh braking.",
        "ta": "திடீர் தடை தவிர்க்க பாதுகாப்பான தூரம் பேணுங்கள்.",
        "hi": "अचानक ब्रेक से बचने के लिए सुरक्षित दूरी बनाए रखें।",
    },
    WeaknessCode.SPEEDING_TENDENCY: {
        "en": "Stick to posted speed limits — they save lives.",
        "ta": "வேகவரம்பை கடைப்பிடியுங்கள் — இது உயிர்களை காக்கும்.",
        "hi": "गति सीमा का पालन करें — यह जीवन बचाता है।",
    },
    WeaknessCode.NEAR_MISS_PRONE: {
        "en": "Multiple near-misses detected. Increase situational awareness.",
        "ta": "பல ஆபத்தான சூழல்கள் பதிவு ஆயின. கூடுதல் கவனம் செலுத்துங்கள்.",
        "hi": "कई नियर-मिस दर्ज हुए हैं। अधिक सतर्क रहें।",
    },
    WeaknessCode.NIGHT_DRIVING: {
        "en": "Use headlights properly and reduce speed at night.",
        "ta": "இரவில் விளக்குகளை சரியாக பயன்படுத்தி வேகத்தை குறைக்கவும்.",
        "hi": "रात में हेडलाइट सही से उपयोग करें और गति कम करें।",
    },
    WeaknessCode.LANE_DISCIPLINE: {
        "en": "Keep to your lane — sudden lane changes cause accidents.",
        "ta": "உங்கள் வழியில் செல்லுங்கள் — திடீர் மாற்றம் விபத்தை ஏற்படுத்தும்.",
        "hi": "अपनी लेन में रहें — अचानक लेन बदलने से दुर्घटना होती है।",
    },
}

# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class DriverWeakness:
    code:  str
    label: str
    count: int = 0

    def to_dict(self) -> dict:
        return {"code": self.code, "label": self.label, "count": self.count}

    @classmethod
    def from_dict(cls, d: dict) -> "DriverWeakness":
        return cls(code=d["code"], label=d.get("label", d["code"]), count=d.get("count", 0))


@dataclass
class DriverProfile:
    driver_id:   str
    name:        str = ""
    language:    str = "ta"       # ta | en | hi
    voice_persona: str = VoicePersona.MALE
    created_at:  float = field(default_factory=time.time)
    last_seen:   float = field(default_factory=time.time)

    # Counters
    total_sessions:         int   = 0
    near_miss_count:        int   = 0
    critical_near_misses:   int   = 0
    speed_violations:       int   = 0
    aggressive_braking_count: int = 0
    night_driving_sessions: int   = 0
    total_km:               float = 0.0
    hazards_reported:       int   = 0

    # Learned patterns
    weaknesses:   List[DriverWeakness] = field(default_factory=list)
    chat_history: List[dict]           = field(default_factory=list)

    # ------------------------------------------------------------------
    # Derived helpers
    # ------------------------------------------------------------------

    def safety_score(self) -> int:
        """0–100 composite score (higher = safer). Never below 0."""
        penalty = (
            self.critical_near_misses    * 10
            + self.speed_violations      * 5
            + self.aggressive_braking_count * 2
            + len(self.weaknesses)       * 5
        )
        return max(0, 100 - penalty)

    def greeting(self) -> str:
        display = self.name or "friend"
        score   = self.safety_score()
        if self.language == "ta":
            return (
                f"வணக்கம் {display}! உங்கள் பாதுகாப்பு மதிப்பெண்: {score}/100. "
                "நான் உங்கள் SmartSalai கோ-பைலட். எப்படி உதவட்டும்?"
            )
        if self.language == "hi":
            return (
                f"नमस्ते {display}! आपका सुरक्षा स्कोर: {score}/100. "
                "मैं आपका SmartSalai Co-Pilot हूँ। कैसे मदद करूं?"
            )
        return (
            f"Hello {display}! Your safety score is {score}/100. "
            "I'm your SmartSalai Co-Pilot. How can I help?"
        )

    def weakness_codes(self) -> List[str]:
        return [w.code for w in self.weaknesses]


# ---------------------------------------------------------------------------
# SQLite store
# ---------------------------------------------------------------------------

_DEFAULT_DB = Path(__file__).parent.parent / "data" / "driver_profiles.db"

class DriverMemoryStore:
    """Thread-safe SQLite-backed store for DriverProfile objects."""

    def __init__(self, db_path: str | None = None) -> None:
        self._db = str(db_path or _DEFAULT_DB)
        Path(self._db).parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db, check_same_thread=False, timeout=10)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_schema(self) -> None:
        with self._connect() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS driver_profiles (
                    driver_id   TEXT PRIMARY KEY,
                    profile_json TEXT NOT NULL,
                    updated_at  REAL NOT NULL
                )
            """)
            conn.commit()

    # ------------------------------------------------------------------
    def save(self, profile: DriverProfile) -> None:
        data = asdict(profile)
        data["weaknesses"]    = [w.to_dict() for w in profile.weaknesses]
        data["chat_history"]  = profile.chat_history[-100:]   # cap at 100
        with self._connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO driver_profiles (driver_id, profile_json, updated_at) "
                "VALUES (?, ?, ?)",
                (profile.driver_id, json.dumps(data), time.time()),
            )
            conn.commit()

    def load(self, driver_id: str) -> Optional[DriverProfile]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT profile_json FROM driver_profiles WHERE driver_id=?",
                (driver_id,),
            ).fetchone()
        if row is None:
            return None
        data = json.loads(row["profile_json"])
        data["weaknesses"] = [DriverWeakness.from_dict(w) for w in data.get("weaknesses", [])]
        return DriverProfile(**data)

    def list_driver_ids(self) -> List[str]:
        with self._connect() as conn:
            rows = conn.execute("SELECT driver_id FROM driver_profiles").fetchall()
        return [r["driver_id"] for r in rows]


# ---------------------------------------------------------------------------
# Profile agent
# ---------------------------------------------------------------------------

class DriverProfileAgent:
    """
    High-level agent that wraps DriverMemoryStore with business logic:
    pattern learning, weakness detection, preference management.
    """

    def __init__(self, db_path: str | None = None) -> None:
        self._store = DriverMemoryStore(db_path=db_path)

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------

    def get_or_create(
        self,
        driver_id: str,
        name: str = "",
        language: str = "ta",
        voice_persona: str = VoicePersona.MALE,
    ) -> DriverProfile:
        p = self._store.load(driver_id)
        if p is not None:
            return p
        p = DriverProfile(
            driver_id=driver_id,
            name=name,
            language=language,
            voice_persona=voice_persona,
        )
        self._store.save(p)
        return p

    def _load_or_create(self, driver_id: str) -> DriverProfile:
        p = self._store.load(driver_id)
        return p if p is not None else self.get_or_create(driver_id)

    def update_preferences(
        self,
        driver_id: str,
        name: Optional[str] = None,
        language: Optional[str] = None,
        voice_persona: Optional[str] = None,
    ) -> DriverProfile:
        p = self._load_or_create(driver_id)
        if name         is not None: p.name          = name
        if language     is not None: p.language      = language
        if voice_persona is not None: p.voice_persona = voice_persona
        p.last_seen = time.time()
        self._store.save(p)
        return p

    # ------------------------------------------------------------------
    # Event recording
    # ------------------------------------------------------------------

    def record_session_start(self, driver_id: str) -> DriverProfile:
        p = self._load_or_create(driver_id)
        p.total_sessions += 1
        p.last_seen = time.time()
        # Detect night session (IST)
        ist_hour = (datetime.datetime.now(datetime.timezone.utc).hour + 5) % 24
        if ist_hour >= 21 or ist_hour < 5:
            p.night_driving_sessions += 1
        self._detect_weaknesses(p)
        self._store.save(p)
        return p

    def record_near_miss(
        self,
        driver_id: str,
        severity: str = "HIGH",
        ax: float = 0.0,
        ay: float = 0.0,
    ) -> DriverProfile:
        p = self._load_or_create(driver_id)
        p.near_miss_count += 1
        if severity == "CRITICAL":
            p.critical_near_misses += 1
        if abs(ax) > 6.0:                        # harsh longitudinal decel
            p.aggressive_braking_count += 1
        self._detect_weaknesses(p)
        self._store.save(p)
        return p

    def record_speed_violation(self, driver_id: str) -> DriverProfile:
        p = self._load_or_create(driver_id)
        p.speed_violations += 1
        self._detect_weaknesses(p)
        self._store.save(p)
        return p

    def record_hazard_reported(
        self,
        driver_id: str,
        km_delta: float = 0.0,
    ) -> DriverProfile:
        p = self._load_or_create(driver_id)
        p.hazards_reported += 1
        p.total_km += km_delta
        self._store.save(p)
        return p

    def add_chat_message(
        self, driver_id: str, role: str, text: str
    ) -> DriverProfile:
        p = self._load_or_create(driver_id)
        p.chat_history.append({"role": role, "text": text, "ts": time.time()})
        if len(p.chat_history) > 100:
            p.chat_history = p.chat_history[-100:]
        self._store.save(p)
        return p

    # ------------------------------------------------------------------
    # Weakness detection
    # ------------------------------------------------------------------

    def _detect_weaknesses(self, p: DriverProfile) -> None:
        existing = {w.code for w in p.weaknesses}

        def _add(code: str, label: str) -> None:
            if code not in existing:
                p.weaknesses.append(DriverWeakness(code=code, label=label, count=1))
                existing.add(code)
            else:
                for w in p.weaknesses:
                    if w.code == code:
                        w.count += 1

        if p.aggressive_braking_count > _THRESH_BRAKING:
            _add(WeaknessCode.AGGRESSIVE_BRAKING, "Aggressive Braking")
        if p.speed_violations > _THRESH_SPEED_VIOL:
            _add(WeaknessCode.SPEEDING_TENDENCY, "Speeding Tendency")
        if p.critical_near_misses > _THRESH_CRITICAL_NM:
            _add(WeaknessCode.NEAR_MISS_PRONE, "Near-Miss Prone")

    # ------------------------------------------------------------------
    # Summaries
    # ------------------------------------------------------------------

    def get_summary(self, driver_id: str) -> dict:
        p = self._store.load(driver_id)
        if p is None:
            return {}
        return {
            "driver_id":       p.driver_id,
            "name":            p.name,
            "language":        p.language,
            "voice_persona":   p.voice_persona,
            "safety_score":    p.safety_score(),
            "total_sessions":  p.total_sessions,
            "near_miss_count": p.near_miss_count,
            "hazards_reported": p.hazards_reported,
            "total_km":        round(p.total_km, 2),
            "weaknesses":      [w.to_dict() for w in p.weaknesses],
            "last_seen":       p.last_seen,
        }

    def get_weakness_advice(self, driver_id: str) -> List[str]:
        p = self._store.load(driver_id)
        if p is None:
            return []
        lang = p.language if p.language in ("ta", "en", "hi") else "en"
        advice = []
        for w in p.weaknesses:
            tip = _WEAKNESS_ADVICE.get(w.code, {}).get(lang)
            if tip:
                advice.append(tip)
        return advice
