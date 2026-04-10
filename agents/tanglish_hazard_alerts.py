# [PERSONA 4: THE HYPER-LOCAL VOCODER]
# Task: Finalize Tanglish phrase mapping for hazard alerts.

TANGLISH_HAZARD_MAP = {
    "POTHOLE": [
        "Macha, slow down, pothole ahead!",
        "Pothole irukku da, paathu po!",
        "Big pothole ahead, don't break your suspension macha."
    ],
    "SPEED_LIMIT": [
        "Macha, speed trap ahead. Slow down!",
        "Over speed pogaatha da, camera irukku.",
        "Keep it under 60 macha, fine kudukka poreeya?"
    ],
    "ACCIDENT_PRONE": [
        "Blackspot ahead. Be careful macha.",
        "Inga accident zone da, extra alert-ah iru.",
        "Macha, this area is risky, keep distance."
    ],
    "LANE_VIOLATION": [
        "Stay in your lane macha, rules follow pannu.",
        "Lane maaratha da, sentinel is watching.",
        "Proper-ah lane-la po macha."
    ]
}

def get_tanglish_alert(hazard_type, severity=0):
    import random
    phrases = TANGLISH_HAZARD_MAP.get(hazard_type.upper(), ["Macha, be careful!"])
    return random.choice(phrases)

if __name__ == "__main__":
    # Test
    print(f"ALERT: {get_tanglish_alert('POTHOLE')}")
    print(f"ALERT: {get_tanglish_alert('SPEED_LIMIT')}")
