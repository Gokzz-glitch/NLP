import os
import logging
from core.secret_manager import get_manager


logger = logging.getLogger("edge_sentinel.driver_companion")
logger.setLevel(logging.INFO)


class DriverCompanionAgent:
    """Friendly but direct co-driver agent (no sugar-coating)."""

    def __init__(self):
        sm = get_manager(strict_mode=False)
        self.api_key = sm.get("GEMINI_API_KEY")
        self.mode = "template"
        self.model = None

        if self.api_key:
            try:
                import google.generativeai as genai

                genai.configure(api_key=self.api_key)
                self.model = genai.GenerativeModel("gemini-1.5-flash")
                self.mode = "api"
                logger.info("✓ DRIVER_COMPANION: Cloud mode enabled (SecretManager)")
            except Exception as e:
                logger.warning(f"⚠️ DRIVER_COMPANION: API init failed, using template mode ({e})")

    def generate_message(self, hazard_type: str, severity: str, direction: str = "FRONT") -> str:
        hazard = (hazard_type or "GENERAL").upper()
        sev = (severity or "MEDIUM").upper()
        direction = (direction or "FRONT").upper()

        if self.mode == "api" and self.model is not None:
            prompt = f"""
You are a co-driver AI speaking to a real driver.
Tone rules:
- Friendly, calm, and respectful.
- Straight-forward and direct.
- Never sugar-coat danger.
- No drama, no fluff.
- Keep under 14 words.

Scenario:
- Hazard: {hazard}
- Severity: {sev}
- Direction: {direction}

Return only one spoken sentence.
"""
            try:
                response = self.model.generate_content(prompt)
                text = (response.text or "").strip()
                if text:
                    return text
            except Exception as e:
                logger.warning(f"DRIVER_COMPANION: API generation failed ({e})")

        return self._template_message(hazard, sev, direction)

    def _template_message(self, hazard: str, severity: str, direction: str) -> str:
        dir_text = "ahead" if direction == "FRONT" else f"on your {direction.lower()}"

        if hazard in {"CONFIRMED_POTHOLE_STRIKE", "POTHOLE"}:
            if severity == "CRITICAL":
                return f"Big pothole {dir_text}. Slow down now, keep both hands steady."
            return f"Pothole {dir_text}. Reduce speed and hold your lane."

        if hazard in {"ACCIDENT", "CRASH", "COLLISION"}:
            return f"Accident risk {dir_text}. Brake smoothly and increase following distance."

        if hazard in {"SPEED_LIMIT", "OVERSPEED"}:
            return f"You are over speed. Drop speed now and stay compliant."

        if hazard in {"LEGAL_SIGN_MISSING", "REGULATORY_CONFLICT"}:
            return f"Signage conflict detected. Drive cautiously and record this segment."

        if severity == "CRITICAL":
            return f"Critical hazard {dir_text}. Slow down now and stay focused."
        return f"Hazard {dir_text}. Stay alert and adjust speed."


driver_companion = DriverCompanionAgent()
