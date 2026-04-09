"""tests/test_driver_chatbot.py — DriverChatbot tests"""
from __future__ import annotations
import pytest
from agents.driver_profile import DriverProfileAgent, VoicePersona
from agents.driver_chatbot import DriverChatbot, _simplify_for_child

@pytest.fixture
def pa(tmp_path): return DriverProfileAgent(db_path=str(tmp_path / "c.db"))

def bot(pa, driver_id="d", language="en", persona="male"):
    pa.get_or_create(driver_id, language=language, voice_persona=persona)
    return DriverChatbot(driver_id, pa)

class TestIntentClassification:
    def test_greeting_en(self, pa):   assert bot(pa).             _classify("Hello there")         == "GREETING"
    def test_greeting_ta(self, pa):   assert bot(pa).             _classify("vanakkam")             == "GREETING"
    def test_greeting_hi(self, pa):   assert bot(pa).             _classify("namaste")              == "GREETING"
    def test_weakness(self, pa):      assert bot(pa).             _classify("my weaknesses")        == "WEAKNESS"
    def test_safety_score(self, pa):  assert bot(pa).             _classify("what is my score?")   == "SAFETY_SCORE"
    def test_route(self, pa):         assert bot(pa).             _classify("best route avoid potholes") == "ROUTE"
    def test_hazard(self, pa):        assert bot(pa).             _classify("any pothole near me") == "HAZARD_QUERY"
    def test_speed(self, pa):         assert bot(pa).             _classify("speed limit city")    == "SPEED_RULE"
    def test_sign(self, pa):          assert bot(pa).             _classify("stop sign meaning")   == "SIGN_QUERY"
    def test_legal(self, pa):         assert bot(pa).             _classify("section 208 camera")  == "LEGAL_CHALLENGE"
    def test_night(self, pa):         assert bot(pa).             _classify("tips night driving")  == "NIGHT_DRIVING"
    def test_safety_gen(self, pa):    assert bot(pa).             _classify("is helmet mandatory") == "GENERAL_SAFETY"
    def test_pothole_report(self, pa):assert bot(pa).             _classify("I found a pothole")   == "POTHOLE_REPORT"
    def test_unknown(self, pa):       assert bot(pa).             _classify("xyzzy foobar 999")    == "UNKNOWN"

class TestResponseGeneration:
    def test_chat_keys(self, pa):
        r = bot(pa, "k").chat("hello")
        for k in ("text","intent","lang","voice_persona","spoken"): assert k in r
    def test_greeting_nonempty(self, pa): assert len(bot(pa,"g").chat("hello")["text"]) > 10
    def test_ta_response(self, pa):
        pa.get_or_create("ta", language="ta")
        r = DriverChatbot("ta", pa).chat("vanakkam")
        assert r["lang"] == "ta" and any(ord(c) > 2944 for c in r["text"])
    def test_en_response(self, pa):
        r = bot(pa, "en", "en").chat("what are my weaknesses?")
        assert r["lang"] == "en" and len(r["text"]) > 10
    def test_hi_response(self, pa):
        pa.get_or_create("hi", language="hi")
        assert DriverChatbot("hi", pa).chat("namaste")["lang"] == "hi"
    def test_name_in_response(self, pa):
        pa.get_or_create("named", name="Priya", language="en")
        assert "Priya" in DriverChatbot("named", pa).chat("hello")["text"]
    def test_speed_response(self, pa):
        r = bot(pa,"sp","en").chat("speed limit?")
        assert "50" in r["text"] or "speed" in r["text"].lower()
    def test_legal_response(self, pa):
        r = bot(pa,"lc","en").chat("section 208 camera challenge")
        assert "208" in r["text"] or "challeng" in r["text"].lower()
    def test_chat_history_grows(self, pa):
        b = bot(pa,"hist","en"); b.chat("hello"); b.chat("speed limit?")
        assert len(pa._store.load("hist").chat_history) >= 4

class TestChildPersona:
    def test_child_stored(self, pa):
        pa.get_or_create("ch", language="en", voice_persona="child")
        assert DriverChatbot("ch",pa).chat("hello")["voice_persona"] == "child"
    def test_simplify_shortens(self):
        long = "Mandatory helmet enforced. Statutory penalties apply. IRC:67 compliance required. Speed limits enforced."
        assert len(_simplify_for_child(long)) < len(long)

class TestPreferences:
    def test_set_language(self, pa):
        pa.get_or_create("pref","","ta"); b = DriverChatbot("pref",pa)
        assert b.set_preference(language="en")["language"] == "en"
    def test_set_persona(self, pa):
        pa.get_or_create("pv"); b = DriverChatbot("pv",pa)
        assert b.set_preference(voice_persona="female")["voice_persona"] == "female"
    def test_get_summary(self, pa):
        pa.get_or_create("sm"); b = DriverChatbot("sm",pa)
        s = b.get_profile_summary(); assert "driver_id" in s

class TestRobustness:
    def test_no_crash_no_route_advisor(self, pa):
        r = bot(pa,"nr","en").chat("best route avoid potholes"); assert "text" in r
    def test_empty_name(self, pa):
        pa.get_or_create("nn","","en"); r = DriverChatbot("nn",pa).chat("hello")
        assert "friend" in r["text"].lower()
    def test_spoken_false_without_audio(self, pa):
        assert bot(pa,"sp2").chat("hi")["spoken"] is False
