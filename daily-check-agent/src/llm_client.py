"""Ollama LLM client — supports both /api/generate and /api/chat endpoints."""

import json
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


class OllamaClient:
    def __init__(self, url: str, model: str, temperature: float = 0.3, num_predict: int = 1024):
        self.generate_url = url
        self.chat_url = url.replace(GENERATE_URL_SUFFIX, CHAT_URL_SUFFIX)
        self.model = model
        self.temperature = temperature
        self.num_predict = num_predict

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
        return f"""당신은 금융 IT 인프라 운영 전문가입니다.
아래는 서버 일일점검 메트릭 요약입니다. 한국어로 간결하게 분석해주세요.

{servers_text}

다음 항목을 순서대로 작성하세요:
1. 전체 상태 평가 (정상 / 주의 / 위험)
2. 이상 항목 및 원인 추정
3. 즉시 조치 필요 사항
4. 모니터링 권고 사항
"""

    def build_system_message(self, summary: dict) -> str:
        servers_text = json.dumps(summary, ensure_ascii=False, indent=2)
        return f"""당신은 금융 IT 인프라 운영 전문가입니다. 한국어로 답변하세요.
현재 서버 점검 데이터는 아래와 같습니다. 사용자의 질문에 이 데이터를 바탕으로 답변하세요.

{servers_text}"""
