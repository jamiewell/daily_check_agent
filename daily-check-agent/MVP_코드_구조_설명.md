# daily-check-agent MVP 코드 구조 설명

---

## 1. 파일 구성

```
daily-check-agent/
├── main.py                  # CLI 진입점
├── config.yaml              # 설정값 (URL, 임계치, 경로)
├── requirements.txt         # Python 패키지 목록
├── .venv/                   # 가상환경 (git 제외)
├── sample_data/
│   ├── cpu.json             # CPU 사용률 샘플 (Grafana API-1 형식)
│   ├── memory.json          # 메모리 사용률 샘플 (Grafana API-4 형식)
│   └── network.json         # 네트워크 I/O 샘플 (Grafana API-6 형식)
├── src/
│   ├── __init__.py          # 패키지 선언 (내용 없음)
│   ├── data_loader.py       # JSON 읽기 + 단위 변환
│   ├── preprocessor.py      # 집계 + 임계치 판단
│   ├── llm_client.py        # Ollama API 클라이언트
│   └── reporter.py          # 터미널 출력 + MD 리포트 저장
└── reports/
    └── report_YYYYMMDD_HHmmss.md   # 자동 생성 리포트
```

---

## 2. 파일별 역할

| 파일 | 역할 |
|------|------|
| `main.py` | CLI 명령어 라우팅. 키워드 감지 후 점검 흐름 조율 |
| `config.yaml` | Ollama URL/모델명, 임계치(%), sample_data 경로 등 설정 |
| `src/data_loader.py` | JSON 파일 읽기 + 단위 변환 (raw 데이터 → Python dict) |
| `src/preprocessor.py` | 시계열 avg/max/latest 집계, 임계치 비교, 상태 판정 |
| `src/llm_client.py` | Ollama REST API 호출. 단발 분석(`analyze`) + 멀티턴 대화(`chat`) |
| `src/reporter.py` | Rich 터미널 테이블 출력 + MD 리포트 파일 저장 |
| `sample_data/*.json` | Grafana API 응답 형식을 모사한 테스트 데이터 |

---

## 3. 참조 관계 (의존 방향)

```
main.py
  ├── src/data_loader.py
  ├── src/preprocessor.py
  ├── src/llm_client.py
  └── src/reporter.py

src/data_loader.py    → sample_data/*.json  (파일 읽기)
src/preprocessor.py   → config.yaml의 thresholds 값 (main.py가 전달)
src/llm_client.py     → Ollama HTTP API (http://localhost:11434)
src/reporter.py       → reports/ 폴더 (파일 쓰기)
```

> `src/` 내부 모듈끼리는 서로 참조하지 않습니다.  
> 모든 조율은 `main.py`가 담당합니다.

---

## 4. 실행 흐름

### 4-1. 기동 시

```
$ source .venv/bin/activate
$ python3 main.py chat
        │
        ▼
main.py — config.yaml 로드
        — Ollama 클라이언트 초기화
        — 대기 상태 진입 (점검 미실행)
        — "You > " 프롬프트 표시
```

### 4-2. 일반 대화 (키워드 없음)

```
You > 안녕?
        │
        ▼
main.py — 키워드 감지 안됨
        │
        ▼
llm_client.chat()  →  Ollama /api/chat  →  Qwen3 응답
        │
        ▼
reporter.print_llm_analysis()  →  터미널 패널 출력
```

### 4-3. 일일점검 실행 (키워드 감지)

```
You > 일일점검
        │
        ▼
main.py — CHECK_KEYWORDS 매칭 확인
        │   ("일일점검", "점검", "서버 점검", "check", "분석 시작", "점검 시작")
        ▼
data_loader.load_all()
  ├── cpu.json    읽기  →  값 그대로 % 사용
  ├── memory.json 읽기  →  값 × 100 (소수 → %)
  └── network.json 읽기 →  값 ÷ 1,000,000 (bps → Mbps)
        │
        ▼
preprocessor.summarize()
  ├── 각 서버별 avg / max / latest 계산
  ├── config.yaml의 thresholds와 비교
  │     cpu_warning: 70%  / cpu_critical: 90%
  │     memory_warning: 70%  / memory_critical: 85%
  │     network_warning: 100Mbps / network_critical: 500Mbps
  └── 알림 문구 생성 + 상태 판정 (정상 / 주의 / 위험)
        │
        ▼
reporter.print_summary()  →  Rich 테이블로 터미널 출력
        │
        ▼
llm_client.chat()
  ├── 시스템 메시지에 summary 데이터 JSON 주입
  └── Ollama /api/chat 호출  →  Qwen3 분석 응답
        │
        ▼
reporter.print_llm_analysis()  →  분석 결과 패널 출력
reporter.save_report()         →  reports/report_YYYYMMDD_HHmmss.md 저장
```

---

## 5. 데이터 변환 흐름

```
[raw JSON]                [data_loader 변환]          [preprocessor 집계]

cpu.json                  값 그대로 (이미 %)           avg: 53.69%
  values: [21.3 ~ 91.4]  ─────────────────────────►  max: 91.4%   → 위험
                                                       latest: 28.4%

memory.json               × 100 적용                  avg: 64.8%
  values: [0.601 ~ 0.682] ─────────────────────────►  latest: 68.2%  → 정상

network.json              ÷ 1,000,000 (Mbps 변환)     rx_max: 421.94 Mbps
  values: [94031128 ~ ]   ─────────────────────────►  tx_max: 213.85 Mbps → 주의
```

---

## 6. LLM 연동 구조

```python
# 멀티턴 대화 — /api/chat 사용
messages = [
    {"role": "system",    "content": "IT 전문가 역할 + 현재 메트릭 데이터"},
    {"role": "user",      "content": "점검 결과 요약해줘"},
    {"role": "assistant", "content": "(Qwen3 응답)"},
    {"role": "user",      "content": "prautap1 cpu 왜 높아?"},  # 후속 질문
    ...
]
```

- 대화 이력 전체를 매 요청마다 전송 → Qwen3가 이전 문맥을 기억
- 점검 데이터는 system 메시지에 포함 → 어떤 질문에도 메트릭 기반 답변 가능

---

## 7. CLI 커맨드 목록

```bash
python3 main.py chat      # 대화형 에이전트 (메인 모드)
python3 main.py check     # 점검 테이블만 출력 (LLM 없음)
python3 main.py analyze   # 점검 + AI 분석 1회 실행 후 종료
python3 main.py status    # Ollama 연결 상태 확인
```

---

## 8. Grafana 실서버 연동 시 변경 포인트

현재 `data_loader.py`의 `load_all()`이 로컬 JSON 파일을 읽습니다.  
실서버 연동 시 이 함수 내부만 Grafana API 호출로 교체하면 됩니다.  
`preprocessor`, `llm_client`, `reporter`는 수정 없이 그대로 사용합니다.

```python
# 현재 (샘플 데이터)
def load_all(sample_dir: str) -> dict:
    return {
        "cpu":     load_cpu(sample_dir),      # 파일 읽기
        "memory":  load_memory(sample_dir),   # 파일 읽기
        "network": load_network(sample_dir),  # 파일 읽기
    }

# 실서버 연동 후 (Grafana API 호출로 교체)
def load_all(grafana_url: str, token: str) -> dict:
    return {
        "cpu":     fetch_cpu(grafana_url, token),      # API 호출
        "memory":  fetch_memory(grafana_url, token),   # API 호출
        "network": fetch_network(grafana_url, token),  # API 호출
    }
```

---

## 9. OS별 구동 주의사항

### 공통 사전 조건

| 항목 | 내용 |
|------|------|
| Python | 3.12 이상 |
| Ollama | 설치 및 서비스 실행 상태 |
| qwen3 모델 | `ollama pull qwen3` 완료 |
| 디스크 여유 | 6 GB 이상 (모델 5.2 GB + 여유) |

---

### macOS

**세팅 순서**

```bash
# 1. 저장소 복제
git clone https://github.com/jamiewell/daily_check_agent.git
cd daily_check_agent/daily-check-agent

# 2. 가상환경 생성 및 활성화
python3 -m venv .venv
source .venv/bin/activate

# 3. 패키지 설치
pip install -r requirements.txt

# 4. Ollama 서비스 시작
brew services start ollama

# 5. 실행
python3 main.py chat
```

**주의사항**

- `python3` 명령어 사용 (`python`은 미인식될 수 있음)
- Homebrew 미설치 시 공식 Python 설치 파일 사용
- Apple Silicon(M1/M2/M3)은 Unified Memory로 GPU 가속 자동 적용

---

### Windows

**세팅 순서**

```powershell
# 1. 저장소 복제
git clone https://github.com/jamiewell/daily_check_agent.git
cd daily_check_agent\daily-check-agent

# 2. 가상환경 생성 및 활성화
python -m venv .venv
.venv\Scripts\activate

# 3. 패키지 설치
pip install -r requirements.txt

# 4. Ollama 실행 (별도 터미널 또는 백그라운드)
ollama serve

# 5. 실행
python main.py chat
```

**주의사항**

**① venv 활성화 오류 (PowerShell 실행 정책)**

```powershell
# 오류 발생 시 한 번만 실행
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
```

**② 한글 깨짐 (cmd / 구형 PowerShell)**

```powershell
# 실행 전 UTF-8로 전환
chcp 65001
```

> Windows Terminal 또는 VSCode 내장 터미널은 UTF-8 기본값이라 설정 불필요.

**③ Python 명령어 차이**

| macOS | Windows |
|-------|---------|
| `python3 main.py chat` | `python main.py chat` |
| `source .venv/bin/activate` | `.venv\Scripts\activate` |

**④ Ollama Windows 설치**

- 다운로드: `https://ollama.com/download/windows`
- 설치 후 `ollama serve` 또는 시스템 트레이에서 자동 실행

---

### OS별 빠른 비교

| 항목 | macOS | Windows |
|------|-------|---------|
| Python 명령어 | `python3` | `python` |
| venv 활성화 | `source .venv/bin/activate` | `.venv\Scripts\activate` |
| Ollama 시작 | `brew services start ollama` | `ollama serve` |
| 한글 설정 | 불필요 | `chcp 65001` (cmd 한정) |
| GPU 가속 | Metal (Apple Silicon 자동) | CUDA (NVIDIA GPU 자동) |
| 권장 터미널 | iTerm2 / 기본 터미널 | Windows Terminal / VSCode |
