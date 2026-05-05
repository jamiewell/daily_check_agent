# Ollama + Qwen3 설치 및 사용 가이드

## 설치 환경

- OS: macOS (Apple Silicon / ARM64)
- Ollama 버전: 0.23.0
- Qwen3 모델: qwen3:latest (5.2GB)

---

## 1. Ollama 설치

### Homebrew로 설치 (권장)

```bash
brew install ollama
```

### 설치 확인

```bash
ollama --version
# ollama version is 0.23.0
```

---

## 2. Ollama 서비스 시작/중지

```bash
# 서비스 시작 (Mac 재시작 시 자동 실행)
brew services start ollama

# 서비스 중지
brew services stop ollama

# 서비스 상태 확인
brew services info ollama

# 서버 직접 실행 (포그라운드)
ollama serve
```

> 서버 주소: `http://localhost:11434`

---

## 3. Qwen3 모델 설치

```bash
# 기본 모델 (4B, 5.2GB) - 권장
ollama pull qwen3

# 모델 크기별 선택
ollama pull qwen3:1.7b    # 1.7B 파라미터 (1.1GB) - 경량
ollama pull qwen3:4b      # 4B  파라미터 (5.2GB) - 기본 ← 현재 설치됨
ollama pull qwen3:8b      # 8B  파라미터 (5.6GB) - 고품질
ollama pull qwen3:14b     # 14B 파라미터 (9.3GB) - 높은 성능
ollama pull qwen3:32b     # 32B 파라미터 (20GB)  - 최고 품질
```

### 설치된 모델 확인

```bash
ollama list
# NAME            ID              SIZE      MODIFIED
# qwen3:latest    500a1f067a9f    5.2 GB    ...
```

---

## 4. CLI 기본 사용법

### 대화형 채팅

```bash
ollama run qwen3
# >>> 여기에 질문 입력
# /bye 로 종료
```

### 단일 질문 (Non-interactive)

```bash
ollama run qwen3 "파이썬으로 피보나치 수열을 구현해줘"
```

### 스트리밍 없이 결과만 출력

```bash
ollama run qwen3 "서버 CPU 사용률이 90%일 때 원인과 조치 방법은?" --nowordwrap
```

### 파이프라인 활용

```bash
# 파일 내용 분석
cat error.log | ollama run qwen3 "이 에러 로그를 분석하고 원인을 알려줘"

# 텍스트 요약
echo "긴 텍스트..." | ollama run qwen3 "다음 내용을 3줄로 요약해줘"
```

---

## 5. REST API 사용법

Ollama는 `http://localhost:11434` 에서 HTTP API를 제공합니다.

### 기본 호출 (curl)

```bash
curl http://localhost:11434/api/generate \
  -d '{
    "model": "qwen3",
    "prompt": "서버 메모리 사용률이 95%입니다. 조치 방법은?",
    "stream": false
  }'
```

### Python에서 호출

```python
import requests

def ask_llm(prompt: str, model: str = "qwen3") -> str:
    response = requests.post(
        "http://localhost:11434/api/generate",
        json={
            "model": model,
            "prompt": prompt,
            "stream": False
        }
    )
    return response.json()["response"]

# 사용 예시
answer = ask_llm("CPU 사용률 92%, 메모리 85% 상태를 분석해줘")
print(answer)
```

### 채팅 형식 (멀티턴 대화)

```python
import requests

def chat(messages: list, model: str = "qwen3") -> str:
    response = requests.post(
        "http://localhost:11434/api/chat",
        json={
            "model": model,
            "messages": messages,
            "stream": False
        }
    )
    return response.json()["message"]["content"]

# 멀티턴 대화 예시
messages = [
    {"role": "system",  "content": "당신은 IT 인프라 운영 전문가입니다."},
    {"role": "user",    "content": "서버 CPU가 갑자기 90%를 넘었습니다."},
]
reply = chat(messages)
print(reply)

# 대화 이어가기
messages.append({"role": "assistant", "content": reply})
messages.append({"role": "user", "content": "추가로 확인할 명령어는?"})
reply2 = chat(messages)
print(reply2)
```

---

## 6. 일일점검 에이전트 연동 예시

```python
import requests, json

OLLAMA_URL = "http://localhost:11434/api/generate"

def analyze_server_status(metrics: dict) -> str:
    prompt = f"""
다음은 금융시스템 서버 일일점검 결과입니다.
이상 여부를 분석하고 조치 우선순위를 알려주세요.

{json.dumps(metrics, ensure_ascii=False, indent=2)}

분석 항목:
1. 이상 여부 (정상/주의/위험)
2. 원인 추정
3. 즉시 조치 필요 항목
4. 모니터링 권고 사항
"""
    response = requests.post(OLLAMA_URL, json={
        "model": "qwen3",
        "prompt": prompt,
        "stream": False,
        "options": {
            "temperature": 0.3,   # 낮을수록 일관된 답변
            "num_predict": 1024   # 최대 토큰 수
        }
    })
    return response.json()["response"]


# 사용 예시
metrics = {
    "timestamp": "2026-05-04 09:00",
    "servers": {
        "prautap1": {"cpu_pct": 23.7, "mem_pct": 14.5},
        "prautdb1": {"cpu_pct": 8.1,  "mem_pct": 61.2}
    },
    "dead_processes": [],
    "alerts": []
}

result = analyze_server_status(metrics)
print(result)
```

---

## 7. 모델 관리 명령어

```bash
# 설치된 모델 목록
ollama list

# 모델 삭제
ollama rm qwen3

# 모델 정보 확인
ollama show qwen3

# 실행 중인 모델 확인
ollama ps

# 모델 복사 (커스텀 이름)
ollama cp qwen3 my-qwen3
```

---

## 8. Modelfile 커스터마이징

시스템 프롬프트를 고정해서 사용하고 싶을 때.

```bash
cat > Modelfile << 'EOF'
FROM qwen3

SYSTEM """
당신은 금융 IT 인프라 운영 전문가입니다.
서버 메트릭과 로그를 분석하고 간결하게 답변합니다.
항상 한국어로 응답하세요.
"""

PARAMETER temperature 0.3
PARAMETER num_predict 1024
EOF

# 커스텀 모델 생성
ollama create daily-check-agent -f Modelfile

# 사용
ollama run daily-check-agent "오늘 점검 결과를 분석해줘"
```

---

## 9. 참고 정보

| 항목 | 내용 |
|------|------|
| 서버 주소 | `http://localhost:11434` |
| 모델 저장 경로 | `~/.ollama/models/` |
| 로그 경로 | `~/.ollama/logs/` |
| 공식 모델 목록 | `https://ollama.com/library` |
| Qwen3 모델 페이지 | `https://ollama.com/library/qwen3` |
