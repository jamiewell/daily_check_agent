# Grafana API 분석 정리

> 분석 대상: Chrome DevTools에서 캡처한 Grafana 대시보드 호출 API  
> 엔드포인트 공통: `POST https://grafana.shinhancard.com:3000/api/ds/query`  
> 인증 방식: Bearer Token (Service Account)  
> Datasource: Prometheus (`uid: aenzqagld59fke`, `id: 157`)

---

## 목차

1. [공통 호출 구조](#1-공통-호출-구조)
2. [변수화 가능 영역 총정리](#2-변수화-가능-영역-총정리)
3. [API별 상세 분석](#3-api별-상세-분석)
   - [API-1: CPU 사용률 (15분 윈도우)](#api-1-cpu-사용률-15분-윈도우--sqr292)
   - [API-2: CPU 사용률 (5분 윈도우)](#api-2-cpu-사용률-5분-윈도우--sqr293)
   - [API-3: 프로세스 수 모니터링](#api-3-프로세스-수-모니터링--sqr325)
   - [API-4: 서버 메모리 사용률](#api-4-서버-전체-메모리-사용률--sqr326)
   - [API-5: 프로세스별 메모리 점유율](#api-5-프로세스별-메모리-점유율--sqr327)
   - [API-6: 네트워크 I/O](#api-6-네트워크-io-rxTx--sqr328)
4. [패턴 및 주의사항](#4-패턴-및-주의사항)
5. [Python 파이프라인 활용 예시](#5-python-파이프라인-활용-예시)

---

## 1. 공통 호출 구조

### 요청

```
POST /api/ds/query?ds_type=prometheus&requestId={SQR번호}
Host: grafana.shinhancard.com:3000
Authorization: Bearer {SERVICE_ACCOUNT_TOKEN}
Content-Type: application/json
```

### 기본 요청 바디 구조

```json
{
  "queries": [
    {
      "datasource": {
        "type": "prometheus",
        "uid": "{datasource_uid}"
      },
      "expr":         "{PromQL 표현식}",
      "refId":        "{단일 알파벳, A~Z}",
      "requestId":    "{숫자+refId}",
      "range":        true,
      "editorMode":   "code",
      "legendFormat": "{레전드 포맷}",
      "intervalMs":   15000,
      "maxDataPoints": 300,
      "datasourceId": 157,
      "utcOffsetSec": 32400,
      "scopes":       [],
      "adhocFilters": []
    }
  ],
  "from": "{Unix ms 타임스탬프 또는 'now-5m'}",
  "to":   "{Unix ms 타임스탬프 또는 'now'}"
}
```

### 응답 구조

```json
{
  "results": {
    "{refId}": {
      "status": 200,
      "frames": [
        {
          "schema": {
            "refId": "{refId}",
            "meta": {
              "executedQueryString": "실제 실행된 PromQL\nStep: 15s"
            },
            "fields": [
              { "name": "Time",  "type": "time"   },
              { "name": "Value", "type": "number",
                "labels": { "instance": "...", "groupname": "..." },
                "config": { "displayNameFromDS": "레전드 표시명" }
              }
            ]
          },
          "data": {
            "values": [
              [타임스탬프 배열 (Unix ms)],
              [값 배열 (float64)]
            ]
          }
        }
      ]
    }
  }
}
```

---

## 2. 변수화 가능 영역 총정리

| 파라미터 | 위치 | 설명 | 변수 예시 |
|---|---|---|---|
| `SERVICE_ACCOUNT_TOKEN` | Header | Bearer 인증 토큰 | `glsa_xxx...` |
| `ds_type` | Query String | 데이터소스 타입 | `prometheus`, `loki` |
| `requestId` | Query String | 요청 식별자 (임의값 가능) | `SQR001`, `MY_REQ_1` |
| `datasource.uid` | Body | Datasource UID | `aenzqagld59fke` |
| `datasourceId` | Body | Datasource 숫자 ID | `157` |
| `expr` | Body | **PromQL 표현식** | 자유롭게 작성 가능 |
| `refId` | Body | 결과 키값 (A~Z) | `A`, `B`, `C` |
| `legendFormat` | Body | 응답 레전드 포맷 | `{{instance}}`, `{{groupname}}` |
| `intervalMs` | Body | 스크래핑 간격 (ms) | `5000`, `15000`, `60000` |
| `maxDataPoints` | Body | 최대 데이터 포인트 수 | `100` ~ `1000` |
| `from` | Body | 조회 시작 시각 (Unix ms) | `int(time.time()-3600)*1000` |
| `to` | Body | 조회 종료 시각 (Unix ms) | `int(time.time())*1000` |
| `range` | Body | 시계열 범위 조회 여부 | `true` (시계열) / `false` (instant) |
| `instant` | Body | 현재값 단일 조회 | `true`로 설정 시 최신값 1개만 반환 |
| `utcOffsetSec` | Body | 타임존 오프셋 | `32400` (KST=UTC+9) |

### `from` / `to` 활용 방법

```python
import time

# 방법 1: Unix milliseconds 직접 계산
now_ms       = int(time.time() * 1000)
one_hour_ago = now_ms - (60 * 60 * 1000)
one_day_ago  = now_ms - (24 * 60 * 60 * 1000)

# 방법 2: Grafana 상대 시간 문자열 (일부 버전 지원)
"from": "now-1h",
"to":   "now"

# 방법 3: 특정 날짜/시간 지정
from datetime import datetime
dt = datetime(2025, 5, 1, 9, 0, 0)
ms = int(dt.timestamp() * 1000)
```

### `intervalMs` / `maxDataPoints` 관계

```
step(초) ≈ (to - from) ms / maxDataPoints / 1000

예시:
  범위 5분(300초), maxDataPoints=300 → step ≈ 1초
  범위 5분(300초), maxDataPoints=21  → step ≈ 15초
```

---

## 3. API별 상세 분석

---

### API-1: CPU 사용률 (15분 윈도우) — SQR292

**목적:** AP서버/DB서버 CPU 사용률 트렌드 개요 (Overview 패널용)

#### 요청

```json
{
  "queries": [{
    "datasource": { "type": "prometheus", "uid": "{{DATASOURCE_UID}}" },
    "expr": "(sum by(instance) (irate(node_cpu_seconds_total{instance=~\"{{INSTANCE_FILTER}}\", mode!=\"idle\"}[{{WINDOW}}])) / on(instance) group_left sum by (instance)((irate(node_cpu_seconds_total{instance=~\"{{INSTANCE_FILTER}}\"}[{{WINDOW}}])))) * 100",
    "refId": "A",
    "legendFormat": "{{instance}}",
    "range": true,
    "intervalMs": 15000,
    "maxDataPoints": 120,
    "datasourceId": {{DATASOURCE_ID}}
  }],
  "from": "{{FROM_MS}}",
  "to":   "{{TO_MS}}"
}
```

#### 변수화 가능 영역

| 변수 | 기본값 | 설명 |
|---|---|---|
| `{{INSTANCE_FILTER}}` | `(prautap1\|prautdb1)` | 대상 인스턴스 정규식. 추가/변경 가능 |
| `{{WINDOW}}` | `15m` | irate 계산 윈도우. `5m`, `1m` 등으로 변경 |
| `{{FROM_MS}}` | 현재-5분 | Unix ms |
| `{{TO_MS}}` | 현재 | Unix ms |
| `maxDataPoints` | `120` | 포인트 수 조정으로 해상도 제어 |

#### 응답 특성

- **값 단위:** `%` (이미 ×100 적용됨) → `23.7`이면 `23.7%`
- **frame 수:** 인스턴스 수만큼 (2개)
- **레이블 키:** `labels.instance`

#### 파싱 코드

```python
def parse_cpu_api1(response: dict) -> dict:
    result = {}
    for frame in response["results"]["A"]["frames"]:
        instance = frame["schema"]["fields"][1]["labels"]["instance"]
        timestamps = frame["data"]["values"][0]
        values_pct = frame["data"]["values"][1]  # 이미 % 단위
        result[instance] = {"timestamps": timestamps, "cpu_pct": values_pct}
    return result
```

---

### API-2: CPU 사용률 (5분 윈도우) — SQR293

**목적:** AP서버/DB서버 CPU 사용률 실시간 세부 추이 (Detail 패널용)

#### 요청

```json
{
  "queries": [{
    "datasource": { "type": "prometheus", "uid": "{{DATASOURCE_UID}}" },
    "expr": "sum by(instance) (irate(node_cpu_seconds_total{instance=~\"{{INSTANCE_FILTER}}\", mode!='idle'}[{{WINDOW}}])) / on(instance) group_left sum by (instance)((irate(node_cpu_seconds_total{instance=~\"{{INSTANCE_FILTER}}\"}[{{WINDOW}}])))",
    "format": "time_series",
    "refId": "E",
    "legendFormat": "{{instance}}",
    "range": true,
    "intervalMs": 5000,
    "maxDataPoints": 376,
    "datasourceId": {{DATASOURCE_ID}}
  }],
  "from": "{{FROM_MS}}",
  "to":   "{{TO_MS}}"
}
```

#### API-1 vs API-2 핵심 차이

| 항목 | API-1 (SQR292) | API-2 (SQR293) |
|---|---|---|
| irate 윈도우 | `15m` | `5m` |
| step | `15s` | `5s` |
| intervalMs | `15000` | `5000` |
| maxDataPoints | `120` | `376` |
| 응답 포인트 수 | 21개 | 61개 |
| **값 단위** | **% (×100 적용)** | **소수 (0~1)** |
| 용도 | 트렌드 overview | 실시간 감지 |

#### ⚠️ 파싱 주의

```python
def parse_cpu_api2(response: dict) -> dict:
    result = {}
    for frame in response["results"]["E"]["frames"]:
        instance = frame["schema"]["fields"][1]["labels"]["instance"]
        values_raw = frame["data"]["values"][1]
        values_pct = [v * 100 for v in values_raw]  # 반드시 ×100 변환 필요
        result[instance] = values_pct
    return result
```

---

### API-3: 프로세스 수 모니터링 — SQR325

**목적:** 서버별 named process 가용성 감시 (프로세스가 살아있는지 확인)

#### 요청

```json
{
  "queries": [{
    "datasource": { "type": "prometheus", "uid": "{{DATASOURCE_UID}}" },
    "expr": "namedprocess_namegroup_num_procs{instance=~\"{{INSTANCE_FILTER}}\"}",
    "legendFormat": "{{groupname}} - {{instance}}",
    "refId": "A",
    "range": true,
    "intervalMs": 15000,
    "maxDataPoints": 163,
    "datasourceId": {{DATASOURCE_ID}}
  }],
  "from": "{{FROM_MS}}",
  "to":   "{{TO_MS}}"
}
```

#### 변수화 가능 영역

| 변수 | 기본값 | 설명 |
|---|---|---|
| `{{INSTANCE_FILTER}}` | `(prautap1\|prautdb1)` | 대상 서버 |
| `groupname` 필터 추가 | 없음 | `groupname=~"Process CDC.*"` 등 추가 가능 |

#### 변수 추가로 특정 그룹만 필터링하는 방법

```python
# 전체 프로세스
expr_all = 'namedprocess_namegroup_num_procs{instance=~"(prautap1|prautdb1)"}'

# CDC 프로세스만
expr_cdc = 'namedprocess_namegroup_num_procs{instance=~"(prautap1|prautdb1)", groupname=~"Process CDC.*"}'

# DB 프로세스만
expr_db = 'namedprocess_namegroup_num_procs{instance=~"(prautap1|prautdb1)", groupname=~"Process DB.*"}'

# Oracle 생존 여부
expr_oracle = 'namedprocess_namegroup_num_procs{instance="prautdb1", groupname=~"Process DB.*"}'
```

#### 응답 특성

- **값:** 정수 (프로세스 개수)
- **frame 수:** 프로세스 그룹 수 (36개 확인됨)
- **레이블 키:** `labels.groupname`, `labels.instance`
- **이상 감지:** 값이 0이면 프로세스 사망, 기대값과 다르면 비정상

#### 파싱 코드 — 이상 감지 포함

```python
# 기대 프로세스 수 기준값 (사전 정의 필요)
BASELINE = {
    "Process DB(ora_pmon_AUTDBP)": 1,
    "Process DB(tnslsnr)": 2,
    "Process SMS(ovcd)": 11,
}

def detect_anomaly(response: dict) -> list:
    alerts = []
    for frame in response["results"]["A"]["frames"]:
        labels   = frame["schema"]["fields"][1]["labels"]
        grp      = labels.get("groupname", "")
        inst     = labels.get("instance", "")
        latest   = frame["data"]["values"][1][-1]

        if grp in BASELINE and latest != BASELINE[grp]:
            alerts.append({
                "groupname": grp,
                "instance":  inst,
                "expected":  BASELINE[grp],
                "actual":    latest
            })
    return alerts
```

---

### API-4: 서버 전체 메모리 사용률 — SQR326

**목적:** 서버 수준의 실질 메모리 사용률 (Free+Cached+Buffers를 가용으로 간주)

#### 요청

```json
{
  "queries": [{
    "datasource": { "type": "prometheus", "uid": "{{DATASOURCE_UID}}" },
    "expr": "(1 - (node_memory_MemFree_bytes{instance=~\"{{INSTANCE_FILTER}}\"} + node_memory_Cached_bytes + node_memory_Buffers_bytes) / node_memory_MemTotal_bytes)",
    "format": "time_series",
    "refId": "A",
    "legendFormat": "{{instance}}",
    "range": true,
    "intervalMs": 15000,
    "maxDataPoints": 376,
    "datasourceId": {{DATASOURCE_ID}}
  }],
  "from": "{{FROM_MS}}",
  "to":   "{{TO_MS}}"
}
```

#### PromQL 수식 설명

```
실질 사용률 = 1 - (사용가능한 메모리 합계 / 전체 메모리)

사용가능한 메모리 = MemFree + Cached + Buffers
  - MemFree  : 완전히 비어 있는 메모리
  - Cached   : 파일 캐시 (필요시 즉시 반환됨)
  - Buffers  : I/O 버퍼 (필요시 즉시 반환됨)

→ 단순 MemFree만 쓰면 실제보다 사용량이 높게 나옴
```

#### 응답 특성

- **값 단위:** 소수 (0~1) → `0.089` = `8.9%`
- **파싱 시 ×100 변환 필요**

#### 파싱 코드

```python
def parse_memory(response: dict) -> dict:
    result = {}
    for frame in response["results"]["A"]["frames"]:
        instance = frame["schema"]["fields"][1]["labels"]["instance"]
        values   = frame["data"]["values"][1]
        latest   = values[-1] * 100  # % 변환
        result[instance] = {
            "mem_pct": round(latest, 2),
            "trend":   "up" if values[-1] > values[0] else "stable"
        }
    return result
```

---

### API-5: 프로세스별 메모리 점유율 — SQR327

**목적:** 각 named process가 전체 메모리의 몇 %를 점유하는지 분해

#### 요청

```json
{
  "queries": [{
    "datasource": { "type": "prometheus", "uid": "{{DATASOURCE_UID}}" },
    "expr": "sum (namedprocess_namegroup_memory_bytes{instance=~\"{{INSTANCE_FILTER}}\", memtype=\"{{MEM_TYPE}}\"}) by(instance, groupname) / on(instance) group_left sum(node_memory_MemTotal_bytes{instance=~\"{{INSTANCE_FILTER}}\"}) by (instance)",
    "legendFormat": "{{groupname}} [{{instance}}]",
    "refId": "B",
    "instant": false,
    "range": true,
    "intervalMs": 15000,
    "maxDataPoints": 333,
    "datasourceId": {{DATASOURCE_ID}}
  }],
  "from": "{{FROM_MS}}",
  "to":   "{{TO_MS}}"
}
```

#### 변수화 가능 영역

| 변수 | 기본값 | 설명 |
|---|---|---|
| `{{MEM_TYPE}}` | `resident` | `resident`(RSS 물리메모리), `virtual`(가상메모리), `swap` |
| `{{INSTANCE_FILTER}}` | `(prautap1\|prautdb1)` | 대상 서버 |

#### API-4 vs API-5 관계

```
API-4: 서버 전체 메모리 사용률
  → "prautap1이 전체의 14.5%를 사용 중"

API-5: 프로세스별 메모리 점유율
  → "그 중 ds_agent가 0.7%, Symagent가 0.39%..."

주의: API-4 합계 ≠ API-5 합계
  → API-5는 process_exporter가 감시하는 named process만 포함
  → OS 커널, 익명 프로세스 등은 제외됨
```

#### 파싱 코드 — 상위 소비 프로세스 추출

```python
def top_memory_consumers(response: dict, top_n: int = 5) -> list:
    items = []
    for frame in response["results"]["B"]["frames"]:
        labels   = frame["schema"]["fields"][1]["labels"]
        grp      = labels.get("groupname", "")
        inst     = labels.get("instance", "")
        latest   = frame["data"]["values"][1][-1] * 100  # % 변환
        items.append({"groupname": grp, "instance": inst, "mem_pct": round(latest, 4)})

    return sorted(items, key=lambda x: x["mem_pct"], reverse=True)[:top_n]
```

---

### API-6: 네트워크 I/O (Rx/Tx) — SQR328

**목적:** 서버별 네트워크 수신(Rx)/송신(Tx) 속도 모니터링 (bps 단위)

#### ⭐ 특징: 단일 요청에 쿼리 2개 (Multi-query 패턴)

```json
{
  "queries": [
    {
      "expr": "sum by(instance) (irate(node_network_receive_bytes_total{instance=~\"{{INSTANCE_FILTER}}\", device=~\"{{DEVICE_FILTER}}\", device!~\"^lo\"}[{{WINDOW}}]) * 8)",
      "legendFormat": "{{instance}} - Rx",
      "refId": "A",
      "format": "time_series",
      "intervalMs": 15000,
      "maxDataPoints": 376,
      "datasourceId": {{DATASOURCE_ID}}
    },
    {
      "expr": "sum by(instance) (irate(node_network_transmit_bytes_total{instance=~\"{{INSTANCE_FILTER}}\", device=~\"{{DEVICE_FILTER}}\", device!~\"^lo\"}[{{WINDOW}}]) * 8)",
      "legendFormat": "{{instance}} - Tx",
      "refId": "B",
      "format": "time_series",
      "intervalMs": 15000,
      "maxDataPoints": 376,
      "datasourceId": {{DATASOURCE_ID}}
    }
  ],
  "from": "{{FROM_MS}}",
  "to":   "{{TO_MS}}"
}
```

#### 변수화 가능 영역

| 변수 | 기본값 | 설명 |
|---|---|---|
| `{{DEVICE_FILTER}}` | `(bond0\|bond1\|ens192\|...)` | NIC 이름 필터. 환경에 맞게 변경 |
| `{{WINDOW}}` | `5m` | irate 윈도우 |
| `* 8` | 고정 | bytes → bits 변환. bps 단위로 출력됨 |

#### 단위 변환 방법

```python
def bps_to_human(bps: float) -> str:
    if bps >= 1e9:
        return f"{bps/1e9:.2f} Gbps"
    elif bps >= 1e6:
        return f"{bps/1e6:.2f} Mbps"
    elif bps >= 1e3:
        return f"{bps/1e3:.2f} Kbps"
    return f"{bps:.0f} bps"
```

#### Multi-query 파싱 코드

```python
def parse_network(response: dict) -> dict:
    result = {"rx": {}, "tx": {}}

    # Rx 파싱 (results["A"])
    for frame in response["results"]["A"]["frames"]:
        instance = frame["schema"]["fields"][1]["labels"]["instance"]
        values   = frame["data"]["values"][1]
        result["rx"][instance] = {
            "latest_bps": values[-1],
            "latest_human": bps_to_human(values[-1]),
            "avg_bps": sum(values) / len(values)
        }

    # Tx 파싱 (results["B"])
    for frame in response["results"]["B"]["frames"]:
        instance = frame["schema"]["fields"][1]["labels"]["instance"]
        values   = frame["data"]["values"][1]
        result["tx"][instance] = {
            "latest_bps": values[-1],
            "latest_human": bps_to_human(values[-1]),
            "avg_bps": sum(values) / len(values)
        }

    return result
```

---

## 4. 패턴 및 주의사항

### 4-1. 응답값 단위 비교 (파이프라인 필수 확인)

| API | refId | 값 형태 | 단위 | 변환 필요 |
|---|---|---|---|---|
| API-1 (SQR292) | A | `23.7` | % (이미 ×100) | ❌ |
| API-2 (SQR293) | E | `0.237` | 소수 | ✅ ×100 |
| API-3 (SQR325) | A | `1`, `9`, `13` | 개수 (정수) | ❌ |
| API-4 (SQR326) | A | `0.089` | 소수 | ✅ ×100 |
| API-5 (SQR327) | B | `0.007` | 소수 | ✅ ×100 |
| API-6 (SQR328) | A/B | `94031128.8` | bps | ✅ ÷1e6 (Mbps) |

### 4-2. 중복 API 호출 패턴

동일 쿼리가 두 번 요청되는 케이스가 확인됨. 캐시로 절반 절약 가능합니다.

```python
import hashlib, json

_cache = {}

def cached_query(url, headers, payload):
    cache_key = hashlib.md5(
        json.dumps({"expr": payload["queries"][0]["expr"],
                    "from": payload["from"],
                    "to":   payload["to"]}, sort_keys=True).encode()
    ).hexdigest()

    if cache_key in _cache:
        return _cache[cache_key]

    resp = requests.post(url, headers=headers, json=payload, verify=False)
    _cache[cache_key] = resp.json()
    return _cache[cache_key]
```

### 4-3. Multi-query 활용 시 results 분리 파싱

```python
response = requests.post(...).json()

rx_frames = response["results"]["A"]["frames"]  # Rx
tx_frames = response["results"]["B"]["frames"]  # Tx
```

### 4-4. 타임스탬프 계단형 패턴

irate 윈도우(5m, 15m)보다 step이 짧으면 동일 값이 반복되는 계단형 응답이 나타납니다. 이는 정상 동작입니다.

```python
# 중복 값 제거 후 실제 변화 포인트만 추출
def deduplicate(values: list) -> list:
    return [v for i, v in enumerate(values)
            if i == 0 or v != values[i-1]]
```

### 4-5. 교차 분석 활용 — API 간 상관관계

```
CPU 스파이크 감지 (API-2)
  + 동시간 프로세스 수 변동 (API-3)
  + 메모리 급증 여부 (API-5)
  + 네트워크 트래픽 변화 (API-6)
  → LLM에 압축 요약 전달 → Notion 인시던트 자동 기록
```

---

## 5. Python 파이프라인 활용 예시

### 전체 파이프라인 통합 호출

```python
import requests
import time

GRAFANA_URL = "https://grafana.shinhancard.com:3000/api/ds/query"
TOKEN       = "glsa_cpeM80mba6oAaeh1TRZdfQ8BcnC69L4F_b2d9b460"
DS_UID      = "aenzqagld59fke"
DS_ID       = 157
INSTANCES   = "(prautap1|prautdb1)"

HEADERS = {
    "Authorization": f"Bearer {TOKEN}",
    "Content-Type": "application/json"
}

def make_time_range(minutes: int = 5):
    now = int(time.time() * 1000)
    return str(now - minutes * 60 * 1000), str(now)

def query(expr: str, ref_id: str = "A",
          minutes: int = 5, interval_ms: int = 15000,
          max_dp: int = 300) -> dict:
    from_ms, to_ms = make_time_range(minutes)
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
            "scopes": [],
            "adhocFilters": []
        }],
        "from": from_ms,
        "to":   to_ms
    }
    resp = requests.post(GRAFANA_URL, headers=HEADERS,
                         json=payload, verify=False)
    return resp.json()

# 사용 예시
cpu_data  = query(f'(sum by(instance)(irate(node_cpu_seconds_total{{instance=~"{INSTANCES}",mode!="idle"}}[5m]))/on(instance) group_left sum by(instance)(irate(node_cpu_seconds_total{{instance=~"{INSTANCES}"}}[5m])))*100')
mem_data  = query(f'(1-(node_memory_MemFree_bytes{{instance=~"{INSTANCES}"}}+node_memory_Cached_bytes+node_memory_Buffers_bytes)/node_memory_MemTotal_bytes)')
proc_data = query(f'namedprocess_namegroup_num_procs{{instance=~"{INSTANCES}"}}')
```

### Prometheus 메트릭 탐색 (대시보드 없이)

```python
# 수집 중인 모든 메트릭 이름 조회
meta_url = f"https://grafana.shinhancard.com:3000/api/datasources/proxy/{DS_ID}/api/v1/label/__name__/values"
resp = requests.get(meta_url, headers=HEADERS, verify=False)
all_metrics = resp.json()["data"]
print(f"총 {len(all_metrics)}개 메트릭 수집 중")

# 특정 인스턴스의 모든 레이블 확인
label_url = f"https://grafana.shinhancard.com:3000/api/datasources/proxy/{DS_ID}/api/v1/labels"
resp = requests.get(label_url, headers=HEADERS,
                    params={"match[]": f'{{instance="prautdb1"}}'}, verify=False)
print(resp.json())
```

---

*작성 기준: Chrome DevTools 캡처 API 분석 결과 (SQR292~SQR328)*
