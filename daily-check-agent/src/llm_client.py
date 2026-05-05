"""Ollama LLM client — supports both /api/generate and /api/chat endpoints."""

import json
import os
import time
import requests

CHAT_URL_SUFFIX = "/api/chat"
GENERATE_URL_SUFFIX = "/api/generate"


class LLMResponse:
    """LLM 응답 + 메타데이터 컨테이너"""
    def __init__(self, content: str, prompt_tokens: int = 0, response_tokens: int = 0, elapsed: float = 0.0):
        self.content = content
        self.prompt_tokens = prompt_tokens
        self.response_tokens = response_tokens
        self.elapsed = elapsed

    def __str__(self):
        return self.content


def _load_template(path: str) -> str:
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


class OllamaClient:
    def __init__(self, url: str, model: str, temperature: float = 0.3, num_predict: int = 1024,
                 templates_dir: str = "templates",
                 prompt_analyze_file: str = "prompt_analyze.txt",
                 prompt_system_file: str = "prompt_system.txt"):
        self.generate_url = url
        self.chat_url = url.replace(GENERATE_URL_SUFFIX, CHAT_URL_SUFFIX)
        self.model = model
        self.temperature = temperature
        self.num_predict = num_predict

        self._prompt_analyze_tpl = _load_template(os.path.join(templates_dir, prompt_analyze_file))
        self._prompt_system_tpl = _load_template(os.path.join(templates_dir, prompt_system_file))

    def analyze(self, summary: dict) -> LLMResponse:
        prompt = self._build_prompt(summary)
        t0 = time.time()
        try:
            resp = requests.post(
                self.generate_url,
                json={
                    "model": self.model,
                    "prompt": prompt,
                    "stream": False,
                    "options": {
                        "temperature": self.temperature,
                        "num_predict": self.num_predict,
                    },
                },
                timeout=120,
            )
            resp.raise_for_status()
            data = resp.json()
            return LLMResponse(
                content=data.get("response", "").strip(),
                prompt_tokens=data.get("prompt_eval_count", 0),
                response_tokens=data.get("eval_count", 0),
                elapsed=time.time() - t0,
            )
        except requests.exceptions.ConnectionError:
            return LLMResponse("[LLM 오류] Ollama 서버에 연결할 수 없습니다. `ollama serve` 또는 `brew services start ollama`를 실행하세요.")
        except requests.exceptions.Timeout:
            return LLMResponse("[LLM 오류] Ollama 응답 시간 초과 (120초).")
        except Exception as e:
            return LLMResponse(f"[LLM 오류] {e}")

    def chat(self, messages: list) -> LLMResponse:
        """Multi-turn chat via /api/chat endpoint."""
        t0 = time.time()
        try:
            resp = requests.post(
                self.chat_url,
                json={
                    "model": self.model,
                    "messages": messages,
                    "stream": False,
                    "options": {
                        "temperature": self.temperature,
                        "num_predict": self.num_predict,
                    },
                },
                timeout=120,
            )
            resp.raise_for_status()
            data = resp.json()
            return LLMResponse(
                content=data["message"]["content"].strip(),
                prompt_tokens=data.get("prompt_eval_count", 0),
                response_tokens=data.get("eval_count", 0),
                elapsed=time.time() - t0,
            )
        except requests.exceptions.ConnectionError:
            return LLMResponse("[LLM 오류] Ollama 서버에 연결할 수 없습니다.")
        except requests.exceptions.Timeout:
            return LLMResponse("[LLM 오류] Ollama 응답 시간 초과 (120초).")
        except Exception as e:
            return LLMResponse(f"[LLM 오류] {e}")

    def _build_prompt(self, summary: dict) -> str:
        servers_text = json.dumps(summary, ensure_ascii=False, indent=2)
        return self._prompt_analyze_tpl.format(servers_text=servers_text)

    def build_system_message(self, summary: dict) -> str:
        servers_text = json.dumps(summary, ensure_ascii=False, indent=2)
        return self._prompt_system_tpl.format(servers_text=servers_text)
