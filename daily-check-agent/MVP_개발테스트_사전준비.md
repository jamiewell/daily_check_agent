# MVP 개발 테스트 사전 준비 항목

---

## 1. 개발 환경 구성 (로컬 PC)

### 1-1. Git 설치 및 저장소 클론

| OS | 설치 방법 |
|----|-----------|
| macOS | `brew install git` |
| Windows | https://git-scm.com/download/win |

```bash
# 저장소 클론 (GitHub PAT 필요)
git clone https://github.com/jamiewell/daily_check_agent.git
cd daily_check_agent/daily-check-agent
```

> **GitHub PAT 필요:** 프라이빗 저장소이므로 Personal Access Token 필수  
> 발급: GitHub → Settings → Developer Settings → Personal access tokens  
> 권한: `Contents: Read and write`

---

### 1-2. Python 3.12 설치

| OS | 설치 방법 |
|----|-----------|
| macOS | `brew install python@3.12` |
| Windows | https://www.python.org/downloads/ (설치 시 **Add to PATH 체크**) |

```bash
# 설치 확인
python3 --version   # macOS
python --version    # Windows
```

---

### 1-3. 가상환경 구성 및 패키지 설치

**macOS**
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

**Windows**
```powershell
# PowerShell 실행 정책 오류 시 한 번만 실행
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned

python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

---

### 1-4. llama.cpp + Qwen3-0.6B 설치

| 항목 | 내용 |
|------|------|
| llama-server | [github.com/ggml-org/llama.cpp/releases](https://github.com/ggml-org/llama.cpp/releases) 에서 OS별 바이너리 다운로드 |
| 모델 파일 | [huggingface.co/Qwen/Qwen3-0.6B-GGUF](https://huggingface.co/Qwen/Qwen3-0.6B-GGUF) 에서 `qwen3-0.6b-q4_k_m.gguf` 다운로드 (~380 MB) |

```bash
# runtime 폴더에 배치
daily-check-agent/
└── runtime/
    ├── llama-server          # macOS: llama-server / Windows: llama-server.exe
    └── models/
        └── qwen3-0.6b-q4_k_m.gguf

# llama-server 기동 (별도 터미널)
./runtime/llama-server -m runtime/models/qwen3-0.6b-q4_k_m.gguf --port 8080

# 기동 확인
curl http://localhost:8080/health
```

> **디스크 여유 공간:** 최소 1 GB 필요 (모델 ~380 MB)

---

### 1-5. Claude Code 설치 (AI 개발 도구)

```bash
# Node.js 설치 후
npm install -g @anthropic-ai/claude-code

# 로그인 (Anthropic 계정 필요)
claude
```

> VSCode에서 사용 시 Claude Code Extension 추가 설치

---

## 2. 샘플 데이터 기반 로컬 테스트 (Grafana 없이)

저장소 클론 후 즉시 테스트 가능한 모드입니다.

```bash
# Ollama 연결 확인
python3 main.py status

# 메트릭 테이블 출력 (LLM 없음)
python3 main.py check --no-save

# AI 분석 포함 1회 실행
python3 main.py analyze

# 대화형 에이전트 실행
python3 main.py chat
# → "일일점검" 입력 시 점검 실행
```

> 이 단계는 AWS / Grafana 없이 로컬에서만 동작합니다.

---

## 3. AWS EC2 Grafana 연동 테스트

### 3-1. EC2 서버 기동

`hjcode-server` (i-01202fdc8fb237804, us-east-1c, 503561457955 계정)

```bash
aws ec2 start-instances \
  --instance-ids i-01202fdc8fb237804 \
  --profile locosalsa12 --region us-east-1

# Public IP 확인
aws ec2 describe-instances \
  --instance-ids i-01202fdc8fb237804 \
  --query 'Reservations[0].Instances[0].PublicIpAddress' \
  --output text \
  --profile locosalsa12 --region us-east-1
```

---

### 3-2. 보안그룹 포트 오픈

개발자 PC의 공인 IP에서 아래 포트가 열려 있어야 합니다.

| 포트 | 서비스 | 용도 |
|------|--------|------|
| 3000 | Grafana | API 호출 및 UI 접속 |
| 9090 | Prometheus | (선택) 직접 쿼리 확인 |

```bash
# 내 공인 IP 확인
curl ifconfig.me

# 보안그룹에 포트 3000 추가
aws ec2 authorize-security-group-ingress \
  --group-id <SECURITY_GROUP_ID> \
  --protocol tcp --port 3000 \
  --cidr <내_IP>/32 \
  --profile locosalsa12 --region us-east-1
```

---

### 3-3. Grafana 접속 및 Service Account Token 발급

브라우저에서 `http://<EC2_PUBLIC_IP>:3000` 접속 (초기 계정: admin / admin)

**Token 발급 경로:**
```
Administration
  → Service accounts
    → Add service account (Role: Viewer)
      → Add token → 토큰 문자열 복사 (glsa_... 형식)
```

---

### 3-4. Prometheus Datasource UID / ID 확인

```
Grafana UI
  → Connections → Data sources → Prometheus
    → 주소창 URL 끝 부분 = UID  (예: aenzqagld59fke)
    → Settings 하단 JSON 뷰 = id (예: 157)
```

또는 API로 확인:
```bash
curl http://<EC2_PUBLIC_IP>:3000/api/datasources \
  -H "Authorization: Bearer glsa_발급받은토큰" \
  | python3 -m json.tool | grep -E '"id"|"uid"|"name"'
```

---

### 3-5. config.yaml 업데이트

```yaml
grafana:
  url: "http://<EC2_PUBLIC_IP>:3000/api/ds/query"
  token: "glsa_발급받은토큰..."
  ds_uid: "확인한_UID"
  ds_id: 확인한_ID
  verify_ssl: false

  instance:
    env: "pr"          # pr=운영, dv=개발, te=테스트
    biz: "aut"
    roles: ["ap"]      # ap=AP서버, db=DB서버
    numbers: [1, 2]

  window: "15m"
  range_minutes: 60
```

---

### 3-6. data_loader.py 실 Grafana 연동으로 전환

`src/data_loader.py`의 `load_all()` 함수를 아래처럼 교체합니다.

```python
# 변경 전 (샘플 JSON)
def load_all(sample_dir: str) -> dict:
    return {
        "cpu":     load_cpu(sample_dir),
        "memory":  load_memory(sample_dir),
        "network": load_network(sample_dir),
    }

# 변경 후 (실 Grafana API)
from src.grafana_client import GrafanaClient, get_cpu_overview, get_memory_usage, get_network_io

def load_all(cfg: dict) -> dict:
    client = GrafanaClient(cfg)
    return {
        "cpu":     get_cpu_overview(client),
        "memory":  get_memory_usage(client),
        "network": get_network_io(client),
    }
```

> `main.py`의 `load_all(sample_dir)` 호출부도 `load_all(cfg)`로 변경 필요

---

### 3-7. 연동 테스트 실행

```bash
# Grafana API 연결 확인
python3 main.py status

# 실 데이터 기반 점검
python3 main.py chat
# → "일일점검" 입력
```

---

## 4. 준비 항목 체크리스트

### 로컬 테스트 (샘플 데이터)

- [ ] Git 설치
- [ ] 저장소 클론 (GitHub PAT 필요)
- [ ] Python 3.12 설치
- [ ] 가상환경 생성 및 패키지 설치 (`pip install -r requirements.txt`)
- [ ] llama-server 바이너리 + Qwen3-0.6B-Q4_K_M.gguf 다운로드 후 runtime/ 배치
- [ ] `python3 main.py status` 정상 확인

### Grafana 연동 테스트 (실 데이터)

- [ ] EC2 서버 기동 확인
- [ ] EC2 Public IP 확인
- [ ] 보안그룹 포트 3000 오픈 (내 IP 기준)
- [ ] Grafana UI 접속 확인 (`http://IP:3000`)
- [ ] Service Account Token 발급
- [ ] Prometheus Datasource UID / ID 확인
- [ ] `config.yaml` 업데이트 (url / token / ds_uid / ds_id)
- [ ] `data_loader.py` 실 API 모드로 전환
- [ ] `python3 main.py chat` → "일일점검" 실행 확인

---

## 5. 참조 문서

| 문서 | 내용 |
|------|------|
| [MVP_코드_구조_설명.md](MVP_코드_구조_설명.md) | 코드 구조 및 파일 참조 관계 |
| [Python_가상환경_가이드.md](../Python_가상환경_가이드.md) | Python 설치 및 venv 상세 가이드 |
| [패키징_가이드.md](패키징_가이드.md) | llama.cpp 설치, GGUF 모델 배치, EXE 패키징 가이드 |
| [CLAUDE_2_모니터링스택_설치및연동.md](../CLAUDE_2_모니터링스택_설치및연동.md) | EC2 Grafana 스택 설치 내역 |
| [CLAUDE_3_일일점검에이전트_개발.md](../CLAUDE_3_일일점검에이전트_개발.md) | Grafana API 목록 및 PromQL |
