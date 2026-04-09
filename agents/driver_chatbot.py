"""
agents/driver_chatbot.py
SmartSalai — Driver Co-Pilot Chatbot

Intent-based conversational agent that:
  • Learns from driver profile (language, voice persona, weaknesses)
  • Answers driving questions (speed rules, signs, legal rights, hazards, routes)
  • Supports Tamil / English / Hindi
  • Supports Male / Female / Child voice personas
  • Optionally speaks via AcousticUI
"""

from __future__ import annotations

import re
from typing import List, Optional, Tuple

# ---------------------------------------------------------------------------
# Imports
# ---------------------------------------------------------------------------

from agents.driver_profile import DriverProfileAgent, DriverProfile, VoicePersona

# ---------------------------------------------------------------------------
# Voice persona → Bhashini gender mapping
# ---------------------------------------------------------------------------

_PERSONA_BHASHINI_GENDER: dict[str, str] = {
    VoicePersona.MALE:   "male",
    VoicePersona.FEMALE: "female",
    VoicePersona.CHILD:  "female",   # child uses female voice with higher rate
}

# ---------------------------------------------------------------------------
# Intent patterns  (order matters — first match wins)
# ---------------------------------------------------------------------------

_INTENT_PATTERNS: List[Tuple[str, List[str]]] = [
    ("GREETING",         [r"\b(hello|hi|vanakkam|vanakam|வணக்கம்|namaste|नमस्ते)\b",
                          r"\b(good morning|good evening|காலை வணக்கம்)\b"]),
    ("WEAKNESS",         [r"\b(weakness(es)?|weak|பலவீனம்|கமி|improvement|improve)\b",
                          r"\b(my driving|என் ஓட்டுதல்|meri driving)\b"]),
    ("SAFETY_SCORE",     [r"\b(score|rating|safe|பாதுகாப்பு|மதிப்பெண்|kitni safe)\b"]),
    ("ROUTE",            [r"\b(route|road|path|வழி|பாதை|safest|best route|avoid|navigate)\b"]),
    ("POTHOLE_REPORT",   [r"\b(report|found|spotted|found pothole|குழி கண்டேன்)\b",
                          r"இருக்கிறது"]),
    ("HAZARD_QUERY",     [r"\b(hazard|pothole|குழி|road work|நிர்மாண|danger|ஆபத்து|खतरा)\b"]),
    ("SPEED_RULE",       [r"\b(speed|வேகம்|limit|kmh|km.?h|speed limit|gati)\b"]),
    ("SIGN_QUERY",       [r"\b(sign|signal|board|விளக்கம்|அர்த்தம்|traffic light|சிக்னல்)\b"]),
    ("LEGAL_CHALLENGE",  [r"\b(section 208|challan|ticket|camera|challenge|legal|சட்டம்|கேமரா)\b"]),
    ("NIGHT_DRIVING",    [r"\b(night|இரவு|dark|rात|late|midnight)\b"]),
    ("GENERAL_SAFETY",   [r"\b(helmet|seat.?belt|சீட்|பெல்ட்|safe driving|safety|सुरक्षा)\b"]),
    ("HISTORY",          [r"\b(history|past|பழைய|last time|trips|sessions)\b"]),
]

# ---------------------------------------------------------------------------
# Response templates — (lang → text)
# Placeholders: {name}, {score}, {weaknesses}, {sessions}, {route_advice}
# ---------------------------------------------------------------------------

_RESPONSES: dict[str, dict[str, str]] = {
    "GREETING": {
        "en": "Hello {name}! 👋 Your safety score is {score}/100. How can I help you today?",
        "ta": "வணக்கம் {name}! 👋 உங்கள் பாதுகாப்பு மதிப்பெண்: {score}/100. எப்படி உதவட்டும்?",
        "hi": "नमस्ते {name}! 👋 आपका सुरक्षा स्कोर: {score}/100. मैं कैसे मदद करूं?",
    },
    "WEAKNESS": {
        "en": "Your safety score is {score}/100. Identified areas to improve:\n{weaknesses}",
        "ta": "உங்கள் மதிப்பெண்: {score}/100. மேம்படுத்த வேண்டிய பகுதிகள்:\n{weaknesses}",
        "hi": "आपका स्कोर: {score}/100. सुधार के क्षेत्र:\n{weaknesses}",
    },
    "SAFETY_SCORE": {
        "en": "Your current safety score is {score}/100 across {sessions} session(s). Keep it up! 🚗",
        "ta": "உங்கள் தற்போதைய மதிப்பெண் {sessions} பயணத்தில் {score}/100. சிறப்பாக செல்லுங்கள்! 🚗",
        "hi": "आपका वर्तमान स्कोर {sessions} सेशन में {score}/100 है। बढ़िया! 🚗",
    },
    "ROUTE": {
        "en": "🗺 For the safest route: {route_advice} Use the Route Scorer in the dashboard to compare alternatives in real-time.",
        "ta": "🗺 பாதுகாப்பான வழி: {route_advice} டாஷ்போர்டில் Route Scorer ஐ பயன்படுத்துங்கள்.",
        "hi": "🗺 सबसे सुरक्षित रास्ता: {route_advice} डैशबोर्ड में Route Scorer का उपयोग करें।",
    },
    "HAZARD_QUERY": {
        "en": "⚠ Live hazard data comes from our community. Open the dashboard map to see potholes, road work, and debris near you.",
        "ta": "⚠ நேரடி ஆபத்து தகவல்கள் கமியூனிட்டியிலிருந்து வருகின்றன. டாஷ்போர்டு வரைபடம் திறக்கவும்.",
        "hi": "⚠ लाइव खतरे की जानकारी कमुनिटी से आती है। डैशबोर्ड मैप खोलें।",
    },
    "SPEED_RULE": {
        "en": "🚦 Speed limits in India: City roads 50 km/h | Highways 100 km/h | Expressways 120 km/h. Always obey posted signs.",
        "ta": "🚦 இந்தியாவில் வேக வரம்பு: நகர சாலைகள் 50 km/h | நெடுஞ்சாலை 100 km/h | எக்ஸ்பிரஸ்வே 120 km/h.",
        "hi": "🚦 भारत में गति सीमा: शहर 50 km/h | हाइवे 100 km/h | एक्सप्रेसवे 120 km/h।",
    },
    "SIGN_QUERY": {
        "en": "�� Traffic signs: RED OCTAGON = Stop | YELLOW TRIANGLE = Warning | BLUE CIRCLE = Mandatory | WHITE RECTANGLE = Information.",
        "ta": "🚸 போக்குவரத்து அடையாளங்கள்: சிவப்பு = நிறுத்து | மஞ்சள் = எச்சரிக்கை | நீலம் = கட்டாயம் | வெள்ளை = தகவல்.",
        "hi": "🚸 ट्रैफिक साइन: लाल अष्टभुज = रुकें | पीला त्रिकोण = चेतावनी | नीला वृत्त = अनिवार्य।",
    },
    "LEGAL_CHALLENGE": {
        "en": "⚖ Under Section 208 of the Motor Vehicles Act you may challenge a speed camera fine within 60 days at the issuing court. Keep your vehicle registration and the notice handy.",
        "ta": "⚖ மோட்டார் வாகனச் சட்டம் பிரிவு 208 ன்படி, கேமரா அபராதத்தை 60 நாட்களுக்குள் நீதிமன்றத்தில் சவால் செய்யலாம்.",
        "hi": "⚖ मोटर वाहन अधिनियम धारा 208 के तहत आप 60 दिनों के भीतर स्पीड कैमरा जुर्माने को अदालत में चुनौती दे सकते हैं।",
    },
    "NIGHT_DRIVING": {
        "en": "🌙 Night driving tips: Use low beam in fog | Reduce speed by 20% | Check tyre pressure | Take a break every 2 hours.",
        "ta": "🌙 இரவு வாகனம் ஓட்டும் குறிப்புகள்: மூடுபனியில் குறைந்த கதிர் பயன்படுத்தவும் | 20% வேகம் குறைக்கவும் | 2 மணி நேரத்திற்கு ஒரு முறை இளைப்பாறவும்.",
        "hi": "🌙 रात में गाड़ी चलाने के टिप्स: कोहरे में लो-बीम | 20% गति कम करें | हर 2 घंटे में ब्रेक लें।",
    },
    "GENERAL_SAFETY": {
        "en": "🛡 Safety essentials: Seatbelt = mandatory for all | Helmet = mandatory for two-wheelers | No phone while driving.",
        "ta": "🛡 பாதுகாப்பு அவசியங்கள்: சீட்பெல்ட் = அனைவருக்கும் கட்டாயம் | ஹெல்மெட் = இரு சக்கர வாகன ஓட்டிகளுக்கு கட்டாயம்.",
        "hi": "🛡 सुरक्षा जरूरी: सीटबेल्ट = सभी के लिए अनिवार्य | हेलमेट = दोपहिया के लिए अनिवार्य | गाड़ी चलाते समय फोन नहीं।",
    },
    "POTHOLE_REPORT": {
        "en": "📍 Thanks for reporting! The pothole has been logged with your GPS coordinates. Our community map is updated live — other drivers will be warned. You have reported {reported} hazard(s) so far.",
        "ta": "📍 புகாரளித்ததற்கு நன்றி! குழி உங்கள் GPS ஒருங்கிணைப்புகளுடன் பதிவு செய்யப்பட்டது. இதுவரை {reported} ஆபத்துகளை புகாரளித்தீர்கள்.",
        "hi": "📍 रिपोर्ट के लिए धन्यवाद! गड्ढा आपके GPS निर्देशांक के साथ दर्ज किया गया। अब तक {reported} खतरे रिपोर्ट किए।",
    },
    "HISTORY": {
        "en": "📊 Driving summary: {sessions} session(s) | Safety score {score}/100 | {near_miss} near-miss event(s).",
        "ta": "📊 ஓட்டுதல் சுருக்கம்: {sessions} பயணங்கள் | மதிப்பெண் {score}/100 | {near_miss} ஆபத்தான நிகழ்வுகள்.",
        "hi": "📊 ड्राइविंग सारांश: {sessions} सेशन | स्कोर {score}/100 | {near_miss} नियर-मिस इवेंट।",
    },
    "UNKNOWN": {
        "en": "Sorry, I didn't quite understand that. You can ask me about: speed limits, traffic signs, safe routes, driving safety tips, or your Section 208 legal rights.",
        "ta": "மன்னிக்கவும், புரியவில்லை. வேக வரம்பு, போக்குவரத்து அடையாளங்கள், பாதுகாப்பான வழி, அல்லது சட்ட உரிமைகளைப் பற்றி கேளுங்கள்.",
        "hi": "क्षमा करें, समझ नहीं आया। आप गति सीमा, ट्रैफिक साइन, सुरक्षित रास्ते या कानूनी अधिकारों के बारे में पूछ सकते हैं।",
    },
}

# Child-friendly substitutions
_CHILD_SIMPLIFY = [
    (r"\bMandatory\b",   "Required"),
    (r"\bmandatory\b",   "required"),
    (r"\bstatutory\b",   "law"),
    (r"\bInfractions?\b","rule breaking"),
    (r"\binfraction\b",  "rule breaking"),
    (r"\benforce[ds]?\b","checked"),
    (r"\bpenalt\w+",     "fine"),
    (r"\bIRC:\d+\b",     "road rules"),
]


def _simplify_for_child(text: str) -> str:
    for pattern, replacement in _CHILD_SIMPLIFY:
        text = re.sub(pattern, replacement, text)
    # Limit to first 2 sentences
    sentences = re.split(r"(?<=[.!?])\s+", text.strip())
    return " ".join(sentences[:2])


# ---------------------------------------------------------------------------
# DriverChatbot
# ---------------------------------------------------------------------------

class DriverChatbot:
    """
    Intent-based co-pilot chatbot.

    Args:
        driver_id:    Unique driver identifier.
        profile_agent: DriverProfileAgent to load/save driver state.
        route_advisor: Optional RouteAdvisor for live hazard routing.
        acoustic_ui:   Optional AcousticUI for TTS output.
    """

    def __init__(
        self,
        driver_id: str,
        profile_agent: DriverProfileAgent,
        route_advisor=None,
        acoustic_ui=None,
    ) -> None:
        self._driver_id    = driver_id
        self._pa           = profile_agent
        self._ra           = route_advisor
        self._audio        = acoustic_ui

    # ------------------------------------------------------------------

    def _profile(self) -> DriverProfile:
        return self._pa._load_or_create(self._driver_id)

    def _classify(self, text: str) -> str:
        lowered = text.lower()
        for intent, patterns in _INTENT_PATTERNS:
            for pat in patterns:
                if re.search(pat, lowered, re.IGNORECASE):
                    return intent
        return "UNKNOWN"

    def _render(self, profile: DriverProfile, intent: str) -> str:
        lang = profile.language if profile.language in ("en", "ta", "hi") else "en"
        template = _RESPONSES.get(intent, _RESPONSES["UNKNOWN"]).get(
            lang, _RESPONSES["UNKNOWN"]["en"]
        )
        name        = profile.name or "friend"
        score       = profile.safety_score()
        sessions    = profile.total_sessions
        near_miss   = profile.near_miss_count
        reported    = profile.hazards_reported
        weaknesses_list = self._pa.get_weakness_advice(self._driver_id)
        weaknesses_str  = ("\n• ".join(weaknesses_list)) if weaknesses_list else (
            "No major weaknesses detected yet. Keep it up!" if lang == "en"
            else ("இன்னும் பலவீனம் இல்லை!" if lang == "ta" else "अभी तक कोई कमज़ोरी नहीं!")
        )
        route_advice = (
            "I'll analyse community hazard data to suggest the safest path." if lang == "en"
            else ("சமூக ஆபத்து தரவை பகுப்பாய்வு செய்கிறேன்." if lang == "ta"
                  else "मैं सामुदायिक डेटा से सुरक्षित रास्ता सुझाऊंगा।")
        )
        if self._ra is not None:
            route_advice = (
                "Use the /api/v1/route/score endpoint with your waypoints for a live hazard score."
                if lang == "en"
                else route_advice
            )

        text = template.format(
            name=name,
            score=score,
            sessions=sessions,
            near_miss=near_miss,
            reported=reported,
            weaknesses=weaknesses_str,
            route_advice=route_advice,
        )

        if profile.voice_persona == VoicePersona.CHILD:
            text = _simplify_for_child(text)

        return text

    # ------------------------------------------------------------------

    def chat(self, message: str) -> dict:
        """
        Process a driver message and return a response dict.

        Returns:
            {text, intent, lang, voice_persona, spoken}
        """
        profile = self._profile()
        lang    = profile.language if profile.language in ("en", "ta", "hi") else "en"
        intent  = self._classify(message)
        text    = self._render(profile, intent)

        # Persist exchange
        self._pa.add_chat_message(self._driver_id, "user", message)
        self._pa.add_chat_message(self._driver_id, "bot",  text)

        # Optional TTS
        spoken = False
        if self._audio is not None:
            try:
                self._audio.alert(text, priority=2)
                spoken = True
            except Exception:
                pass

        return {
            "text":         text,
            "intent":       intent,
            "lang":         lang,
            "voice_persona": profile.voice_persona,
            "spoken":       spoken,
        }

    # ------------------------------------------------------------------

    def set_preference(
        self,
        language: Optional[str] = None,
        voice_persona: Optional[str] = None,
        name: Optional[str] = None,
    ) -> dict:
        p = self._pa.update_preferences(
            self._driver_id,
            name=name,
            language=language,
            voice_persona=voice_persona,
        )
        return {
            "driver_id":    p.driver_id,
            "language":     p.language,
            "voice_persona": p.voice_persona,
            "name":         p.name,
        }

    def get_profile_summary(self) -> dict:
        return self._pa.get_summary(self._driver_id)
