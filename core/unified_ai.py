import os
import json
import base64
import time
import requests
import google.generativeai as genai
from PIL import Image
import io
import logging

logger = logging.getLogger(__name__)

class UnifiedAI:
    """
    Unified interface for multiple AI providers to handle vision and text completions.
    Supports Google Gemini (native SDK) and OpenAI-compatible providers (OpenRouter, Groq, Mistral).
    """
    def __init__(self):
        # Gemini setup
        self.gemini_keys = [k.strip() for k in os.getenv("GEMINI_API_KEYS", "").split(",") if k.strip()]
        if not self.gemini_keys and os.getenv("GEMINI_API_KEY"):
            self.gemini_keys = [os.getenv("GEMINI_API_KEY").strip()]
        
        # OpenAI-compatible providers setup
        self.providers = {
            "openrouter": {
                "key": os.getenv("OPENROUTER_API_KEY"),
                "url": "https://openrouter.ai/api/v1/chat/completions",
                "default_model": "google/gemini-2.0-flash-lite-preview-02-05:free"
            },
            "groq": {
                "key": os.getenv("GROQ_API_KEY"),
                "url": "https://api.groq.com/openai/v1/chat/completions",
                "default_model": "llama-3.2-11b-vision-preview" # Common free vision model on Groq
            },
            "mistral": {
                "key": os.getenv("MISTRAL_API_KEY"),
                "url": "https://api.mistral.ai/v1/chat/completions",
                "default_model": "pixtral-12b-2409"
            },
            "together": {
                "key": os.getenv("TOGETHER_API_KEY"),
                "url": "https://api.together.xyz/v1/chat/completions",
                "default_model": "meta-llama/Llama-Vision-Free"
            }
        }
        
        # Remove providers without keys
        self.active_providers = [p for p, cfg in self.providers.items() if cfg["key"]]
        self.current_provider_idx = 0
        self.current_gemini_idx = 0

    def _get_next_provider(self):
        if not self.active_providers:
            return None
        p = self.active_providers[self.current_provider_idx % len(self.active_providers)]
        self.current_provider_idx += 1
        return p

    def _get_next_gemini_key(self):
        if not self.gemini_keys:
            return None
        key = self.gemini_keys[self.current_gemini_idx % len(self.gemini_keys)]
        self.current_gemini_idx += 1
        return key

    def generate_vision_completion(self, prompt, image_data, prefer_provider=None):
        """
        Generates a completion using an image. 
        image_data can be a numpy array (OpenCV frame) or a PIL Image.
        """
        # Convert image to b64 for OpenAI-compatible and PIL for Gemini
        import numpy as np
        import cv2

        if isinstance(image_data, np.ndarray):
            # OpenCV frame
            _, buffer = cv2.imencode('.jpg', image_data)
            b64_img = base64.b64encode(buffer).decode('utf-8')
            pil_img = Image.open(io.BytesIO(buffer))
        elif isinstance(image_data, Image.Image):
            # PIL Image
            buffered = io.BytesIO()
            image_data.save(buffered, format="JPEG")
            b64_img = base64.b64encode(buffered.getvalue()).decode('utf-8')
            pil_img = image_data
        else:
            raise ValueError("Unsupported image format")

        # Try Providers in order: Prefer native Gemini first (if available), then the rest
        max_retries = len(self.gemini_keys) + len(self.active_providers)
        
        for _ in range(max_retries):
            # 1. Try Gemini Native if keys exist and not forced to a provider
            if self.gemini_keys and prefer_provider != "external":
                key = self._get_next_gemini_key()
                try:
                    genai.configure(api_key=key)
                    model = genai.GenerativeModel('models/gemini-1.5-flash-latest')
                    response = model.generate_content([prompt, pil_img])
                    return self._clean_json_output(response.text)
                except Exception as e:
                    logger.warning(f"Native Gemini failed (key_fp={key[:8]}...): {e}")
            
            # 2. Try External Providers
            provider_name = self._get_next_provider()
            if not provider_name:
                continue
                
            cfg = self.providers[provider_name]
            try:
                payload = {
                    "model": cfg["default_model"],
                    "messages": [
                        {
                            "role": "user",
                            "content": [
                                {"type": "text", "text": prompt},
                                {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64_img}"}}
                            ]
                        }
                    ],
                    "response_format": {"type": "json_object"}
                }
                headers = {
                    "Authorization": f"Bearer {cfg['key']}",
                    "Content-Type": "application/json"
                }
                
                resp = requests.post(cfg["url"], json=payload, headers=headers, timeout=30)
                if resp.status_code == 200:
                    data = resp.json()
                    content = data['choices'][0]['message']['content']
                    return self._clean_json_output(content)
                else:
                    logger.warning(f"Provider {provider_name} failed: {resp.status_code} - {resp.text}")
            except Exception as e:
                logger.warning(f"Provider {provider_name} exception: {e}")

        raise RuntimeError("All AI providers failed to generate a response.")

    def _clean_json_output(self, text):
        """Extracts JSON from markdown code blocks if necessary."""
        text = text.strip()
        if "```json" in text:
            text = text.split("```json")[1].split("```")[0].strip()
        elif "```" in text:
            text = text.split("```")[1].split("```")[0].strip()
        
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            # Try a stricter regex or just return the text if it's already a dict (not possible here)
            return text

if __name__ == "__main__":
    # Test stub
    from dotenv import load_dotenv
    load_dotenv()
    ui = UnifiedAI()
    print(f"Active external providers: {ui.active_providers}")
    print(f"Gemini keys: {len(ui.gemini_keys)}")
