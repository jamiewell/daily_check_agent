# Grafana API 분석 정리

> 분석 대상: Chrome DevTools에서 캡처한 Grafana 대시보드 호출 API  
> 엔드포인트 공통: `POST https://grafana.shinhancard.com:3000/api/ds/query`  
> 인증 방식: Bearer Token (Service Account)  
> Datasource: Prometheus (`uid: aenzqagld59fke`, `id: 157`)

---

## 목차

1. [공통 호출 구조](#1-공통-호출-구조)
2. [변수화 가능 영역 총정리](#2-변수화-가능-영역-총정리)
   - [서버 대상 선택](#서버-대상-선택--instance-필터)
   - [시간 범위 6가지 모드](#from--to-활용-방법--6가지-시간-범위-모드)
   - [intervalMs 자동 계산](#intervalms--maxdatapoints-관계--자동-계산)
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
POST /api/ds/query
Host: grafana.shinhancard.com:3000
Authorization: Bearer {SERVICE_ACCOUNT_TOKEN}
Content-Type: application/json
```

> **URL 파라미터 (`ds_type`, `requestId`)는 생략 가능합니다.**  
> - `?ds_type=prometheus` — Grafana UI가 내부 라우팅에 쓰는 힌트. 바디의 `datasource.type`으로 이미 명시되므로 없어도 동일하게 동작합니다.  
> - `?requestId=SQR292` — Grafana 대시보드가 **어떤 패널이 보낸 요청인지 추적하려고 붙이는 UI 내부용 식별자**입니다. 서버(Prometheus)는 이 값을 완전히 무시합니다. 직접 호출 시 URL에서 제거해도 응답은 동일합니다.

### 기본 요청 바디 구조

```json
{
  "queries": [
    {
      "datasource": {
        "type": "prometheus",
        "uid": "{datasource_uid}"
      },
      "expr":          "{PromQL 표현식}",
      "refId":         "{단일 알파벳, A~Z}",
      "range":         true,
      "intervalMs":    15000,
      "maxDataPoints": 300,
      "datasourceId":  157,
      "utcOffsetSec":  32400,

      "requestId":     "{생략 가능 — Grafana UI 추적용, 서버 무시}",
      "legendFormat":  "{{instance}}",
      "scopes":        [],
      "adhocFilters":  [],
      "interval":      "",
      "exemplar":      false
    }
  ],
  "from": "{Unix ms 타임스탬프}",
  "to":   "{Unix ms 타임스탬프}"
}
```

> **실제 직접 호출 시 최소 구성 (requestId 등 생략)**
>
> ```json
> {
>   "queries": [{
>     "datasource": {"type": "prometheus", "uid": "aenzqagld59fke"},
>     "expr":       "{PromQL}",
>     "refId":      "A",
>     "intervalMs": 300000,
>     "maxDataPoints": 300,
>     "datasourceId": 157,
>     "range": true
>   }],
>   "from": "1778175000000",
>   "to":   "1778261637000"
> }
> ```

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
| `ds_type` | Query String | ❌ **생략 가능** — 바디의 `datasource.type`과 중복 | `prometheus` |
| `requestId` | Query String | ❌ **생략 가능** — Grafana UI 내부 추적용. 서버는 무시 | `SQR001` |
| `queries[].requestId` | Body | ❌ **생략 가능** — URL의 requestId와 동일한 UI 추적용 | `4A` |
| `datasource.uid` | Body | ✅ **필수** — 어떤 데이터소스인지 식별 | `aenzqagld59fke` |
| `datasourceId` | Body | ✅ **권장** — uid와 함께 있으면 안정적 | `157` |
| `expr` | Body | ✅ **필수** — PromQL 표현식 | 자유롭게 작성 가능 |
| `refId` | Body | ✅ **필수** — 응답 파싱 키 (A~Z) | `A`, `B`, `C` |
| `from` / `to` | Body | ✅ **필수** — 조회 시간 범위 (Unix ms) | `str(now_ms)` |
| `legendFormat` | Body | 응답 레전드 포맷 | `{{instance}}`, `{{groupname}}` |
| `intervalMs` | Body | 수집 간격 (ms) | `15000`, `300000` |
| `maxDataPoints` | Body | 최대 데이터 포인트 수 | `100` ~ `1000` |
| `range` | Body | 시계열 범위 조회 여부 | `true` (시계열) / `false` (instant) |
| `instant` | Body | 현재값 단일 조회 | `true`로 설정 시 최신값 1개만 반환 |
| `utcOffsetSec` | Body | 타임존 오프셋 | `32400` (KST=UTC+9) |
| `exemplar` / `scopes` / `adhocFilters` / `interval` | Body | ❌ **생략 가능** — Grafana UI 내부용 | `false`, `[]`, `[]`, `""` |

> **최소 필수 파라미터 요약:** `datasource.uid` + `expr` + `refId` + `from` + `to`  
> 이 5개만 있으면 동작합니다. 나머지는 모두 선택입니다.

### 서버 대상 선택 — `instance` 필터

#### 호스트명 명명 규칙

운영 환경의 호스트명은 아래 4개 요소의 조합으로 구성됩니다.

```
{환경}{업무코드}{서버역할}{번호}

예:  pr  aut  ap  1
     │    │    │   └─ 서버 번호 (1, 2, 3, 4 ...)
     │    │    └───── 서버 역할 (ap=애플리케이션, db=데이터베이스)
     │    └────────── 업무 코드 (aut=승인, 그 외 업무코드 추가 가능)
     └─────────────── 환경 구분 (pr=운영, te=테스트, dv=개발)
```

| 구분 | 값 | 의미 |
|---|---|---|
| **환경** | `pr` | 운영 (Production) |
| | `te` | 테스트 (Test) |
| | `dv` | 개발 (Development) |
| **업무코드** | `aut` | 카드 승인 업무 |
| **서버역할** | `ap` | 애플리케이션 서버 |
| | `db` | 데이터베이스 서버 |
| **번호** | `1`, `2`, `3` ... | 서버 번호 (HA/이중화) |

**호스트명 예시:**

| 호스트명 | 환경 | 업무 | 역할 | 번호 |
|---|---|---|---|---|
| `prautap1` | 운영(pr) | 승인(aut) | AP | 1 |
| `prautap2` | 운영(pr) | 승인(aut) | AP | 2 |
| `prautdb1` | 운영(pr) | 승인(aut) | DB | 1 |
| `teautap1` | 테스트(te) | 승인(aut) | AP | 1 |
| `dvautap1` | 개발(dv) | 승인(aut) | AP | 1 |

#### 서버 필터 생성

`expr` 안의 `instance=~"..."` 정규식만 바꾸면 환경/업무/역할/번호를 자유롭게 조합할 수 있습니다.

```python
def make_instance_filter(
    env:   str  = "pr",    # 환경: pr / te / dv
    app:   str  = "aut",   # 업무코드: aut / ...
    roles: list = None,    # 역할: ["ap"] / ["db"] / ["ap","db"] / None=전체
    nums:  list = None,    # 번호: [1] / [1,2] / None=전체
) -> str:
    """
    사용 예:
        make_instance_filter("pr", "aut", ["ap"])        → "prautap[0-9]+"
        make_instance_filter("pr", "aut", ["db"])        → "prautdb[0-9]+"
        make_instance_filter("pr", "aut")                → "praut(ap|db)[0-9]+"
        make_instance_filter("pr", "aut", ["ap"], [1])   → "prautap1"
        make_instance_filter("pr", "aut", ["ap"], [1,2]) → "prautap1|prautap2"
        make_instance_filter("te", "aut", ["ap"])        → "teautap[0-9]+"
        make_instance_filter("dv", "aut")                → "dvaut(ap|db)[0-9]+"
    """
    if roles is None:
        roles = ["ap", "db"]

    if nums is not None:
        hosts = [f"{env}{app}{role}{n}" for role in roles for n in nums]
        return "|".join(hosts)
    else:
        if len(roles) == 1:
            return f"{env}{app}{roles[0]}[0-9]+"
        else:
            role_pattern = "|".join(roles)
            return f"{env}{app}({role_pattern})[0-9]+"

# ── 자주 쓰는 조합 ───────────────────────────────────────
instance = make_instance_filter("pr", "aut", ["ap"])          # 운영 AP 전체
instance = make_instance_filter("pr", "aut", ["db"])          # 운영 DB 전체
instance = make_instance_filter("pr", "aut")                  # 운영 전체
instance = make_instance_filter("pr", "aut", ["ap"], [1])     # 운영 AP 1번만
instance = make_instance_filter("pr", "aut", ["ap"], [1, 2])  # 운영 AP 1,2번
instance = make_instance_filter("te", "aut")                  # 테스트 전체
instance = make_instance_filter("dv", "aut", ["ap"])          # 개발 AP 전체
```

PromQL expr 안에 적용하는 방법입니다.

```python
instance = make_instance_filter("pr", "aut", ["ap"])
# → "prautap[0-9]+"

expr = f'node_cpu_seconds_total{{instance=~"{instance}",mode!="idle"}}'
# → node_cpu_seconds_total{instance=~"prautap[0-9]+",mode!="idle"}
```

---

### `from` / `to` 활용 방법 — 6가지 시간 범위 모드

```python
import time
from datetime import datetime, date, timedelta

def time_range(mode: str = "today", **kwargs) -> tuple:
    """
    mode 목록:
        "realtime"   → 현재 기준 최근 N분       (기본 5분)
        "today"      → 오늘 00:00 ~ 현재
        "yesterday"  → 어제 00:00 ~ 23:59
        "date"       → 특정 날짜 전체            (date="2025-05-01")
        "range"      → 임의 구간                 (start="2025-05-01 09:00", end="2025-05-01 18:00")
        "hours"      → 현재 기준 최근 N시간      (hours=6)
    반환: (from_ms, to_ms) 문자열 튜플
    """
    now_ms = int(time.time() * 1000)

    if mode == "realtime":
        minutes = kwargs.get("minutes", 5)
        return str(now_ms - minutes * 60 * 1000), str(now_ms)

    elif mode == "today":
        today = date.today()
        start = int(datetime(today.year, today.month, today.day).timestamp() * 1000)
        return str(start), str(now_ms)

    elif mode == "yesterday":
        yesterday = date.today() - timedelta(days=1)
        start = int(datetime(yesterday.year, yesterday.month, yesterday.day, 0, 0, 0).timestamp() * 1000)
        end   = int(datetime(yesterday.year, yesterday.month, yesterday.day, 23, 59, 59).timestamp() * 1000)
        return str(start), str(end)

    elif mode == "date":
        dt    = datetime.strptime(kwargs["date"], "%Y-%m-%d")
        start = int(dt.replace(hour=0, minute=0, second=0).timestamp() * 1000)
        end   = int(dt.replace(hour=23, minute=59, second=59).timestamp() * 1000)
        return str(start), str(end)

    elif mode == "range":
        start = int(datetime.strptime(kwargs["start"], "%Y-%m-%d %H:%M").timestamp() * 1000)
        end   = int(datetime.strptime(kwargs["end"],   "%Y-%m-%d %H:%M").timestamp() * 1000)
        return str(start), str(end)

    elif mode == "hours":
        hours = kwargs.get("hours", 1)
        return str(now_ms - hours * 3600 * 1000), str(now_ms)

    else:
        raise ValueError(f"알 수 없는 mode: {mode}")

# 사용 예
from_ms, to_ms = time_range("realtime", minutes=5)                          # 최근 5분
from_ms, to_ms = time_range("today")                                         # 오늘 전체
from_ms, to_ms = time_range("yesterday")                                     # 어제 전체
from_ms, to_ms = time_range("date", date="2025-05-01")                       # 특정 날짜
from_ms, to_ms = time_range("range", start="2025-05-01 13:00",
                                      end="2025-05-01 15:00")                # 임의 구간
from_ms, to_ms = time_range("hours", hours=6)                                # 최근 6시간
```

---

### `intervalMs` / `maxDataPoints` 관계 — 자동 계산

```
step(초) ≈ (to - from) ms / maxDataPoints / 1000

예시:
  범위 5분(300초), maxDataPoints=300 → step ≈ 1초
  범위 5분(300초), maxDataPoints=21  → step ≈ 15초
```

조회 범위가 달라질 때 `intervalMs`도 함께 조정하지 않으면 포인트 수가 폭발합니다.  
아래 함수로 자동 계산할 수 있습니다.

```python
def auto_interval(from_ms: str, to_ms: str, max_dp: int = 300) -> int:
    """조회 범위에 따라 intervalMs 자동 계산 (최솟값 15초 보정)"""
    duration_ms = int(to_ms) - int(from_ms)
    step_ms     = duration_ms // max_dp
    return max(step_ms, 15000)   # 15초 미만이면 15초로 보정

# 사용 예 — 조회 범위와 상관없이 항상 적정 step 유지
from_ms, to_ms  = time_range("date", date="2025-05-01")
interval_ms     = auto_interval(from_ms, to_ms)   # 자동으로 ~5분 step
```

### 조회 범위별 권장 설정

| 조회 범위 | 권장 intervalMs | 권장 maxDataPoints | 결과 step |
|---|---|---|---|
| 5분 이내 (실시간) | `15,000` | `300` | ~1초 |
| 1시간 | `60,000` | `300` | ~12초 |
| 6시간 | `60,000` | `300` | ~1분 |
| 24시간 (오늘/어제) | `300,000` | `300` | ~5분 |
| 2~7일 | `3,600,000` | `300` | ~1시간 |
| 1개월 | `3,600,000` | `720` | ~1시간 |

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

### 공통 설정 및 빌더

```python
import requests
import time
from datetime import datetime, date, timedelta

GRAFANA_URL = "https://grafana.shinhancard.com:3000/api/ds/query"
TOKEN       = "glsa_cpeM80mba6oAaeh1TRZdfQ8BcnC69L4F_b2d9b460"
DS_UID      = "aenzqagld59fke"
DS_ID       = 157

HEADERS = {
    "Authorization": f"Bearer {TOKEN}",
    "Content-Type": "application/json"
}

# 섹션 2의 make_instance_filter(), time_range(), auto_interval() 함수 포함 가정

def build_query(expr, ref_id="A", legend="{{instance}}",
                interval_ms=300000, max_dp=300):
    """공통 쿼리 객체 생성"""
    return {
        "datasource":    {"type": "prometheus", "uid": DS_UID},
        "expr":          expr,
        "refId":         ref_id,
        "legendFormat":  legend,
        "range":         True,
        "intervalMs":    interval_ms,
        "maxDataPoints": max_dp,
        "datasourceId":  DS_ID,
        "utcOffsetSec":  32400,
        "scopes":        [],
        "adhocFilters":  [],
        "interval":      ""
    }

def call_api(queries: list, from_ms: str, to_ms: str) -> dict:
    payload = {"queries": queries, "from": from_ms, "to": to_ms}
    resp = requests.post(GRAFANA_URL, headers=HEADERS,
                         json=payload, verify=False)
    return resp.json()
```

### 서버 대상 + 시간 범위 조합 예시

```python
# ── 대상 서버 선택 ─────────────────────────────────────
instance = make_instance_filter("ap")           # AP서버만
instance = make_instance_filter("db")           # DB서버만
instance = make_instance_filter("ap", "db")     # AP + DB 동시
instance = make_instance_filter("all")          # 전체

# ── 시간 범위 선택 ─────────────────────────────────────
from_ms, to_ms = time_range("realtime", minutes=5)                       # 최근 5분
from_ms, to_ms = time_range("today")                                      # 오늘 전체
from_ms, to_ms = time_range("yesterday")                                  # 어제 전체
from_ms, to_ms = time_range("date", date="2025-05-01")                    # 특정 날짜
from_ms, to_ms = time_range("range",
                             start="2025-05-01 13:00",
                             end="2025-05-01 15:00")                      # 임의 구간
from_ms, to_ms = time_range("hours", hours=6)                             # 최근 6시간

# ── intervalMs 자동 계산 ────────────────────────────────
interval_ms = auto_interval(from_ms, to_ms)   # 범위에 맞는 step 자동 결정

# ── 쿼리 조합 및 호출 ───────────────────────────────────
cpu_q  = build_query(
    f'(sum by(instance)(irate(node_cpu_seconds_total{{instance=~"{instance}",mode!="idle"}}[5m]))'
    f' / on(instance) group_left sum by(instance)(irate(node_cpu_seconds_total{{instance=~"{instance}"}}[5m]))) * 100',
    interval_ms=interval_ms
)
mem_q  = build_query(
    f'(1-(node_memory_MemFree_bytes{{instance=~"{instance}"}}+node_memory_Cached_bytes+node_memory_Buffers_bytes)/node_memory_MemTotal_bytes)',
    interval_ms=interval_ms
)
proc_q = build_query(
    f'namedprocess_namegroup_num_procs{{instance=~"{instance}"}}',
    legend="{{groupname}} - {{instance}}",
    interval_ms=interval_ms
)

# 단일 호출로 여러 메트릭 동시 수집 (queries 배열에 조합)
raw = call_api([cpu_q, mem_q, proc_q], from_ms, to_ms)

# 결과 파싱 — refId로 분리
cpu_frames  = raw["results"]["A"]["frames"]
mem_frames  = raw["results"]["A"]["frames"]   # 별도 refId 설정 시 분리
proc_frames = raw["results"]["A"]["frames"]
```

### 실전 조합 시나리오

```python
# 시나리오 1: AP서버 오늘 하루 CPU/메모리 트렌드
instance = make_instance_filter("ap")
from_ms, to_ms = time_range("today")
interval_ms = auto_interval(from_ms, to_ms)   # → 300,000 (5분)

# 시나리오 2: AP+DB 어제 장애 구간 집중 분석
instance = make_instance_filter("ap", "db")
from_ms, to_ms = time_range("range",
                             start="2025-05-01 13:00",
                             end="2025-05-01 15:00")
interval_ms = auto_interval(from_ms, to_ms)   # → 24,000 (24초)

# 시나리오 3: DB서버 최근 6시간 프로세스 감시
instance = make_instance_filter("db")
from_ms, to_ms = time_range("hours", hours=6)
interval_ms = auto_interval(from_ms, to_ms)   # → 72,000 (72초)

# 시나리오 4: 전체 서버 실시간 5분 스냅샷
instance = make_instance_filter("all")
from_ms, to_ms = time_range("realtime", minutes=5)
interval_ms = 15000                           # 실시간은 15초 고정
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

*작성 기준: Chrome DevTools 캡처 API 분석 결과 (SQR203~SQR328)*  
*지원 서버: prautap1 (AP), prautdb1 (DB) — 단일/복수/전체 자유 선택*  
*시간 범위: realtime / today / yesterday / date / range / hours 6가지 모드 지원*