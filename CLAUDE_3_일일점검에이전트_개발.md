# CLAUDE 3 — 일일점검 에이전트 프로젝트 개발

## 개요

업무망(폐쇄망) Grafana API 기반 AI LLM 운영지원 에이전트.  
외부 인터넷망에서 개발 → 내부 업무망 반입 → 사내 LLM 연동 구조.

---

## 핵심 제약사항

- 내부 업무망은 외부 인터넷 차단 (OpenAI, Claude API 사용 불가)
- Grafana API를 통해서만 메트릭/로그 수집 가능 (Prometheus/Loki 직접 접근 불가)
- 사내 LLM API만 사용 (Qwen3, KURE-v1 등)
- EXE 패키징 후 망간 반입 절차 필요

---

## 프로젝트 구조

```
grafana-ai-agent/
├── main.py
├── config.yaml                # API 주소, 토큰, 모델명 — 환경별 변경
├── src/
│   ├── grafana_client.py      # Grafana API 호출
│   ├── collector.py           # 메트릭/로그 수집
│   ├── preprocessor.py        # 데이터 전처리/집계
│   ├── llm_client.py          # LLM API 클라이언트
│   ├── reporter.py            # 리포트 생성 (MD/TXT)
│   └── notifier.py            # 메일/메신저 발송
├── logs/
└── reports/
```

---

## 기술 스택

| 구분 | 기술 |
|------|------|
| 언어 | Python |
| HTTP | requests |
| 데이터 처리 | pandas |
| LLM | llama.cpp + Qwen3-0.6B-Q4_K_M.gguf (외부) / 사내 LLM API (내부) |
| CLI | argparse / click |
| 설정 | YAML |
| 리포트 | Markdown / TXT |
| 패키징 | PyInstaller (EXE) |
| 환경 | Windows (내부망) / Mac (개발) |

---

## Grafana API 연동 정보

### 공통 설정

```python
GRAFANA_URL = "https://grafana.shinhancard.com:3000/api/ds/query"
TOKEN       = "glsa_..."          # Service Account Token
DS_UID      = "aenzqagld59fke"    # Prometheus datasource UID
DS_ID       = 157                  # Prometheus datasource ID
INSTANCES   = "(prautap1|prautdb1)"

HEADERS = {
    "Authorization": f"Bearer {TOKEN}",
    "Content-Type": "application/json"
}
```

### 공통 호출 함수

```python
import time, requests

def query(expr, ref_id="A", minutes=5, interval_ms=15000, max_dp=300):
    now = int(time.time() * 1000)
    from_ms = str(now - minutes * 60 * 1000)
    payload = {
        "queries": [{
            "datasource": {"type": "prometheus", "uid": DS_UID},
            "expr": expr,
            "refId": ref_id,
            "range": True,
            "intervalMs": interval_ms,
            "maxDataPoints": max_dp,
            "datasourceId": DS_ID,
            "utcOffsetSec": 32400,
            "scopes": [], "adhocFilters": []
        }],
        "from": from_ms,
        "to": str(now)
    }
    return requests.post(GRAFANA_URL, headers=HEADERS, json=payload, verify=False).json()
```

---

## 개발해야 할 API 목록

### API-1: CPU 사용률 (15분 윈도우) — SQR292

- **용도:** AP/DB 서버 CPU 트렌드 overview
- **PromQL:** `(sum by(instance)(irate(node_cpu_seconds_total{instance=~"INSTANCES",mode!="idle"}[15m])) / on(instance) group_left sum by(instance)(irate(node_cpu_seconds_total{instance=~"INSTANCES"}[15m]))) * 100`
- **응답 단위:** % (이미 ×100 적용, 변환 불필요)
- **refId:** A

```python
def get_cpu_overview():
    expr = f'(sum by(instance)(irate(node_cpu_seconds_total{{instance=~"{INSTANCES}",mode!="idle"}}[15m]))/on(instance) group_left sum by(instance)(irate(node_cpu_seconds_total{{instance=~"{INSTANCES}"}}[15m])))*100'
    return query(expr, interval_ms=15000, max_dp=120)
```

---

### API-2: CPU 사용률 (5분 윈도우) — SQR293

- **용도:** CPU 실시간 세부 추이 (Detail 패널)
- **PromQL:** 위와 동일, 윈도우만 `5m`으로 변경
- **응답 단위:** 소수 (0~1) → **반드시 ×100 변환 필요**
- **refId:** E

```python
def get_cpu_detail():
    expr = f'sum by(instance)(irate(node_cpu_seconds_total{{instance=~"{INSTANCES}",mode!="idle"}}[5m]))/on(instance) group_left sum by(instance)(irate(node_cpu_seconds_total{{instance=~"{INSTANCES}"}}[5m]))'
    resp = query(expr, ref_id="E", interval_ms=5000, max_dp=376)
    # 파싱 시 values * 100 필요
    return resp
```

---

### API-3: 프로세스 수 모니터링 — SQR325

- **용도:** 서버별 named process 생존 여부 감시
- **PromQL:** `namedprocess_namegroup_num_procs{instance=~"INSTANCES"}`
- **응답 단위:** 정수 (프로세스 개수), 0이면 프로세스 사망
- **이상 감지:** 기대값 대비 실제값 비교

```python
BASELINE = {
    "Process DB(ora_pmon_AUTDBP)": 1,
    "Process DB(tnslsnr)": 2,
    "Process SMS(ovcd)": 11,
}

def get_process_status():
    expr = f'namedprocess_namegroup_num_procs{{instance=~"{INSTANCES}"}}'
    return query(expr, interval_ms=15000, max_dp=163)

def detect_dead_process(response):
    alerts = []
    for frame in response["results"]["A"]["frames"]:
        labels = frame["schema"]["fields"][1]["labels"]
        grp, inst = labels.get("groupname",""), labels.get("instance","")
        latest = frame["data"]["values"][1][-1]
        if grp in BASELINE and latest != BASELINE[grp]:
            alerts.append({"groupname": grp, "instance": inst,
                           "expected": BASELINE[grp], "actual": latest})
    return alerts
```

---

### API-4: 서버 전체 메모리 사용률 — SQR326

- **용도:** 서버 수준 실질 메모리 사용률 (Free+Cached+Buffers를 가용으로 간주)
- **PromQL:** `(1-(node_memory_MemFree_bytes{instance=~"INSTANCES"}+node_memory_Cached_bytes+node_memory_Buffers_bytes)/node_memory_MemTotal_bytes)`
- **응답 단위:** 소수 (0~1) → **×100 변환 필요**

```python
def get_memory_usage():
    expr = f'(1-(node_memory_MemFree_bytes{{instance=~"{INSTANCES}"}}+node_memory_Cached_bytes+node_memory_Buffers_bytes)/node_memory_MemTotal_bytes)'
    return query(expr, interval_ms=15000, max_dp=376)
```

---

### API-5: 프로세스별 메모리 점유율 — SQR327

- **용도:** named process별 전체 메모리 대비 점유율 분해
- **PromQL:** `sum(namedprocess_namegroup_memory_bytes{instance=~"INSTANCES",memtype="resident"}) by(instance,groupname) / on(instance) group_left sum(node_memory_MemTotal_bytes{instance=~"INSTANCES"}) by(instance)`
- **응답 단위:** 소수 (0~1) → **×100 변환 필요**
- **refId:** B

```python
def get_process_memory():
    expr = f'sum(namedprocess_namegroup_memory_bytes{{instance=~"{INSTANCES}",memtype="resident"}}) by(instance,groupname)/on(instance) group_left sum(node_memory_MemTotal_bytes{{instance=~"{INSTANCES}"}}) by(instance)'
    return query(expr, ref_id="B", interval_ms=15000, max_dp=333)

def top_memory_consumers(response, top_n=5):
    items = []
    for frame in response["results"]["B"]["frames"]:
        labels = frame["schema"]["fields"][1]["labels"]
        latest = frame["data"]["values"][1][-1] * 100
        items.append({"groupname": labels.get("groupname",""),
                      "instance": labels.get("instance",""),
                      "mem_pct": round(latest, 4)})
    return sorted(items, key=lambda x: x["mem_pct"], reverse=True)[:top_n]
```

---

### API-6: 네트워크 I/O (Rx/Tx) — SQR328

- **용도:** 서버별 네트워크 수신/송신 속도 (bps)
- **특징:** 단일 요청에 쿼리 2개 (Multi-query 패턴)
- **refId:** A (Rx), B (Tx)
- **응답 단위:** bps → Mbps 변환 필요 (`÷1e6`)

```python
def get_network_io():
    now = int(time.time() * 1000)
    from_ms = str(now - 5 * 60 * 1000)
    payload = {
        "queries": [
            {
                "datasource": {"type": "prometheus", "uid": DS_UID},
                "expr": f'sum by(instance)(irate(node_network_receive_bytes_total{{instance=~"{INSTANCES}",device!~"^lo"}}[5m])*8)',
                "legendFormat": "{{instance}} - Rx",
                "refId": "A", "range": True,
                "intervalMs": 15000, "maxDataPoints": 376, "datasourceId": DS_ID
            },
            {
                "datasource": {"type": "prometheus", "uid": DS_UID},
                "expr": f'sum by(instance)(irate(node_network_transmit_bytes_total{{instance=~"{INSTANCES}",device!~"^lo"}}[5m])*8)',
                "legendFormat": "{{instance}} - Tx",
                "refId": "B", "range": True,
                "intervalMs": 15000, "maxDataPoints": 376, "datasourceId": DS_ID
            }
        ],
        "from": from_ms, "to": str(now)
    }
    return requests.post(GRAFANA_URL, headers=HEADERS, json=payload, verify=False).json()
```

---

## API 응답값 단위 정리 (파싱 필수 체크)

| API | refId | 응답값 형태 | 단위 | 변환 |
|-----|-------|------------|------|------|
| API-1 (SQR292) | A | `23.7` | % | 불필요 |
| API-2 (SQR293) | E | `0.237` | 소수 | **×100** |
| API-3 (SQR325) | A | `1`, `9` | 개수 | 불필요 |
| API-4 (SQR326) | A | `0.089` | 소수 | **×100** |
| API-5 (SQR327) | B | `0.007` | 소수 | **×100** |
| API-6 (SQR328) | A/B | `94031128.8` | bps | **÷1e6 (Mbps)** |

---

## LLM 연동 구조

```python
# 수집된 데이터를 요약해서 LLM에 전달
summary = {
    "timestamp": "2026-05-04 09:00",
    "servers": {
        "prautap1": {"cpu_pct": 23.7, "mem_pct": 14.5, "net_rx_mbps": 94.0},
        "prautdb1": {"cpu_pct": 8.1,  "mem_pct": 61.2, "net_rx_mbps": 12.3}
    },
    "dead_processes": [],
    "top_memory": [{"groupname": "Process DB(oracle)", "mem_pct": 45.2}]
}

prompt = f"""
다음은 금융시스템 서버 일일점검 결과입니다. 이상 여부를 분석하고 조치 우선순위를 알려주세요.
{json.dumps(summary, ensure_ascii=False, indent=2)}
"""

# llama.cpp (외부 개발 환경 — llama-server가 8080으로 실행 중인 상태)
response = requests.post("http://localhost:8080/v1/completions",
    json={"model": "qwen3-0.6b", "prompt": prompt, "stream": False})

# 사내 LLM (내부망 — config.yaml의 주소로 교체)
response = requests.post(config["llm"]["url"],
    headers={"Authorization": f"Bearer {config['llm']['api_key']}"},
    json={"model": config["llm"]["model"], "prompt": prompt})
```

---

## CLI 사용법

```bash
# 서버 분석
python main.py analyze --server prautap1 --time 1h

# 전체 서버 일일점검
python main.py daily-check

# 트렌드 분석
python main.py trend --days 7

# 리포트 파일 저장
python main.py daily-check --output report_20260504.md
```

---

## 개발 단계

| 단계 | 내용 | 상태 |
|------|------|------|
| 1 | Grafana API 연동 (`grafana_client.py`) | 분석 완료 |
| 2 | 6개 API 수집 구현 (`collector.py`) | 개발 필요 |
| 3 | 데이터 전처리/집계 (`preprocessor.py`) | 개발 필요 |
| 4 | LLM 연동 (`llm_client.py`) | 개발 필요 |
| 5 | CLI 구현 (`main.py`) | 개발 필요 |
| 6 | 리포트 생성 (`reporter.py`) | 개발 필요 |
| 7 | EXE 패키징 (PyInstaller) | 개발 필요 |
| 8 | 내부망 반입 및 사내 LLM 연동 | 미정 |

---

## 폐쇄망 반입 체크리스트

- [ ] 외부 개발 완료 (Mac/인터넷망)
- [ ] PyInstaller로 EXE 생성
- [ ] V3 백신 검사 수행
- [ ] HASH 값 확보
- [ ] 사용 라이브러리 목록 정리
- [ ] config.yaml에서 LLM URL → 사내 API 주소로 변경
- [ ] 망간 자료 전송 절차 준수
- [ ] 내부망 테스트 수행
