# Windows 11 저사양 PC 데모용 로컬 AI Agent 패키징 가이드

## 1. 목표

Python 3 기반 MVP 로컬 AI Agent를 Windows 11 저사양 PC에서 실행 가능한 형태로 패키징한다.

구성 목표:

```text
Python3 MVP 코드
+ llama.cpp 런타임
+ Qwen3-0.6B GGUF(Q4)
+ PyInstaller exe 패키징
```

실행 목표:

```text
사용자가 exe 실행
→ llama.cpp 서버 자동 실행
→ Python MVP Agent가 analyze 모드로 자동 실행
→ main.py analyze와 동일한 실행 결과 확인
```

---

## 2. 권장 데모 구성

### 최종 권장 방식

```text
Start.exe
+ runtime 폴더 포함
```

완전한 단일 exe도 가능하지만, 저사양 PC와 임원 데모 안정성을 고려하면 아래 방식이 더 안전하다.

```text
AI-Agent-Demo/
 ├─ Start.exe
 └─ runtime/
     ├─ llama-server.exe
     └─ models/
         └─ qwen3-0.6b-q4_k_m.gguf
```

### 완전 단일 exe 방식

```text
Start.exe 내부에
 ├─ llama-server.exe
 └─ qwen3-0.6b-q4_k_m.gguf
포함
```

단점:

```text
exe 용량 500MB~1GB 이상
첫 실행 시 임시 폴더 압축 해제 시간 발생
Windows Defender/EDR 검사 지연 가능
임시 폴더 용량 부족 가능
```

---

## 3. 최소/권장 스펙

| 항목 | 최소 | 권장 |
|---|---:|---:|
| OS | Windows 11 64bit | Windows 11 64bit |
| RAM | 8GB | 16GB |
| CPU | x64 CPU | AVX2 지원 CPU |
| GPU | 불필요 | 없어도 가능 |
| 저장공간 | 3GB 이상 | 5GB 이상 |
| 모델 | Qwen3-0.6B Q4 | Qwen3-0.6B Q4_K_M |

저사양 PC에서는 GPU 없이 CPU-only로 실행하는 것을 기본으로 한다.

---

## 4. 준비 파일

### 필수 파일

```text
1. Python 3.10~3.12
2. PyInstaller
3. requests
4. llama-server.exe
5. Qwen3-0.6B GGUF Q4 모델
```

### 모델 권장

```text
Qwen3-0.6B-GGUF
Q4_K_M 양자화 모델
예상 크기: 약 500MB 전후
```

### llama.cpp 런타임

Ollama 대신 llama.cpp의 `llama-server.exe`를 사용한다.

이유:

```text
Ollama보다 가벼움
설치 불필요
subprocess 제어 쉬움
GGUF 모델 직접 로딩 가능
OpenAI 호환 API 사용 가능
```

---

## 5. 프로젝트 폴더 구조

```text
project/
 ├─ main.py
 ├─ requirements.txt
 └─ runtime/
     ├─ llama-server.exe
     └─ models/
         └─ qwen3-0.6b-q4_k_m.gguf
```

---

## 6. Python MVP 코드 예시

아래 코드는 기존 MVP Agent가 `python main.py analyze`로 실행되는 구조를 유지하면서, exe 실행 시에도 자동으로 `analyze` 모드가 선택되도록 하는 예시다.

핵심은 `sys.argv`에 모드 인자가 없을 때 기본값을 `analyze`로 주는 것이다.

`main.py`

```python
import os
import sys
import time
import subprocess
import requests
from pathlib import Path

PORT = 8080
MODEL_FILE = "qwen3-0.6b-q4_k_m.gguf"
DEFAULT_MODE = "analyze"


def resource_path(relative_path: str) -> Path:
    if hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS) / relative_path
    return Path(__file__).resolve().parent / relative_path


def start_llama_server():
    runtime_dir = resource_path("runtime")
    server_path = runtime_dir / "llama-server.exe"
    model_path = runtime_dir / "models" / MODEL_FILE

    if not server_path.exists():
        raise FileNotFoundError(f"llama-server.exe not found: {server_path}")

    if not model_path.exists():
        raise FileNotFoundError(f"model not found: {model_path}")

    cmd = [
        str(server_path),
        "-m", str(model_path),
        "--host", "127.0.0.1",
        "--port", str(PORT),
        "-c", "2048",
        "-t", "4"
    ]

    proc = subprocess.Popen(
        cmd,
        creationflags=subprocess.CREATE_NEW_CONSOLE
    )

    for _ in range(60):
        try:
            r = requests.get(f"http://127.0.0.1:{PORT}/health", timeout=1)
            if r.status_code in (200, 503):
                return proc
        except Exception:
            time.sleep(1)

    raise RuntimeError("llama.cpp server start failed")


def ask_llm(user_prompt: str) -> str:
    url = f"http://127.0.0.1:{PORT}/v1/chat/completions"

    payload = {
        "model": "qwen3-0.6b",
        "messages": [
            {
                "role": "system",
                "content": "너는 금융권 시스템 운영자를 돕는 로컬 AI 에이전트다. 핵심만 간결하게 답변한다."
            },
            {
                "role": "user",
                "content": user_prompt
            }
        ],
        "temperature": 0.3,
        "max_tokens": 512,
        "stream": False
    }

    res = requests.post(url, json=payload, timeout=180)
    res.raise_for_status()
    return res.json()["choices"][0]["message"]["content"]


def run_analyze_mode():
    # 실제 MVP Agent의 analyze 로직을 이 함수에 연결한다.
    # 예: Grafana API 조회 → 데이터 요약 → LLM 분석 → 결과 출력/파일 저장
    prompt = "시스템 상태 데이터를 분석하고 핵심 이상 징후와 조치 방안을 요약해줘."
    answer = ask_llm(prompt)
    print("\n[analyze 결과]")
    print(answer)


def run_chat_mode():
    print("종료하려면 exit 입력")

    while True:
        question = input("\n질문> ").strip()

        if question.lower() in ["exit", "quit", "q"]:
            break

        if not question:
            continue

        try:
            answer = ask_llm(question)
            print("\n답변>")
            print(answer)
        except Exception as e:
            print(f"\n오류 발생: {e}")


def main():
    # exe를 더블클릭하면 인자가 없으므로 analyze 모드로 자동 실행
    mode = sys.argv[1] if len(sys.argv) >= 2 else DEFAULT_MODE

    print("Local AI Agent Demo")
    print("llama.cpp + Qwen3-0.6B GGUF(Q4)")
    print(f"실행 모드: {mode}")
    print("서버 시작 중...")

    server_proc = None

    try:
        server_proc = start_llama_server()
        print("서버 시작 완료")

        if mode == "analyze":
            run_analyze_mode()
        elif mode == "chat":
            run_chat_mode()
        elif mode == "status":
            print("status 모드 실행")
            # 기존 status 로직 연결
        elif mode == "check":
            print("check 모드 실행")
            # 기존 check 로직 연결
        else:
            print(f"지원하지 않는 모드: {mode}")
            print("사용 가능 모드: status, check, analyze, chat")

    finally:
        if server_proc:
            server_proc.terminate()


if __name__ == "__main__":
    main()
```

---

## 7. requirements.txt

```text
requests==2.32.3
pyinstaller==6.11.1
```

---

## 8. 로컬 실행 테스트

기존 MVP Agent의 실행 확인 모드는 아래와 같다.

```powershell
python main.py status
python main.py check
python main.py analyze
python main.py chat
```

이번 데모 패키징에서는 exe 실행 시 자동으로 아래 명령과 동일하게 동작하도록 구성한다.

```powershell
python main.py analyze
```

로컬 테스트:

```powershell
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python main.py analyze
```

인자 없이 실행해도 analyze가 기본 실행되도록 확인한다.

```powershell
python main.py
```

정상 실행 시:

```text
Local AI Agent Demo
실행 모드: analyze
서버 시작 중...
서버 시작 완료
[analyze 결과]
...
```

테스트 질문:

```text
WebtoB 큐잉 백로그가 증가했을 때 점검 순서를 알려줘
```

---

## 9. PyInstaller 패키징

### 권장: onedir 방식

데모 안정성 우선 방식이다.

`main.py` 내부에서 기본 모드를 `analyze`로 처리하므로, PyInstaller 빌드 시 별도 인자를 넣을 필요는 없다.

```powershell
pyinstaller --onedir --console ^
  --name Start ^
  --add-data "runtime;runtime" ^
  main.py
```

결과:

```text
dist/
 └─ Start/
     ├─ Start.exe
     ├─ _internal/
     └─ runtime/
         ├─ llama-server.exe
         └─ models/
             └─ qwen3-0.6b-q4_k_m.gguf
```

실행:

```powershell
cd dist\Start
Start.exe
```

위 실행은 내부적으로 아래와 동일하게 동작한다.

```powershell
python main.py analyze
```

다른 모드를 수동 실행하고 싶으면 CMD/PowerShell에서 인자를 붙인다.

```powershell
Start.exe status
Start.exe check
Start.exe chat
```

---

### 단일 exe 방식

반드시 하나의 exe가 필요할 때 사용한다.

```powershell
pyinstaller --onefile --console ^
  --name Start ^
  --add-data "runtime;runtime" ^
  main.py
```

결과:

```text
dist/Start.exe
```

주의:

```text
첫 실행이 느릴 수 있음
TEMP 폴더에 모델 파일 압축 해제됨
디스크 여유 공간 필요
보안 솔루션 검사 지연 가능
```

---

## 9-1. exe 실행 시 analyze 모드 자동 실행 핵심

가장 중요한 코드는 아래 한 줄이다.

```python
mode = sys.argv[1] if len(sys.argv) >= 2 else "analyze"
```

의미:

```text
Start.exe           → analyze 모드 자동 실행
Start.exe analyze   → analyze 모드 실행
Start.exe status    → status 모드 실행
Start.exe check     → check 모드 실행
Start.exe chat      → chat 모드 실행
```

따라서 임원 데모용 exe는 더블클릭만 해도 `python main.py analyze`와 동일한 흐름으로 실행된다.

---

## 10. 사용 방법

### 임원 데모 순서

```text
1. Windows 11 PC에 Start.exe 복사
2. Start.exe 더블클릭
3. llama.cpp 서버 창 자동 실행 확인
4. Python Agent 창에서 analyze 모드 자동 실행 확인
5. 분석 결과 출력 확인
6. 필요한 경우 결과 텍스트 파일 생성 여부 확인
```

### 데모 질문 예시

```text
CPU 사용률이 높고 응답속도가 느릴 때 점검 순서를 알려줘
```

```text
GC 로그에서 Full GC가 자주 발생하면 어떤 원인을 의심해야 해?
```

```text
Linux 서버 디스크 사용률이 95%일 때 운영자 조치 절차를 정리해줘
```

---

## 11. 저사양 PC 튜닝 옵션

`main.py`의 llama-server 실행 옵션을 조정한다.

### 더 가볍게 실행

```text
-c 1024
-t 2
max_tokens 256
```

### 기본 권장

```text
-c 2048
-t 4
max_tokens 512
```

### 옵션 의미

| 옵션 | 의미 |
|---|---|
| `-c 2048` | 컨텍스트 길이 |
| `-t 4` | CPU 스레드 수 |
| `max_tokens` | 최대 응답 길이 |
| `temperature` | 답변 창의성 |

저사양 PC에서는 `-t` 값을 CPU 코어 수보다 낮게 잡는 것이 안정적이다.

---

## 12. Ollama 기반 코드에서 변경되는 부분

### 기존 Ollama 방식

```text
http://127.0.0.1:11434/api/chat
```

### llama.cpp 방식

```text
http://127.0.0.1:8080/v1/chat/completions
```

### 응답 파싱 변경

Ollama:

```python
answer = res.json()["message"]["content"]
```

llama.cpp:

```python
answer = res.json()["choices"][0]["message"]["content"]
```

수정 범위:

```text
LLM 호출 함수
서버 실행 함수
응답 파싱 함수
```

기존 Agent 로직, CLI, 파일 저장, Grafana API 수집 로직은 대부분 그대로 사용 가능하다.

---

## 13. 데모 리스크 및 대응

| 리스크 | 대응 |
|---|---|
| 첫 실행 느림 | onedir 방식 우선 사용 |
| 백신 검사 지연 | 사전 실행 테스트 |
| 포트 충돌 | 8080 대신 18080 사용 |
| RAM 부족 | Qwen3-0.6B Q4 사용 |
| 응답 느림 | `-c 1024`, `max_tokens 256` 적용 |
| 모델 파일 누락 | 실행 전 runtime/models 확인 |

---

## 14. 최종 추천

임원 데모 안정성 기준 최종 추천은 아래와 같다.

```text
Python 3 MVP 코드
+ llama.cpp llama-server.exe
+ Qwen3-0.6B GGUF Q4_K_M
+ PyInstaller onedir 패키징
```

단일 exe가 반드시 필요하면 `--onefile`을 사용하되, 사전 테스트가 필수다.

```text
데모 안정성: onedir > onefile
배포 단순성: onefile > onedir
저사양 PC 안정성: onedir 권장
```

---

## 15. 참고 기준

- llama.cpp server는 OpenAI 호환 `/v1/chat/completions` API를 제공한다.
- PyInstaller는 `--add-data`로 런타임 파일과 모델 파일을 번들링할 수 있다.
- PyInstaller onefile은 실행 시 내부 파일을 임시 폴더에 풀어서 실행한다.
- Qwen3-0.6B Q4_K_M GGUF 모델은 약 500MB 전후의 경량 모델로 저사양 데모에 적합하다.
