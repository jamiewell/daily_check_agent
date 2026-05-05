"""Ollama LLM client — supports both /api/generate and /api/chat endpoints."""

import json
import requests


class OllamaClient:
    def __init__(self, url: str, model: str, temperature: float = 0.3, num_predict: int = 1024):
        self.url = url
        self.model = model
        self.temperature = temperature
        self.num_predict = num_predict

    def analyze(self, summary: dict) -> str:
        prompt = self._build_prompt(summary)
        try:
            resp = requests.post(
                self.url,
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
            return resp.json().get("response", "").strip()
        except requests.exceptions.ConnectionError:
            return "[LLM 오류] Ollama 서버에 연결할 수 없습니다. `ollama serve` 또는 `brew services start ollama`를 실행하세요."
        except requests.exceptions.Timeout:
            return "[LLM 오류] Ollama 응답 시간 초과 (120초)."
        except Exception as e:
            return f"[LLM 오류] {e}"

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
