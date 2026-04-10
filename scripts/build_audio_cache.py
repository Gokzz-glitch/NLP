import json
import logging
import re
from pathlib import Path

import pyttsx3


logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger("build_audio_cache")

CACHE_DIR = Path("mobile/assets/audio")
INDEX_PATH = CACHE_DIR / "index.json"

TOP_50_CRITICAL_ALERTS = [
    "Macha, severe pothole 50m ahead. Slow down now.",
    "Warning, speed camera detected. No legal signage visible.",
    "Caution, auto-rickshaw swerving left. Keep distance.",
    "Macha, accident risk ahead. Brake smoothly now.",
    "Critical hazard front. Hold lane and reduce speed.",
    "Macha, deep pothole right lane. Move left carefully.",
    "Warning, road construction ahead. Expect sudden blocks.",
    "Macha, pedestrian crossing suddenly. Slow down immediately.",
    "Caution, biker cutting in from left. Stay steady.",
    "Warning, bus merging aggressively. Give more space.",
    "Macha, waterlogging ahead. Traction may drop.",
    "Critical, blind curve ahead. No signboard seen.",
    "Warning, broken divider ahead. Keep center lane.",
    "Macha, stalled vehicle ahead. Prepare to stop.",
    "Caution, wrong-side rider detected. Keep left.",
    "Warning, school zone ahead. Reduce speed now.",
    "Macha, heavy congestion ahead. Avoid sudden braking.",
    "Critical, lane markings missing. Drive cautiously.",
    "Warning, speed bump unmarked ahead.",
    "Macha, sharp turn ahead. Slow and steady.",
    "Caution, dog crossing ahead. Be alert.",
    "Warning, truck blind spot near left. Do not overtake.",
    "Macha, oil spill suspected on road. Avoid hard braking.",
    "Critical, near miss event detected. Slow down now.",
    "Warning, signal jump hotspot ahead. Stay compliant.",
    "Macha, pothole cluster detected. Keep speed low.",
    "Caution, lane violation camera ahead.",
    "Warning, no parking obstruction ahead. Narrow passage.",
    "Macha, emergency vehicle approaching. Give way left.",
    "Critical, intersection conflict ahead. Prepare to halt.",
    "Warning, blackspot area entered. Max caution.",
    "Macha, bridge expansion joint ahead. Hold steering firm.",
    "Caution, gravel patch ahead. Reduce throttle.",
    "Warning, uneven road surface detected.",
    "Macha, rain plus pothole risk high. Slow down.",
    "Critical, tailgater detected behind. Avoid hard brake.",
    "Warning, U-turn vehicle ahead. Keep safe gap.",
    "Macha, zebra crossing occupied. Stop and wait.",
    "Caution, side road merge from right.",
    "Warning, blind pedestrian zone ahead.",
    "Macha, legal signage missing in speed zone.",
    "Critical, collision probability rising. Brake now.",
    "Warning, road shoulder collapse risk ahead.",
    "Macha, diversion ahead. Follow lane cones.",
    "Caution, sudden slowdown traffic ahead.",
    "Warning, parked lorry blocking left lane.",
    "Macha, two-wheeler weaving ahead. Keep distance.",
    "Critical, pothole strike risk immediate.",
    "Warning, high-speed bike approaching from rear.",
    "Macha, stay focused. Hazard density high in this stretch.",
]


def _slugify(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", text.lower())
    slug = re.sub(r"_+", "_", slug).strip("_")
    return slug[:96] if len(slug) > 96 else slug


def _normalize_phrase(text: str) -> str:
    return " ".join((text or "").strip().lower().split())


def build_cache() -> int:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)

    engine = pyttsx3.init()
    engine.setProperty("rate", 150)

    index = {}

    for idx, phrase in enumerate(TOP_50_CRITICAL_ALERTS, start=1):
        key = _slugify(phrase)
        filename = f"alert_{idx:02d}_{key}.wav"
        output_path = CACHE_DIR / filename

        logger.info("Rendering %d/50: %s", idx, phrase)
        engine.save_to_file(phrase, str(output_path))

        index[_normalize_phrase(phrase)] = {
            "file": filename,
            "priority": "CRITICAL",
            "phrase": phrase,
        }

    engine.runAndWait()

    with INDEX_PATH.open("w", encoding="utf-8") as fh:
        json.dump(index, fh, indent=2)

    logger.info("Audio cache built at: %s", CACHE_DIR)
    logger.info("Index file: %s", INDEX_PATH)
    return len(index)


if __name__ == "__main__":
    count = build_cache()
    print(f"Built cache entries: {count}")
