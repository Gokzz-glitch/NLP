import aiohttp
import asyncio
import json
import logging
import os
from typing import Dict, Any, List
from pathlib import Path
from core.model_registry import GEMMA_GGUF_CANDIDATES, first_or_default

logger = logging.getLogger(__name__)


class LocalGemmaClient:
    """Best-effort local GGUF client for Gemma models."""

    @staticmethod
    def _int_env(name: str, default: int) -> int:
        try:
            return int(os.getenv(name, str(default)))
        except (TypeError, ValueError):
            return default

    def _resolve_gpu_layers(self) -> int:
        # Conservative default for 4GB-class cards; override with LOCAL_GEMMA_MAX_GPU_LAYERS.
        configured = self._int_env("LOCAL_GEMMA_MAX_GPU_LAYERS", 20)
        return max(0, configured)

    def __init__(self, model_path: str = None):
        default_path = first_or_default(
            GEMMA_GGUF_CANDIDATES,
            Path(__file__).resolve().parents[1] / "models" / "llm" / "gemma-2-2b-it-q4_k_m.gguf",
        )
        self.model_path = Path(model_path) if model_path else default_path
        self.enabled = self.model_path.exists()
        self._llm = None

        if not self.enabled:
            logger.info(f"LocalGemma: model not found at {self.model_path}")
            return

        try:
            from llama_cpp import Llama
            n_ctx = self._int_env("LOCAL_GEMMA_N_CTX", 768)
            n_gpu_layers = self._resolve_gpu_layers()
            self._llm = Llama(
                model_path=str(self.model_path),
                n_ctx=n_ctx,
                n_gpu_layers=n_gpu_layers,
                n_threads=1,
                verbose=False,
            )
            logger.info(
                "Aegis GPU LLM: loaded %s | n_ctx=%s | n_gpu_layers=%s",
                self.model_path.name,
                n_ctx,
                n_gpu_layers,
            )
        except Exception as exc:
            self._llm = None
            logger.warning(f"LocalGemma: GGUF runtime unavailable, using deterministic offline fallback ({exc})")

    def available(self) -> bool:
        return self.enabled

    async def infer(self, topic: str) -> Dict[str, Any]:
        if not self.enabled:
            return {
                "winner_model": "local-gemma-missing",
                "composite_score": 70,
                "response": f"Gemma model file not found at {self.model_path}.",
            }

        if self._llm is None:
            # Deterministic fallback when llama-cpp runtime isn't installed.
            return {
                "winner_model": f"{self.model_path.name} (offline-fallback)",
                "composite_score": 84,
                "response": (
                    "Local Gemma file is present and selected for offline mode. "
                    "Install llama-cpp-python to run full local inference; "
                    "until then, using deterministic offline guidance: prioritize "
                    "INT8 data pipeline stability, augmentation consistency, and LoRA-safe tuning budgets."
                ),
            }

        prompt = (
            "You are an offline research assistant for edge AI. "
            "Provide concise practical guidance for this topic in 3 bullets:\n"
            f"{topic}"
        )
        try:
            output = await asyncio.to_thread(
                self._llm,
                prompt,
                max_tokens=180,
                temperature=0.2,
                stop=["</s>", "\n\n\n"],
            )
            text = output["choices"][0]["text"].strip() if output.get("choices") else "No response"
            return {
                "winner_model": self.model_path.name,
                "composite_score": 88,
                "response": text,
            }
        except Exception as exc:
            logger.error(f"LocalGemma inference failed: {exc}")
            return {
                "winner_model": self.model_path.name,
                "composite_score": 75,
                "response": f"Local Gemma selected but inference failed: {exc}",
            }

class G0DM0D3Client:
    """
    Client for interacting with a locally running G0DM0D3 Node.js API instance.
    Uses 'ULTRAPLINIAN' or 'GODMODE CLASSIC' logic under the hood by querying the local API.
    """
    def __init__(self, base_url: str = None):
        self.base_url = base_url or os.getenv("GODMODE_BASE_URL", "http://127.0.0.1:7860")
        self.godmode_key = os.getenv("GODMODE_API_KEY") or os.getenv("GODMODE_KEY")
        self.openrouter_key = os.getenv("OPENROUTER_API_KEY")
        self.local_gemma = LocalGemmaClient(os.getenv("LOCAL_GEMMA_GGUF_PATH"))

    async def _post(self, endpoint: str, payload: Dict) -> Dict:
        headers = {}
        if self.godmode_key:
            headers["Authorization"] = f"Bearer {self.godmode_key}"
            
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(f"{self.base_url}/{endpoint}", json=payload, headers=headers) as response:
                    if response.status == 200:
                        return await response.json()
                    else:
                        text = await response.text()
                        logger.error(f"G0DM0D3 API Error: {response.status} - {text}")
                        return {"error": text}
        except Exception as e:
            logger.error(f"Failed to connect to G0DM0D3 Local Server at {self.base_url}: {e}")
            return {"error": str(e)}

    async def ultra_research(self, topic: str, max_models: int = 5) -> Dict[str, Any]:
        """
        Submits a research query to the local G0DM0D3 engine using multiple parallel models.
        """
        if self.local_gemma.available() and not self.openrouter_key and not self.godmode_key:
            logger.info("G0DM0D3Client: Using local Gemma offline path")
            return await self.local_gemma.infer(topic)

        payload = {
            "model": "ultraplinian/fast",
            "messages": [{"role": "user", "content": f"Conduct extensive state-of-the-art research on: {topic}. Output in JSON format with insights and citations."}]
        }
        if self.openrouter_key:
            payload["openrouter_api_key"] = self.openrouter_key
            
        result = await self._post("v1/chat/completions", payload)
        
        if "error" in result:
            if self.local_gemma.available():
                logger.info("G0DM0D3Client: API unavailable, falling back to local Gemma")
                return await self.local_gemma.infer(topic)
            # Production: Fail securely instead of returning mock data
            raise RuntimeError(
                "G0DM0D3 research unavailable: API down and local Gemma not available. "
                "Set GEMMA_OFFLINE_PATH env var or ensure G0DM0D3 server is running."
            )
        
        return result


class NotebookLMClientWrapper:
    """
    Async wrapper for notebooklm-py to automate deep document analysis.
    """
    def __init__(self):
        # We import notebooklm dynamically to avoid crashing if it's not installed globally yet
        try:
            from notebooklm import NotebookLMClient
            self.has_lib = True
            self.NotebookLMClient = NotebookLMClient
        except ImportError:
            self.has_lib = False
            logger.warning("notebooklm-py not installed. Falling back to mock implementation.")

    async def analyze_document(self, query: str, notebook_id: str = None) -> str:
        """
        Given a notebook_id (representing a collection of PDFs/URLs), perform an analysis query.
        """
        if not self.has_lib:
            return f"[Offline Mock] Deep analysis on query: '{query}' -> Extracted 3 key constraints from rulebook.pdf related to INT8 deployment on 4GB VRAM."
        
        try:
            # As per notebooklm-py documentation provided in the research
            async with await self.NotebookLMClient.from_storage() as client:
                if not notebook_id:
                    # Create a temporary one if none provided
                    nb = await client.notebooks.create("HACKATHON_RESEARCH_AUTO")
                    nb_id = nb.id
                else:
                    nb_id = notebook_id
                
                result = await client.chat.ask(nb_id, query)
                return result.answer
        except Exception as e:
            logger.error(f"NotebookLM API Error: {e}")
            return f"[Error] Analysis failed: {e}"

class GPUEmbeddingClient:
    """
    GPU-Accelerated Intelligence for agents to perform semantic search 
    and RAG without stressing the CPU.
    """
    def __init__(self):
        from core.gpu_manager import gpu_manager
        self._gpu = gpu_manager
        self.model_name = "all-MiniLM-L6-v2"
        self._model = None

    def _ensure_model(self):
        if self._model is None:
            self._model = self._gpu.get_shared_model(self.model_name)
        return self._model

    async def get_embedding(self, text: str):
        """Asynchronously compute vector on GPU 1."""
        model = self._ensure_model()
        if model is None: return [] # Fallback
        
        # Move to thread to keep asyncio loop free
        return await asyncio.to_thread(model.encode, text)

    async def compute_similarity(self, text_a: str, text_b: str):
        """Compare two findings using GPU vectors."""
        vec_a = await self.get_embedding(text_a)
        vec_b = await self.get_embedding(text_b)
        
        import numpy as np
        # Simple cosine similarity on the GPU result
        return np.dot(vec_a, vec_b) / (np.linalg.norm(vec_a) * np.linalg.norm(vec_b))

class UnifiedResearchClient:
    """
    Combines NotebookLM deep corpus analysis with G0DM0D3 parallel model validation.
    """
    def __init__(self):
        self.g3 = G0DM0D3Client()
        self.nlm = NotebookLMClientWrapper()
        
    async def synergistic_research(self, topic: str, context_query: str = None) -> Dict[str, Any]:
        logger.info(f"UnifiedResearch: Starting NotebookLM analysis for '{topic}'")
        if context_query is None:
            context_query = f"Extract key rules and constraints regarding {topic} from the rulebook or other local files."
            
        nlm_insight = await self.nlm.analyze_document(context_query)
        
        logger.info(f"UnifiedResearch: Passing NotebookLM context into G0DM0D3 for parallel evaluation")
        g3_query = f"Topic: {topic}\\nLocal Context/Constraints from NotebookLM: {nlm_insight}\\nBased on this context, what is the best architectural or strategic decision we can make?"
        g3_result = await self.g3.ultra_research(g3_query)
        
        return {
            "notebooklm_context": nlm_insight,
            "godmod3_validation": g3_result.get("response", g3_result.get("error", "No response")),
            "winner_model": g3_result.get("winner_model", "unknown")
        }

if __name__ == "__main__":
    async def test():
        urc = UnifiedResearchClient()
        res = await urc.synergistic_research("YOLOv8 Edge optimization")
        print("Unified Result:", json.dumps(res, indent=2))
        
    asyncio.run(test())
