import os
import logging
import sqlite3
import numpy as np
from core.driver_memory import memory
from core.secret_manager import get_manager
from edge_vector_store import EdgeVectorStore

logger = logging.getLogger("edge_sentinel.gen_voice")
logger.setLevel(logging.INFO)

class GenerativeVoiceEngine:
    def __init__(self):
        sm = get_manager(strict_mode=False)
        self.api_key = sm.get("GEMINI_API_KEY")
        self.legal_store = EdgeVectorStore()
        if self.api_key:
            import google.generativeai as genai
            genai.configure(api_key=self.api_key)
            self.model = genai.GenerativeModel('gemini-1.5-flash')
            self.mode = "api"
            logger.info("✓ VOICE_ENGINE: Activated Cloud LLM (Gemini API via SecretManager)")
        else:
            self.mode = "local_fallback"
            logger.warning("⚠️ VOICE_ENGINE: No GEMINI_API_KEY found. Using Offline Fallback.")

    def get_legal_context(self, query):
        try:
            results = self.legal_store.query(query, top_k=1)
            if results:
                return f"Legal Stat: {results[0][1]}"
            return ""
        except: return ""

    def generate_alert(self, hazard_type, severity, direction="FRONT"):
        context = memory.get_context_for_llm()
        legal_info = self.get_legal_context(f"Penalty for {hazard_type}")
        
        prompt = f"""
        System: You are an incredibly comforting, adaptive, emotionally intelligent AI co-driver named Macha.
        Your goal is to calm the driver and guide them safely. Use a brotherly tone (Tanglish/English).
        If the hazard is dangerous, mention the Law (MVA 2019) in a helpful way.
        Keep the alert strictly under 12 words.
        
        {context}
        {legal_info}
        
        Current Scenario: 
        Hazard: {hazard_type} at the {direction}.
        Severity: {severity}
        
        Generate the exact spoken phrase (no quotes, no thinking text, just the phrase):
        """
        
        if self.mode == "api":
            try:
                response = self.model.generate_content(prompt)
                phrase = response.text.strip()
                return phrase
            except Exception as e:
                logger.error(f"LLM API Failed: {e}")
                return self._fallback_phrase(hazard_type, severity, direction)
        else:
            return self._fallback_phrase(hazard_type, severity, direction)

    def _fallback_phrase(self, hazard_type, severity, direction):
        dir_text = "" if direction == "FRONT" else f" at the {direction.lower()}"
        if hazard_type == "POTHOLE":
            return f"Machaa, pothole incoming{dir_text}. Araam se, slow down."
        elif hazard_type == "SPEED_LIMIT":
            return f"Camera ahead da{dir_text}. Section 183 says lower your speed."
        else:
            return f"Careful macha, {hazard_type.lower()} detected{dir_text}. Eyes on the road."

# Single instance
voice_engine = GenerativeVoiceEngine()
