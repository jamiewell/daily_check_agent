"""LLM clients: OllamaClient (/api/generate + /api/chat), LlamaCppClient (/v1/chat/completions)."""

import json
import os
import time
import requests

from src import debug_logger as dbg

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

        dbg.log_step(f"템플릿 로드: {templates_dir}/{prompt_analyze_file}, {prompt_system_file}")
        self._prompt_analyze_tpl = _load_template(os.path.join(templates_dir, prompt_analyze_file))
        self._prompt_system_tpl  = _load_template(os.path.join(templates_dir, prompt_system_file))

    def analyze(self, summary: dict, comparison: dict = None) -> LLMResponse:
        prompt = self._build_prompt(summary, comparison)
        payload = {
            "model": self.model,
            "prompt": prompt,
            "stream": False,
            "options": {"temperature": self.temperature, "num_predict": self.num_predict},
        }
        dbg.log_request("Ollama /api/generate", self.generate_url, payload)
        t0 = time.time()
        try:
            resp = requests.post(self.generate_url, json=payload, timeout=120)
            resp.raise_for_status()
            data = resp.json()
            elapsed = time.time() - t0
            dbg.log_response("Ollama /api/generate", resp.status_code, data, elapsed)
            return LLMResponse(
                content=data.get("response", "").strip(),
                prompt_tokens=data.get("prompt_eval_count", 0),
                response_tokens=data.get("eval_count", 0),
                elapsed=elapsed,
            )
        except requests.exceptions.ConnectionError as e:
            dbg.log_error("Ollama ConnectionError", e)
            return LLMResponse("[LLM 오류] Ollama 서버에 연결할 수 없습니다. `ollama serve` 또는 `brew services start ollama`를 실행하세요.")
        except requests.exceptions.Timeout as e:
            dbg.log_error("Ollama Timeout", e)
            return LLMResponse("[LLM 오류] Ollama 응답 시간 초과 (120초).")
        except Exception as e:
            dbg.log_error("Ollama 알 수 없는 오류", e)
            return LLMResponse(f"[LLM 오류] {e}")

    def chat(self, messages: list) -> LLMResponse:
        """Multi-turn chat via /api/chat endpoint."""
        payload = {
            "model": self.model,
            "messages": messages,
            "stream": False,
            "options": {"temperature": self.temperature, "num_predict": self.num_predict},
        }
        dbg.log_request("Ollama /api/chat", self.chat_url, payload)
        t0 = time.time()
        try:
            resp = requests.post(self.chat_url, json=payload, timeout=120)
            resp.raise_for_status()
            data = resp.json()
            elapsed = time.time() - t0
            dbg.log_response("Ollama /api/chat", resp.status_code, data, elapsed)
            return LLMResponse(
                content=data["message"]["content"].strip(),
                prompt_tokens=data.get("prompt_eval_count", 0),
                response_tokens=data.get("eval_count", 0),
                elapsed=elapsed,
            )
        except requests.exceptions.ConnectionError as e:
            dbg.log_error("Ollama ConnectionError", e)
            return LLMResponse("[LLM 오류] Ollama 서버에 연결할 수 없습니다.")
        except requests.exceptions.Timeout as e:
            dbg.log_error("Ollama Timeout", e)
            return LLMResponse("[LLM 오류] Ollama 응답 시간 초과 (120초).")
        except Exception as e:
            dbg.log_error("Ollama 알 수 없는 오류", e)
            return LLMResponse(f"[LLM 오류] {e}")

    def _build_prompt(self, summary: dict, comparison: dict = None) -> str:
        from src.comparator import comparison_text as make_comparison_text
        servers_text = json.dumps(summary, ensure_ascii=False, indent=2)
        cmp_text = make_comparison_text(comparison) if comparison else "(전일 데이터 없음)"
        return self._prompt_analyze_tpl.format(
            servers_text=servers_text,
            comparison_text=cmp_text,
        )

    def build_system_message(self, summary: dict) -> str:
        servers_text = json.dumps(summary, ensure_ascii=False, indent=2)
        return self._prompt_system_tpl.format(servers_text=servers_text)


class LlamaCppClient:
    """llama.cpp llama-server OpenAI 호환 API 클라이언트 (/v1/chat/completions).

    Ollama 대신 llama-server.exe 를 사용하는 폐쇄망·저사양 PC 데모용.
    """

    def __init__(self, host: str = "127.0.0.1", port: int = 8080,
                 temperature: float = 0.3, max_tokens: int = 512,
                 templates_dir: str = "templates",
                 prompt_analyze_file: str = "prompt_analyze.txt",
                 prompt_system_file: str = "prompt_system.txt"):
        self.url = f"http://{host}:{port}/v1/chat/completions"
        self.temperature = temperature
        self.max_tokens = max_tokens

        dbg.log_step(f"템플릿 로드 (LlamaCpp): {templates_dir}/{prompt_analyze_file}")
        self._prompt_analyze_tpl = _load_template(os.path.join(templates_dir, prompt_analyze_file))
        self._prompt_system_tpl  = _load_template(os.path.join(templates_dir, prompt_system_file))

    def analyze(self, summary: dict, comparison: dict = None) -> LLMResponse:
        """단일 분석 요청 — /v1/chat/completions 사용."""
        prompt = self._build_prompt(summary, comparison)
        messages = [
            {"role": "system", "content": "너는 금융권 IT 인프라 운영 전문가다. 한국어로 간결하게 답변한다."},
            {"role": "user",   "content": prompt},
        ]
        return self.chat(messages)

    def chat(self, messages: list) -> LLMResponse:
        """Multi-turn chat — OpenAI 호환 /v1/chat/completions."""
        payload = {
            "model":       "local",   # llama-server 는 모델명 무시
            "messages":    messages,
            "stream":      False,
            "temperature": self.temperature,
            "max_tokens":  self.max_tokens,
        }
        dbg.log_request("LlamaCpp /v1/chat/completions", self.url, payload)
        t0 = time.time()
        try:
            resp = requests.post(self.url, json=payload, timeout=180)
            resp.raise_for_status()
            data = resp.json()
            elapsed = time.time() - t0
            dbg.log_response("LlamaCpp /v1/chat/completions", resp.status_code, data, elapsed)
            usage = data.get("usage", {})
            return LLMResponse(
                content=data["choices"][0]["message"]["content"].strip(),
                prompt_tokens=usage.get("prompt_tokens", 0),
                response_tokens=usage.get("completion_tokens", 0),
                elapsed=elapsed,
            )
        except requests.exceptions.ConnectionError as e:
            dbg.log_error("LlamaCpp ConnectionError", e)
            return LLMResponse("[LLM 오류] llama-server에 연결할 수 없습니다. 서버가 실행 중인지 확인하세요.")
        except requests.exceptions.Timeout as e:
            dbg.log_error("LlamaCpp Timeout", e)
            return LLMResponse("[LLM 오류] llama-server 응답 시간 초과 (180초).")
        except Exception as e:
            dbg.log_error("LlamaCpp 알 수 없는 오류", e)
            return LLMResponse(f"[LLM 오류] {e}")

    def _build_prompt(self, summary: dict, comparison: dict = None) -> str:
        from src.comparator import comparison_text as make_comparison_text
        servers_text = json.dumps(summary, ensure_ascii=False, indent=2)
        cmp_text = make_comparison_text(comparison) if comparison else "(전일 데이터 없음)"
        return self._prompt_analyze_tpl.format(
            servers_text=servers_text,
            comparison_text=cmp_text,
        )

    def build_system_message(self, summary: dict) -> str:
        servers_text = json.dumps(summary, ensure_ascii=False, indent=2)
        return self._prompt_system_tpl.format(servers_text=servers_text)
