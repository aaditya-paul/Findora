import os
import logging
from enum import Enum
from typing import Optional

try:
    import httpx
except ImportError:
    pass

log = logging.getLogger(__name__)

class DeprecatedModelError(Exception):
    pass

class Provider(str, Enum):
    NVIDIA = "nvidia"
    GEMINI = "gemini"
    GROQ   = "groq"
    OLLAMA = "ollama"

class LLMRouter:
    FALLBACK_ORDER = [Provider.NVIDIA, Provider.GEMINI, Provider.GROQ, Provider.OLLAMA]

    NVIDIA_BASE_URL = "https://integrate.api.nvidia.com/v1"
    NVIDIA_MODELS = {
        "orchestrator": "nvidia/llama-3.3-nemotron-super-49b-v1.5",
        "fast":         "nvidia/nvidia-nemotron-nano-9b-v2",
        "vision":       "meta/llama-3.2-11b-vision-instruct",
    }

    GEMINI_MODELS = {
        "default":   "gemini-2.5-flash-lite",
        "standard":  "gemini-2.5-flash",
        "reasoning": "gemini-2.5-pro",
    }

    GROQ_BASE_URL = "https://api.groq.com/openai/v1"
    GROQ_MODELS = {
        "orchestrator": "llama-3.3-70b-versatile",
        "fast":         "llama-3.1-8b-instant",
        "vision":       "llama-3.2-11b-vision-preview",
        "fallback":     "gemma2-9b-it",
        "default":      "llama-3.3-70b-versatile",
    }

    OLLAMA_BASE_URL = "http://localhost:11434/v1"
    OLLAMA_MODELS = {
        "default":   "qwen2.5:7b",
        "vision":    "qwen2.5vl:3b",
        "vision_hq": "qwen2.5vl:7b",
        "embed":     "nomic-embed-text",
        "fallback":  "qwen2.5:1.5b",
    }

    DEFAULT_MODELS = {
        Provider.NVIDIA: NVIDIA_MODELS["orchestrator"],
        Provider.GEMINI: GEMINI_MODELS["default"],
        Provider.GROQ:   GROQ_MODELS["default"],
        Provider.OLLAMA: OLLAMA_MODELS["default"],
    }

    def __init__(self, preferred: str = "auto", model_override: Optional[str] = None):
        self.preferred = preferred
        self.model_override = model_override

    def _check_nvidia(self) -> bool:
        return bool(os.getenv("NVIDIA_API_KEY"))

    def _check_gemini(self) -> bool:
        return bool(os.getenv("GEMINI_API_KEY"))

    def _check_groq(self) -> bool:
        return bool(os.getenv("GROQ_API_KEY"))

    def _check_ollama(self) -> bool:
        try:
            r = httpx.get("http://localhost:11434/api/tags", timeout=2)
            return r.status_code == 200
        except Exception:
            return False

    def get_provider(self) -> Provider:
        if self.preferred != "auto":
            return Provider(self.preferred)
        checks = {
            Provider.NVIDIA: self._check_nvidia,
            Provider.GEMINI: self._check_gemini,
            Provider.GROQ:   self._check_groq,
            Provider.OLLAMA: self._check_ollama,
        }
        for p in self.FALLBACK_ORDER:
            if checks[p]():
                log.info(f"LLM router selected: {p.value}")
                return p
        return Provider.OLLAMA

    def get_model(self, provider: Provider, task: str = "default") -> str:
        if self.model_override:
            if "gemini-2.0-flash" in self.model_override:
                raise DeprecatedModelError("gemini-2.0-flash is retired. Use gemini-2.5-flash.")
            return self.model_override
        if provider == Provider.GEMINI:
            return self.GEMINI_MODELS.get(task, self.GEMINI_MODELS["default"])
        if provider == Provider.NVIDIA:
            return self.NVIDIA_MODELS.get(task, self.NVIDIA_MODELS["orchestrator"])
        if provider == Provider.GROQ:
            return self.GROQ_MODELS.get(task, self.GROQ_MODELS["default"])
        if provider == Provider.OLLAMA:
            return self.OLLAMA_MODELS.get(task, self.OLLAMA_MODELS["default"])
        return self.OLLAMA_MODELS["fallback"]

    def complete(self, messages: list[dict], task: str = "default", json_mode: bool = False) -> tuple[str, str, str]:
        """Returns (response_text, provider_used, model_used)"""
        provider = self.get_provider()
        model = self.get_model(provider, task)
        log.info(f"Calling {provider.value} / {model}")
        response = self._dispatch(provider, model, messages, json_mode)
        return response, provider.value, model

    def complete_vision(self, messages: list[dict]) -> tuple[str, str, str]:
        provider = self.get_provider()
        if provider == Provider.NVIDIA:
            model = self.NVIDIA_MODELS["vision"]
            resp = self._call_openai_compat(
                self.NVIDIA_BASE_URL, os.getenv("NVIDIA_API_KEY", ""),
                model, messages, json_mode=True
            )
            return resp, provider.value, model
        elif provider == Provider.GEMINI:
            model = self.GEMINI_MODELS["standard"]
            resp = self._call_gemini(model, messages, json_mode=True)
            return resp, provider.value, model
        elif provider == Provider.GROQ:
            model = self.GROQ_MODELS["vision"]
            resp = self._call_openai_compat(
                self.GROQ_BASE_URL, os.getenv("GROQ_API_KEY", ""),
                model, messages, json_mode=True
            )
            return resp, provider.value, model
        else:
            model = self._pick_vision_model()
            resp = self._call_openai_compat(
                self.OLLAMA_BASE_URL, "ollama",
                model, messages, json_mode=True
            )
            return resp, provider.value, model

    def _pick_vision_model(self) -> str:
        import subprocess
        try:
            out = subprocess.check_output(
                ["nvidia-smi", "--query-gpu=memory.free", "--format=csv,noheader,nounits"],
                text=True
            )
            free_mb = int(out.strip().split("\n")[0])
            if free_mb >= 4800:
                return self.OLLAMA_MODELS["vision_hq"]
            elif free_mb >= 2200:
                return self.OLLAMA_MODELS["vision"]
            else:
                return self.OLLAMA_MODELS["vision"]
        except Exception:
            return self.OLLAMA_MODELS["vision"]

    def _dispatch(self, provider, model, messages, json_mode):
        if provider == Provider.NVIDIA:
            return self._call_openai_compat(
                self.NVIDIA_BASE_URL, os.getenv("NVIDIA_API_KEY", ""),
                model, messages, json_mode
            )
        elif provider == Provider.GEMINI:
            return self._call_gemini(model, messages, json_mode)
        elif provider == Provider.GROQ:
            return self._call_openai_compat(
                self.GROQ_BASE_URL, os.getenv("GROQ_API_KEY", ""),
                model, messages, json_mode
            )
        else:
            return self._call_openai_compat(
                self.OLLAMA_BASE_URL, "ollama",
                model, messages, json_mode
            )

    def _call_openai_compat(self, base_url, api_key, model, messages, json_mode) -> str:
        from openai import OpenAI
        client = OpenAI(base_url=base_url, api_key=api_key)
        kwargs = dict(model=model, messages=messages, temperature=0.3)
        if json_mode:
            kwargs["response_format"] = {"type": "json_object"}
        if "nemotron" in model and not json_mode:
            kwargs["temperature"] = 0.6
            kwargs["top_p"] = 0.95
            
        resp = client.chat.completions.create(**kwargs)
        return resp.choices[0].message.content

    def _call_gemini(self, model, messages, json_mode) -> str:
        import google.generativeai as genai
        import time
        from app.llm.gemini_guard import rate_guard
        
        genai.configure(api_key=os.getenv("GEMINI_API_KEY"))
        m = genai.GenerativeModel(model)
        
        # Rate Limiting check
        level = "default"
        if "flash" in model and "lite" not in model:
            level = "standard"
        elif "pro" in model:
            level = "reasoning"
            
        if not rate_guard.can_request(level):
            log.warning(f"Gemini {level} RPM exceeded. Backing off 5s.")
            time.sleep(5)
            
        rate_guard.record_request(level)
                
        prompt = "\n".join(f"{msg['role']}: {msg['content']}"
                           for msg in messages
                           if isinstance(msg.get("content"), str))
        config = genai.GenerationConfig(
            response_mime_type="application/json" if json_mode else "text/plain"
        )
        try:
            resp = m.generate_content(prompt, generation_config=config)
            return resp.text
        except Exception as e:
            if "429" in str(e):
                log.warning("Gemini 429 rate limit exceeded. Retrying after delay...")
                time.sleep(5)
                resp = m.generate_content(prompt, generation_config=config)
                return resp.text
            raise e
