import json
import os
import time
import logging

logger = logging.getLogger("edge_sentinel.driver_memory")
logger.setLevel(logging.INFO)

class DriverMemoryManager:
    def __init__(self, profile_path="schemas/driver_profile.json"):
        # We need this to resolve relative paths regardless of CWD.
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self.profile_path = os.path.join(base_dir, profile_path)
        self.profile = self.load_profile()
        self.hard_brake_streak = 0
        self.smooth_riding_streak = 0

    def load_profile(self):
        if not os.path.exists(self.profile_path):
            logger.warning("No driver profile found, initializing empty.")
            return {"driving_skills": {"pros": [], "cons": []}, "recent_events": []}
        with open(self.profile_path, 'r') as f:
            return json.load(f)

    def save_profile(self):
        with open(self.profile_path, 'w') as f:
            json.dump(self.profile, f, indent=2)

    def get_context_for_llm(self):
        """Returns a string block summarizing the driver's persona for the LLM prompt."""
        p = self.profile
        context = f"Driver Identity: {p.get('name', 'User')}. "
        context += f"Languages: {', '.join(p.get('base_languages', ['English']))}. "
        context += f"Tone required: {p.get('preferred_tone', 'Casual')}. "
        context += f"Context: {p.get('daily_routine', 'Normal driving')}. "
        
        pros = ", ".join(p.get('driving_skills', {}).get('pros', []))
        cons = ", ".join(p.get('driving_skills', {}).get('cons', []))
        context += f"Driver Strengths: {pros}. Vulnerabilities: {cons}. "
        return context

    def process_telemetry(self, event_type, severity):
        """Dynamically updates pros/cons over time."""
        if event_type == "NEAR_MISS" and severity == "CRITICAL":
            self.hard_brake_streak += 1
            self.smooth_riding_streak = 0
            if self.hard_brake_streak > 3:
                new_con = "Exhibits frequent aggressive braking. Needs calming."
                if new_con not in self.profile['driving_skills']['cons']:
                    self.profile['driving_skills']['cons'].append(new_con)
                    self.save_profile()
                    logger.warning("DRIVER_MEMORY: Added new Con to profile (Aggressive Braking).")
        elif event_type == "SMOOTH_DRIVING":
            self.smooth_riding_streak += 1
            if self.smooth_riding_streak > 50:
                new_pro = "Consistent and smooth cruising."
                if new_pro not in self.profile['driving_skills']['pros']:
                    self.profile['driving_skills']['pros'].append(new_pro)
                    self.save_profile()
                    logger.info("DRIVER_MEMORY: Added new Pro to profile (Smooth Cruising).")

        # Keep a rotating log of recent events
        self.profile['recent_events'].append({"type": event_type, "ts": time.time()})
        self.profile['recent_events'] = self.profile['recent_events'][-10:] # Keep last 10
        self.save_profile()

# Global instance for easy injection
memory = DriverMemoryManager()
