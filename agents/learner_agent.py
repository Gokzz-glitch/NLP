import os
import time
import json
import logging
import hashlib
import random
import base64
import re
import urllib.request
import urllib.error
from pathlib import Path
from dotenv import load_dotenv
from typing import Dict, Any, List, Tuple, Optional

from core.secret_manager import get_manager
from scripts.road_scene_taxonomy import canonicalize_label, class_names

try:
    from google import genai as google_genai
except Exception:
    google_genai = None
legacy_genai = None

# [PERSONA 8: SELF-SUPERVISED LEARNER]
# Uses IMU spikes to trigger a "Self-Labeling" loop for Vision.
# Gemini 1.5 Flash acts as the 'Teacher' to verify the potholes detected by physics.

load_dotenv()
logger = logging.getLogger("edge_sentinel.learner")
logger.setLevel(logging.INFO)

class SelfSupervisedLearner:
    def __init__(self, data_dir: str = "raw_data/self_labeled/"):
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.api_keys = self._load_api_keys()
        self.api_key_index = 0
        self.model_name = os.getenv("GEMINI_MODEL", "gemini-flash-latest")
        self.scene_classes = class_names()
        self.scene_class_prompt = ", ".join(self.scene_classes)
        
        # ===== NEW: Per-key quota tracking instead of global backoff =====
        self.key_quota_backoff = {i: 0.0 for i in range(len(self.api_keys))}  # {key_idx: backoff_until_time}
        self.key_health = {i: {"successes": 0, "failures": 0, "last_quota_hit": 0} for i in range(len(self.api_keys))}
        self.quota_backoff_until = 0.0  # Global fallback (only set if ALL keys exhausted)

        # Optional local Gemma fallback (Ollama-compatible endpoint).
        self.gemma_enabled = os.getenv("GEMMA_VALIDATOR_ENABLED", "1").strip().lower() in {
            "1", "true", "yes", "on"
        }
        self.gemma_force_primary = os.getenv("GEMMA_VALIDATOR_FORCE_PRIMARY", "0").strip().lower() in {
            "1", "true", "yes", "on"
        }
        self.gemma_api_url = os.getenv("GEMMA_API_URL", "http://127.0.0.1:11434/api/generate")
        self.gemma_model = os.getenv("GEMMA_MODEL", "gemma4:latest")
        self.gemma_api_backoff_until = 0.0
        self.gemma_api_probe_interval_sec = float(os.getenv("GEMMA_API_PROBE_INTERVAL_SEC", "60"))

        sm = get_manager(strict_mode=False)
        self.godmode_enabled = os.getenv("GODMODE_VERIFIER_ENABLED", "1").strip().lower() in {
            "1", "true", "yes", "on"
        }
        self.godmode_base_url = os.getenv("GODMODE_BASE_URL", "http://127.0.0.1:7860").rstrip("/")
        self.godmode_key = sm.get("GODMODE_API_KEY") or os.getenv("GODMODE_KEY", "").strip()
        self.godmode_model = (
            os.getenv("GODMODE_VERIFIER_MODEL", "").strip()
            or os.getenv("GODMODE_CLASSIC_MODEL", "").strip()
            or "openai/gpt-4o"
        )
        self.openrouter_key = sm.get("OPENROUTER_API_KEY")
        self.consortium_enabled = os.getenv("CONSORTIUM_ENABLED", "1").strip().lower() in {"1", "true", "yes"}
        
        self.client = None

        # Configure Gemini Teacher
        if self.api_keys:
            self._configure_gemini_safe()
            logger.info(
                "PERSONA_8_REPORT: GEMINI_TEACHER_ONLINE | key_pool=%s | model=%s",
                len(self.api_keys),
                self.model_name,
            )
        else:
            self.model = None
            if self.gemma_enabled:
                logger.warning(
                    "PERSONA_8_REPORT: GEMINI_API_KEY_MISSING | using_gemma_fallback=%s | model=%s",
                    True,
                    self.gemma_model,
                )
            else:
                logger.warning("PERSONA_8_REPORT: GEMINI_API_KEY_MISSING (No Autolabeling)")

    @staticmethod
    def _extract_first_json_object(text: str) -> str:
        """Best-effort extraction of first JSON object from model text output."""
        if not text:
            return ""
        cleaned = text.replace("```json", "").replace("```", "").strip()
        match = re.search(r"\{.*\}", cleaned, flags=re.DOTALL)
        return match.group(0).strip() if match else cleaned

    @staticmethod
    def _coerce_float(value: Any, default: float = 0.0) -> float:
        try:
            return float(value)
        except Exception:
            return float(default)

    @staticmethod
    def _coerce_box(value: Any) -> List[float]:
        if not isinstance(value, (list, tuple)) or len(value) < 4:
            return [0.0, 0.0, 0.0, 0.0]
        box = []
        for item in value[:4]:
            try:
                box.append(float(item))
            except Exception:
                box.append(0.0)
        return box

    def _normalize_scene_verification(self, verification: Dict[str, Any]) -> Dict[str, Any]:
        raw_objects = verification.get("scene_objects") or verification.get("objects") or []
        if not isinstance(raw_objects, list):
            raw_objects = []

        if not raw_objects and verification.get("hazard_confirmed"):
            raw_objects = [{
                "class": verification.get("type", "other_road_object"),
                "confidence": verification.get("confidence", 0.0),
                "bounding_box": verification.get("bounding_box", [0, 0, 0, 0]),
            }]

        normalized_objects = []
        for raw_obj in raw_objects:
            if not isinstance(raw_obj, dict):
                continue
            class_name = canonicalize_label(raw_obj.get("class") or raw_obj.get("type") or raw_obj.get("name"))
            confidence = self._coerce_float(raw_obj.get("confidence", raw_obj.get("score", 0.0)))
            bounding_box = self._coerce_box(
                raw_obj.get("bounding_box") or raw_obj.get("bbox") or raw_obj.get("box")
            )
            normalized_objects.append({
                "class": class_name,
                "confidence": round(confidence, 3),
                "bounding_box": bounding_box,
            })

        if not normalized_objects and verification.get("hazard_confirmed"):
            normalized_objects.append({
                "class": canonicalize_label(verification.get("type", "other_road_object")),
                "confidence": round(self._coerce_float(verification.get("confidence", 0.0)), 3),
                "bounding_box": self._coerce_box(verification.get("bounding_box", [0, 0, 0, 0])),
            })

        if normalized_objects:
            primary = max(normalized_objects, key=lambda item: item.get("confidence", 0.0))
            verification["hazard_confirmed"] = True
            verification["type"] = primary["class"]
            verification["primary_class"] = primary["class"]
            verification["confidence"] = primary["confidence"]
            verification["bounding_box"] = primary["bounding_box"]
        else:
            verification["hazard_confirmed"] = bool(verification.get("hazard_confirmed", False))
            verification["type"] = canonicalize_label(verification.get("type", "other_road_object"))
            verification["primary_class"] = verification["type"]
            verification["confidence"] = round(self._coerce_float(verification.get("confidence", 0.0)), 3)
            verification["bounding_box"] = self._coerce_box(verification.get("bounding_box", [0, 0, 0, 0]))

        verification["scene_objects"] = normalized_objects
        verification["objects"] = normalized_objects
        return verification

    def _build_road_scene_prompt(self, imu_metadata: Dict[str, Any]) -> str:
        return f"""
You are an autonomous road-scene annotation assistant for a self-supervised driving vision loop.

Task: Review the dashcam frame and perform a multi-modal assessment.

Analysis Steps (Internal Reasoning):
1. Identification: Scanning for all objects in this taxonomy: {self.scene_class_prompt}
2. Metadata Context: Does the frame match the reported IMU impact? {json.dumps(imu_metadata)}
3. Verification: Are there visible potholes, road debris, accidents, or speed breakers?

Rules:
1. Return ALL visible objects that match the taxonomy.
2. Provide bounding boxes in normalized coordinates [ymin, xmin, ymax, xmax] (0-1000 scale).
3. Respond ONLY with JSON using this schema:
   {{
     "hazard_confirmed": boolean,
     "reasoning_steps": ["string", "string"],
     "primary_class": "string",
     "confidence": 0-1,
     "scene_objects": [
       {{"class": "string", "confidence": 0-1, "bounding_box": [ymin, xmin, ymax, xmax]}}
     ]
   }}
"""

    def _validate_with_gemma_local(self, frame_path: str, imu_metadata: Dict[str, Any]):
        """Local fallback verifier using Ollama-compatible Gemma multimodal endpoint."""
        if not self.gemma_enabled:
            return None

        image_file = Path(frame_path)
        if not image_file.exists():
            return None

        try:
            now = time.time()
            if now < self.gemma_api_backoff_until:
                return self._gemma_proxy_verification(imu_metadata)

            # Probe Ollama endpoint quickly before attempting multimodal call.
            probe_url = self.gemma_api_url.replace("/api/generate", "/api/tags")
            try:
                with urllib.request.urlopen(probe_url, timeout=2) as _:
                    pass
            except Exception:
                self.gemma_api_backoff_until = now + self.gemma_api_probe_interval_sec
                logger.warning(
                    "PERSONA_8_REPORT: GEMMA_ENDPOINT_UNAVAILABLE | probe_backoff_sec=%s",
                    int(self.gemma_api_probe_interval_sec),
                )
                return self._gemma_proxy_verification(imu_metadata)

            encoded = base64.b64encode(image_file.read_bytes()).decode("utf-8")
            prompt = self._build_road_scene_prompt(imu_metadata)

            payload = {
                "model": self.gemma_model,
                "prompt": prompt,
                "images": [encoded],
                "stream": False,
                "options": {"temperature": 0.1},
            }

            req = urllib.request.Request(
                self.gemma_api_url,
                data=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )

            with urllib.request.urlopen(req, timeout=60) as resp:
                body = resp.read().decode("utf-8", errors="ignore")
            outer = json.loads(body)
            text = outer.get("response", "")
            as_json = self._extract_first_json_object(text)
            verification = json.loads(as_json)

            if "hazard_confirmed" not in verification:
                return None

            verification = self._normalize_scene_verification(verification)

            logger.info(
                "PERSONA_8_REPORT: GEMMA_FALLBACK_VERIFIED | model=%s | hazard=%s | primary=%s | confidence=%s",
                self.gemma_model,
                verification.get("hazard_confirmed"),
                verification.get("primary_class"),
                verification.get("confidence"),
            )
            return verification
        except Exception as exc:
            logger.warning("PERSONA_8_REPORT: GEMMA_FALLBACK_ERROR | %s", exc)
            self.gemma_api_backoff_until = time.time() + self.gemma_api_probe_interval_sec
            return self._gemma_proxy_verification(imu_metadata)

    def _gemma_proxy_verification(self, imu_metadata: Dict[str, Any]):
        """Emergency offline fallback: keep SSL loop moving when no local Gemma server exists."""
        try:
            z_val = float((imu_metadata or {}).get("accel", {}).get("z", 0.0))
        except Exception:
            z_val = 0.0

        proxy_conf = max(0.0, min(1.0, z_val / 2.5))
        verification = {
            "hazard_confirmed": bool(proxy_conf >= 0.5),
            "type": "road_surface_anomaly",
            "primary_class": "road_surface_anomaly",
            "confidence": round(proxy_conf, 3),
            "bounding_box": [0, 0, 1000, 1000],
            "scene_objects": ([{
                "class": "road_surface_anomaly",
                "confidence": round(proxy_conf, 3),
                "bounding_box": [0, 0, 1000, 1000],
            }] if proxy_conf >= 0.5 else []),
            "fallback_mode": "gemma_offline_proxy",
        }
        logger.info(
            "PERSONA_8_REPORT: GEMMA_PROXY_VERIFIED | z=%s | confidence=%s | hazard=%s",
            round(z_val, 3),
            verification["confidence"],
            verification["hazard_confirmed"],
        )
        return verification

    def _load_api_keys(self):
        """Load Gemini API keys from secure SecretManager."""
        sm = get_manager(strict_mode=False)

        # Gemini verifier keys only. GODMODE verifier uses its own auth path.
        raw_keys = sm.get("GEMINI_API_KEYS").strip()

        if not raw_keys:
            for env_name in ("GEMINI_API_KEY",):
                single_key = sm.get(env_name)
                if single_key:
                    raw_keys = single_key
                    break
        
        if not raw_keys:
            logger.error(
                "❌ No SSL verifier API keys found. Set GEMINI_API_KEYS/GEMINI_API_KEY "
                "for Gemini verifier."
            )
            return []
        
        # Parse comma-separated keys and deduplicate
        keys = []
        seen = set()
        for key in [key.strip() for key in raw_keys.split(",") if key.strip()]:
            if key not in seen and len(key) > 10:  # Basic validation
                seen.add(key)
                keys.append(key)
        
        if keys:
            logger.info(f"✓ Loaded {len(keys)} Gemini API key(s) from SecretManager")
        else:
            logger.error("❌ No valid Gemini API keys found")
        
        return keys

    def _validate_with_godmode_local(self, frame_path: str, imu_metadata: Dict[str, Any]):
        """Fallback verifier using local G0DM0D3 OpenAI-compatible endpoint."""
        if not self.godmode_enabled:
            return None

        try:
            img_path = Path(frame_path)
            if not img_path.exists():
                return None

            encoded = base64.b64encode(img_path.read_bytes()).decode("utf-8")
            prompt = self._build_road_scene_prompt(imu_metadata)

            payload = {
                "model": self.godmode_model,
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": prompt},
                            {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{encoded}"}},
                        ],
                    }
                ],
            }
            if self.openrouter_key:
                payload["openrouter_api_key"] = self.openrouter_key

            headers = {
                "Content-Type": "application/json",
            }
            if self.godmode_key:
                headers["Authorization"] = f"Bearer {self.godmode_key}"

            req = urllib.request.Request(
                url=f"{self.godmode_base_url}/v1/chat/completions",
                data=json.dumps(payload).encode("utf-8"),
                headers=headers,
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=60) as resp:
                body = resp.read().decode("utf-8", errors="ignore")
                if int(getattr(resp, "status", 0)) != 200:
                    return None

            parsed = json.loads(body)
            content = (
                parsed.get("choices", [{}])[0]
                .get("message", {})
                .get("content", "")
            )
            as_json = self._extract_first_json_object(content)
            verification = json.loads(as_json)

            verification = self._normalize_scene_verification(verification)

            logger.info(
                "PERSONA_8_REPORT: GODMODE_VERIFIER_OK | model=%s | hazard=%s | primary=%s | confidence=%s",
                self.godmode_model,
                verification.get("hazard_confirmed"),
                verification.get("primary_class"),
                verification.get("confidence"),
            )
            return verification
        except Exception as exc:
            logger.warning("PERSONA_8_REPORT: GODMODE_VERIFIER_ERROR | %s", exc)
            return None

    def _consortium_verify(self, frame_path: str, imu_metadata: Dict[str, Any], use_free_tier: bool = True) -> Optional[Dict[str, Any]]:
        """
        G0DM0D3 Consortium (Hive-Mind) Verification.
        Queries models and synthesizes consensus decision.
        Defaults to 'free' tier to avoid credit consumption.
        """
        if not self.consortium_enabled or not self.godmode_key:
            return None
        
        prompt = self._build_road_scene_prompt(imu_metadata)
        
        url = f"{self.godmode_base_url}/v1/consortium/completions"
        tier = "free" if use_free_tier else "fast"
        orchestrator = "google/gemini-2.0-flash-exp:free" if use_free_tier else "anthropic/claude-3.5-sonnet"
        
        payload = {
            "messages": [{"role": "user", "content": prompt}],
            "openrouter_api_key": self.openrouter_key or self.godmode_key,
            "tier": tier,
            "godmode": True,
            "orchestrator_model": orchestrator,
            "contribute_to_dataset": False
        }

        try:
            req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"), 
                                         headers={"Authorization": f"Bearer {self.godmode_key}", 
                                                  "Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=90) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                synthesis = data.get("synthesis", "")
                
                # Parse JSON from synthesis text
                json_match = re.search(r'\{.*\}', synthesis, re.DOTALL)
                if json_match:
                    verification = json.loads(json_match.group(0))
                    verification = self._normalize_scene_verification(verification)
                    logger.info(f"📡 [CONSORTIUM_CONSENSUS] Hive-mind decision reached ({tier} tier)")
                    return verification
        except urllib.error.HTTPError as e:
            if e.code == 402: # Payment Required / Insufficient Credits
                if not use_free_tier:
                    logger.warning("💸 [CONSORTIUM] Paid tier blocked. Retrying with strictly FREE models...")
                    return self._consortium_verify(frame_path, imu_metadata, use_free_tier=True)
                else:
                    logger.error("🚨 [CONSORTIUM] Even FREE models are blocked or rate-limited.")
            else:
                logger.warning(f"⚠️ Consortium consensus failed (HTTP {e.code}): {e}")
        except Exception as e:
            logger.warning(f"⚠️ Consortium consensus failed: {e}")
        return None

    def _check_ollama_alive(self) -> bool:
        """Check if local Ollama server is responsive (Zero-Cost Hardening)."""
        try:
            url = f"http://{urllib.parse.urlparse(self.gemma_api_url).netloc}/api/tags"
            req = urllib.request.Request(url)
            with urllib.request.urlopen(req, timeout=1) as resp:
                return resp.status == 200
        except:
            return False

    def _fallback_verify(self, frame_path: str, imu_metadata: Dict[str, Any]):
        """
        Multimodal Verification Pyramid (Zero-Cost Optimized):
        1. Direct Gemini (Free Tier - Primary Teacher)
        2. Local Ollama (100% Free Hardware - Secondary Validator)
        3. G0DM0D3 Consortium (Hive-Mind, defaults to free tier)
        4. G0DM0D3 Single-Model (Paid, last resort)
        5. IMU-ONLY Fallback (Deterministic)
        """
        # --- 1. Direct Gemini (Free Tier) ---
        gemini_result = self._gemini_verify(frame_path, imu_metadata)
        if gemini_result:
            return gemini_result

        # --- 2. Local Ollama (Hardware-Accelerated Free) ---
        if self._check_ollama_alive():
            ollama_result = self._validate_with_gemma_local(frame_path, imu_metadata)
            if ollama_result:
                logger.info("🏠 [LOCAL_OLLAMA] Zero-cost verification successful")
                return ollama_result
        else:
            logger.debug("🏠 [LOCAL_OLLAMA] Server not responding. Skipping.")

        # --- 3. G0DM0D3 Consortium (Hive-Mind Consensus) ---
        if self.consortium_enabled:
            consensus = self._consortium_verify(frame_path, imu_metadata, use_free_tier=True)
            if consensus:
                return consensus

        # --- 4. Single-Model GODMODE (Paid Fallback) ---
        result = self._validate_with_godmode_local(frame_path, imu_metadata)
        if result is not None:
            return result
        
        # --- 5. IMU-ONLY Emergency Fail-safe ---
        return self._gemma_proxy_verification(imu_metadata)

    def _key_fingerprint(self, api_key: str) -> str:
        digest = hashlib.sha256(api_key.encode("utf-8")).hexdigest()
        return f"{digest[:8]}"

    def _configure_gemini(self, api_key: str):
        if google_genai is not None:
            self.client = google_genai.Client(api_key=api_key)
            self.model = self.model_name
        else:
            global legacy_genai
            if legacy_genai is None:
                try:
                    import google.generativeai as legacy_genai_module
                    legacy_genai = legacy_genai_module
                except Exception:
                    legacy_genai = None

            if legacy_genai is not None:
                legacy_genai.configure(api_key=api_key)
                self.client = None
                self.model = legacy_genai.GenerativeModel(self.model_name)
            else:
                raise ImportError("No Gemini SDK available")

    def _configure_gemini_safe(self):
        """Configure with a safe key, preferring non-throttled ones."""
        available = self._get_available_keys()
        if not available:
            # All keys in backoff - try the oldest one
            logger.warning("PERSONA_8_REPORT: ALL_KEYS_IN_BACKOFF | selecting least-throttled key")
            available = [0]  # Fallback to first key
        
        self.api_key_index = available[0]
        self._configure_gemini(self.api_keys[self.api_key_index])
        logger.info(
            "PERSONA_8_REPORT: GEMINI_KEY_ACTIVE | key_index=%s | key_fp=%s | model=%s | available_keys=%s",
            self.api_key_index,
            self._key_fingerprint(self.api_keys[self.api_key_index]),
            self.model_name,
            len(available),
        )

    def _get_available_keys(self) -> List[int]:
        """Return list of key indices that are NOT in quota backoff, sorted by health."""
        now = time.time()
        available = []
        
        for idx in range(len(self.api_keys)):
            if now >= self.key_quota_backoff.get(idx, 0.0):
                available.append(idx)
        
        if not available:
            return []
        
        # Sort by success rate (prefer healthier keys)
        def key_health_score(idx):
            health = self.key_health.get(idx, {})
            successes = health.get("successes", 0)
            failures = health.get("failures", 0)
            if successes + failures == 0:
                return 0
            return successes / (successes + failures)
        
        available.sort(key=key_health_score, reverse=True)
        return available

    def _select_key_randomly(self) -> int:
        """Randomly select from available keys, weighted by health."""
        available = self._get_available_keys()
        if not available:
            # All in backoff - return one with shortest backoff remaining
            min_idx = min(range(len(self.api_keys)), 
                         key=lambda i: self.key_quota_backoff.get(i, 0.0))
            return min_idx
        
        # If only one available, use it
        if len(available) == 1:
            return available[0]
        
        # Weighted random selection by health
        weights = []
        for idx in available:
            health = self.key_health.get(idx, {})
            successes = health.get("successes", 0)
            failures = health.get("failures", 0)
            # Weight = successes + 1 (so even new keys have chance)
            weights.append(max(1, successes + 1))
        
        return random.choices(available, weights=weights, k=1)[0]

    def _rotate_key(self):
        """Pick next available key (not sequential, random weighted selection)."""
        if not self.api_keys:
            return False
        
        next_idx = self._select_key_randomly()
        self.api_key_index = next_idx
        self._configure_gemini(self.api_keys[self.api_key_index])
        logger.warning(
            "PERSONA_8_REPORT: GEMINI_KEY_ROTATED | active_key_index=%s | key_fp=%s | pool_size=%s",
            self.api_key_index,
            self._key_fingerprint(self.api_keys[self.api_key_index]),
            len(self.api_keys),
        )
        return True

    def is_quota_backoff_active(self) -> bool:
        """Check if current key is in backoff, or if all keys are exhausted."""
        now = time.time()
        
        # Check per-key backoff for current key
        if self.api_key_index in self.key_quota_backoff:
            if now < self.key_quota_backoff[self.api_key_index]:
                return True
        
        # Check global emergency backoff
        if now < self.quota_backoff_until:
            return True
        
        return False

    def audit_jerk_event(self, frame_path: str, imu_metadata: Dict[str, Any]):
        """
        Main entry point for road-scene verification.
        Uses Zero-Cost priority: Gemini Free -> Fallback (Ollama, etc).
        """
        if self.gemma_force_primary and self.gemma_enabled:
            return self._validate_with_gemma_local(frame_path, imu_metadata)

        # 1. Try Gemini first (Shared logic)
        gemini_result = self._gemini_verify(frame_path, imu_metadata)
        if gemini_result:
            # Save verified sample
            sample_id = f"self_{int(time.time())}"
            sample_meta = {
                "id": sample_id,
                "imu": imu_metadata,
                "teacher_vqa": gemini_result,
                "timestamp": time.time(),
                "key_index": self.api_key_index,
                "key_fp": self._key_fingerprint(self.api_keys[self.api_key_index])
            }
            with open(self.data_dir / f"{sample_id}.json", "w") as f:
                json.dump(sample_meta, f, indent=2)
            return gemini_result

        # 2. Fallback to Ollama / Consortium / Godmode
        # Set skip_gemini=True since we just tried it and it failed.
        return self._fallback_verify(frame_path, imu_metadata, skip_gemini=True)

if __name__ == "__main__":
    # Test Mock Learner
    learner = SelfSupervisedLearner()
    print("Self-Supervised Learner Initialized.")
