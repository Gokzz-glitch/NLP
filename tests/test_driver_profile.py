"""tests/test_driver_profile.py — DriverProfileAgent tests"""
from __future__ import annotations
import pytest
from agents.driver_profile import (
    DriverMemoryStore, DriverProfile, DriverProfileAgent,
    DriverWeakness, VoicePersona, WeaknessCode,
)

@pytest.fixture
def store(tmp_path):  return DriverMemoryStore(db_path=str(tmp_path / "t.db"))
@pytest.fixture
def agent(tmp_path):  return DriverProfileAgent(db_path=str(tmp_path / "t.db"))

class TestDriverMemoryStore:
    def test_save_load(self, store):
        p = DriverProfile(driver_id="d1", name="Ramesh", language="ta")
        store.save(p); loaded = store.load("d1")
        assert loaded.name == "Ramesh"
    def test_load_missing(self, store):     assert store.load("ghost") is None
    def test_upsert(self, store):
        p = DriverProfile(driver_id="d2", name="Old"); store.save(p)
        p.name = "New"; store.save(p)
        assert store.load("d2").name == "New"
    def test_list_ids(self, store):
        for i in range(3): store.save(DriverProfile(driver_id=f"x{i}"))
        assert len(store.list_driver_ids()) == 3
    def test_weaknesses_roundtrip(self, store):
        p = DriverProfile(driver_id="d3",
            weaknesses=[DriverWeakness(code=WeaknessCode.AGGRESSIVE_BRAKING, label="AB")])
        store.save(p); loaded = store.load("d3")
        assert loaded.weaknesses[0].code == WeaknessCode.AGGRESSIVE_BRAKING
    def test_chat_history_roundtrip(self, store):
        p = DriverProfile(driver_id="d4", chat_history=[{"role":"user","text":"hi","ts":0.0}])
        store.save(p); assert store.load("d4").chat_history[0]["text"] == "hi"

class TestDriverProfileAgent:
    def test_get_or_create_new(self, agent):
        p = agent.get_or_create("new"); assert p.driver_id == "new"
    def test_get_or_create_existing(self, agent):
        agent.get_or_create("x", name="Priya"); assert agent.get_or_create("x").name == "Priya"
    def test_update_prefs(self, agent):
        agent.get_or_create("pref")
        p = agent.update_preferences("pref", name="K", language="hi", voice_persona="female")
        assert p.name == "K" and p.language == "hi" and p.voice_persona == "female"
    def test_session_count(self, agent):
        agent.get_or_create("s"); agent.record_session_start("s")
        assert agent.record_session_start("s").total_sessions == 2
    def test_near_miss(self, agent):
        agent.get_or_create("nm")
        p = agent.record_near_miss("nm", "CRITICAL")
        assert p.near_miss_count == 1 and p.critical_near_misses == 1
    def test_aggressive_braking_weakness(self, agent):
        agent.get_or_create("ab")
        for _ in range(6): agent.record_near_miss("ab", "HIGH", ax=-7.0)
        codes = [w.code for w in agent.get_or_create("ab").weaknesses]
        assert WeaknessCode.AGGRESSIVE_BRAKING in codes
    def test_critical_nm_weakness(self, agent):
        agent.get_or_create("cm")
        for _ in range(4): agent.record_near_miss("cm", "CRITICAL")
        codes = [w.code for w in agent.get_or_create("cm").weaknesses]
        assert WeaknessCode.NEAR_MISS_PRONE in codes
    def test_speed_weakness(self, agent):
        agent.get_or_create("sv")
        for _ in range(4): agent.record_speed_violation("sv")
        codes = [w.code for w in agent.get_or_create("sv").weaknesses]
        assert WeaknessCode.SPEEDING_TENDENCY in codes
    def test_hazard_reported(self, agent):
        agent.get_or_create("hr")
        p = agent.record_hazard_reported("hr", km_delta=1.5)
        assert p.hazards_reported == 1 and p.total_km == pytest.approx(1.5)
    def test_chat_message(self, agent):
        agent.get_or_create("ch")
        p = agent.add_chat_message("ch", "user", "hello")
        assert p.chat_history[0]["role"] == "user"
    def test_chat_capped_100(self, agent):
        agent.get_or_create("cap")
        for i in range(110): agent.add_chat_message("cap", "user", f"m{i}")
        assert len(agent.get_or_create("cap").chat_history) <= 100
    def test_get_summary(self, agent):
        agent.get_or_create("sm", language="en")
        s = agent.get_summary("sm"); assert "safety_score" in s
    def test_get_summary_missing(self, agent): assert agent.get_summary("nope") == {}
    def test_weakness_advice(self, agent):
        agent.get_or_create("adv", language="ta")
        for _ in range(4): agent.record_speed_violation("adv")
        assert len(agent.get_weakness_advice("adv")) > 0

class TestDriverProfile:
    def test_safety_score_perfect(self): assert DriverProfile("x").safety_score() == 100
    def test_safety_score_penalised(self):
        p = DriverProfile("bad", critical_near_misses=3, speed_violations=4, aggressive_braking_count=6)
        assert p.safety_score() < 60
    def test_safety_score_min_zero(self):
        p = DriverProfile("w", critical_near_misses=100, speed_violations=100, aggressive_braking_count=100)
        assert p.safety_score() == 0
    def test_greeting_en(self): assert "friend" in DriverProfile("g", language="en").greeting()
    def test_greeting_ta(self): assert "வணக்கம்" in DriverProfile("g", language="ta").greeting()
    def test_greeting_with_name(self): assert "Meena" in DriverProfile("g", name="Meena").greeting()
    def test_weakness_codes(self):
        p = DriverProfile("wc", weaknesses=[
            DriverWeakness(code="AGGRESSIVE_BRAKING", label="AB"),
            DriverWeakness(code="SPEEDING_TENDENCY",  label="SP"),
        ])
        assert "AGGRESSIVE_BRAKING" in p.weakness_codes()

class TestVoicePersona:
    def test_values(self):
        assert VoicePersona.MALE == "male"
        assert VoicePersona.FEMALE == "female"
        assert VoicePersona.CHILD == "child"
