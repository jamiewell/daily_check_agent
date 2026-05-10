# 서버 종합 상태 점검 — Grafana API 호출 목록

> 목적: AP/DB 서버 종합 상태를 REST API로 자동 점검  
> 대상: 단일 서버 / 복수 서버 / 전체 서버 자유롭게 선택  
> 시간: 실시간 / 오늘 / 특정 날짜 / 임의 구간 자유롭게 지정  
> 기준: 실제 캡처 API 샘플(SQR203~SQR328) 분석 결과

---

## 1. 고정 파라미터 (환경 설정)

```python
# 절대 바뀌지 않는 값 — 최초 1회만 설정
GRAFANA_URL = "https://grafana.shinhancard.com:3000/api/ds/query"
TOKEN       = "glsa_cpeM80mba6oAaeh1TRZdfQ8BcnC69L4F_b2d9b460"
DS_UID      = "aenzqagld59fke"
DS_ID       = 157
UTC_OFFSET  = 32400   # KST (UTC+9)

HEADERS = {
    "Authorization": f"Bearer {TOKEN}",
    "Content-Type": "application/json"
}
```

| 파라미터 | 고정값 | 비고 |
|---|---|---|
| `datasource.type` | `prometheus` | 전 API 동일 |
| `datasource.uid` | `aenzqagld59fke` | 전 API 동일 |
| `datasourceId` | `157` | 전 API 동일 |
| `utcOffsetSec` | `32400` | KST 고정 |
| `range` | `true` | 시계열 조회 고정 |
| `exemplar` | `false` | 전 API 동일 |
| `scopes` / `adhocFilters` / `interval` | `[]` / `[]` / `""` | 전 API 동일 |

> **requestId / ds_type 은 넣지 않아도 됩니다**  
> 캡처된 원본 API URL에 `?ds_type=prometheus&requestId=SQR292` 형태가 붙어 있지만,  
> 이는 **Grafana 대시보드 UI가 패널별 요청을 추적하려고 자동으로 붙이는 값**입니다.  
> Prometheus 서버는 이 값을 완전히 무시하며, 직접 호출 시 URL과 바디 모두에서 생략해도 응답은 동일합니다.
>
> ```
> ❌ 캡처된 원본:  POST /api/ds/query?ds_type=prometheus&requestId=SQR292
> ✅ 직접 호출:   POST /api/ds/query
> ```
>
> **최소 필수 파라미터:** `datasource.uid` + `expr` + `refId` + `from` + `to`

---

## 2. 서버 대상 선택

### 호스트명 명명 규칙

운영 환경의 호스트명은 아래 규칙으로 구성됩니다.

```
{환경prefix}{업무코드}{서버역할}{번호}

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
| **번호** | `1`, `2`, `3` ... | 서버 번호 (HA/이중화 구성) |

**예시 호스트명:**

| 호스트명 | 환경 | 업무 | 역할 | 번호 |
|---|---|---|---|---|
| `prautap1` | 운영(pr) | 승인(aut) | AP | 1 |
| `prautap2` | 운영(pr) | 승인(aut) | AP | 2 |
| `prautdb1` | 운영(pr) | 승인(aut) | DB | 1 |
| `prautdb2` | 운영(pr) | 승인(aut) | DB | 2 |
| `teautap1` | 테스트(te) | 승인(aut) | AP | 1 |
| `teautdb1` | 테스트(te) | 승인(aut) | DB | 1 |
| `dvautap1` | 개발(dv) | 승인(aut) | AP | 1 |

---

### 서버 필터 구성

PromQL의 `instance=~"..."` 정규식을 활용해 대상 서버를 자유롭게 조합합니다.

```python
def make_instance_filter(
    env:   str  = "pr",    # 환경: pr / te / dv
    app:   str  = "aut",   # 업무코드: aut / ...
    roles: list = None,    # 역할: ["ap"] / ["db"] / ["ap","db"] / None=전체
    nums:  list = None,    # 번호: [1] / [1,2] / None=전체
) -> str:
    """
    호스트명 규칙 기반 instance 정규식 필터 생성

    사용 예:
        make_instance_filter("pr", "aut", ["ap"])        → "prautap[0-9]+"
        make_instance_filter("pr", "aut", ["db"])        → "prautdb[0-9]+"
        make_instance_filter("pr", "aut", ["ap","db"])   → "praut(ap|db)[0-9]+"
        make_instance_filter("pr", "aut", ["ap"], [1])   → "prautap1"
        make_instance_filter("pr", "aut", ["ap"], [1,2]) → "prautap1|prautap2"
        make_instance_filter("te", "aut", ["ap"])        → "teautap[0-9]+"
        make_instance_filter("pr", "aut")                → "praut(ap|db)[0-9]+" (전체)
    """
    if roles is None:
        roles = ["ap", "db"]

    if nums is not None:
        # 번호 지정: 명시적 호스트명 열거
        hosts = [f"{env}{app}{role}{n}" for role in roles for n in nums]
        return "|".join(hosts)
    else:
        # 번호 미지정: 정규식으로 전체 매칭
        if len(roles) == 1:
            return f"{env}{app}{roles[0]}[0-9]+"
        else:
            role_pattern = "|".join(roles)
            return f"{env}{app}({role_pattern})[0-9]+"

# ── 자주 쓰는 조합 ───────────────────────────────────────
# 운영 AP서버 전체
make_instance_filter("pr", "aut", ["ap"])            # → prautap[0-9]+

# 운영 DB서버 전체
make_instance_filter("pr", "aut", ["db"])            # → prautdb[0-9]+

# 운영 AP + DB 전체
make_instance_filter("pr", "aut")                    # → praut(ap|db)[0-9]+

# 운영 AP 1번 서버 (장애 대응 시 단일 서버 집중 점검)
make_instance_filter("pr", "aut", ["ap"], [1])       # → prautap1

# 운영 AP 1, 2번 서버
make_instance_filter("pr", "aut", ["ap"], [1, 2])    # → prautap1|prautap2

# 운영 AP 1번 + DB 1번 (pair 점검)
make_instance_filter("pr", "aut", ["ap", "db"], [1]) # → prautap1|prautdb1

# 테스트 환경 전체
make_instance_filter("te", "aut")                    # → teaut(ap|db)[0-9]+

# 개발 AP서버만
make_instance_filter("dv", "aut", ["ap"])            # → dvautap[0-9]+

# 직접 지정 (규칙 외 케이스)
INSTANCE = "prautap1"
```

---

## 3. 시간 범위 선택

조회 목적에 따라 6가지 방식을 자유롭게 선택할 수 있습니다.

```python
import time
from datetime import datetime, date, timedelta

def time_range(mode: str = "today", **kwargs) -> tuple[str, str]:
    """
    mode 목록:
        "realtime"   → 현재 기준 최근 N분 (기본 5분)
        "today"      → 오늘 00:00 ~ 현재
        "yesterday"  → 어제 00:00 ~ 23:59
        "date"       → 특정 날짜 전체 (date="2025-05-01")
        "range"      → 임의 구간 (start="2025-05-01 09:00", end="2025-05-01 18:00")
        "hours"      → 현재 기준 최근 N시간 (hours=6)
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
```

### 시간 범위 사용 예시

```python
# 최근 5분 (실시간 감시)
from_ms, to_ms = time_range("realtime", minutes=5)

# 오늘 하루 전체
from_ms, to_ms = time_range("today")

# 어제 하루 전체
from_ms, to_ms = time_range("yesterday")

# 특정 날짜 전체
from_ms, to_ms = time_range("date", date="2025-05-01")

# 임의 구간 (장애 발생 전후 2시간)
from_ms, to_ms = time_range("range", start="2025-05-01 13:00", end="2025-05-01 15:00")

# 최근 6시간
from_ms, to_ms = time_range("hours", hours=6)
```

### 시간 범위별 권장 intervalMs / maxDataPoints

| 조회 범위 | 권장 intervalMs | 권장 maxDataPoints | step 결과 |
|---|---|---|---|
| 5분 이내 (실시간) | `15000` | `300` | ~1초 |
| 1시간 | `60000` | `300` | ~12초 |
| 6시간 | `60000` | `300` | ~1분 |
| 오늘 / 24시간 | `300000` | `300` | ~5분 |
| 2~7일 | `3600000` | `300` | ~1시간 |
| 1개월 | `3600000` | `720` | ~1시간 |

```python
def auto_interval(from_ms: str, to_ms: str, max_dp: int = 300) -> int:
    """
    조회 범위에 따라 intervalMs 자동 계산
    step(ms) = 범위(ms) / maxDataPoints
    """
    duration_ms = int(to_ms) - int(from_ms)
    step_ms     = duration_ms // max_dp

    # 최솟값 보정 (15초 미만이면 15초로)
    return max(step_ms, 15000)

# 사용 예
interval_ms = auto_interval(from_ms, to_ms, max_dp=300)
```

---

## 4. 공통 쿼리 빌더

```python
def build_query(
    expr:        str,
    ref_id:      str = "A",
    legend:      str = "{{instance}}",
    interval_ms: int = 300000,
    max_dp:      int = 300
) -> dict:
    """공통 쿼리 객체 생성 — 변하지 않는 파라미터는 자동 포함"""
    return {
        "datasource":   {"type": "prometheus", "uid": DS_UID},
        "expr":         expr,
        "refId":        ref_id,
        "legendFormat": legend,
        "range":        True,
        "intervalMs":   interval_ms,
        "maxDataPoints": max_dp,
        "datasourceId": DS_ID,
        "utcOffsetSec": UTC_OFFSET,
        "scopes":       [],
        "adhocFilters": [],
        "interval":     ""
    }

def call_api(queries: list, from_ms: str, to_ms: str) -> dict:
    payload = {"queries": queries, "from": from_ms, "to": to_ms}
    resp = requests.post(GRAFANA_URL, headers=HEADERS,
                         json=payload, verify=False)
    return resp.json()
```

---

## 5. 점검 API 목록

모든 CHECK에서 `INSTANCE`와 `from_ms / to_ms`는 위 2, 3번 설정에서 자유롭게 주입합니다.

---

### CHECK-01. CPU 사용률 (서버 전체)

**목적:** 서버 전체 CPU 부하 확인  
**지원 서버:** AP / DB / 동시  
**임계값:** 80% → WARN / 95% → CRITICAL

```python
def check_cpu(instance: str, from_ms: str, to_ms: str,
              interval_ms: int = 300000) -> dict:
    expr = (
        f"(sum by(instance)"
        f"(irate(node_cpu_seconds_total{{instance=~\"{instance}\",mode!=\"idle\"}}[5m]))"
        f" / on(instance) group_left"
        f" sum by(instance)(irate(node_cpu_seconds_total{{instance=~\"{instance}\"}}[5m])))"
        f" * 100"
    )
    q   = build_query(expr, legend="{{instance}} CPU%", interval_ms=interval_ms)
    raw = call_api([q], from_ms, to_ms)
    return raw
    # 값 단위: % (이미 ×100 적용됨)
    # 임계값: warn=80, critical=95
```

---

### CHECK-02. 메모리 사용률 (서버 전체)

**목적:** 실질 메모리 사용량 확인 (Free+Cached+Buffers를 가용으로 간주)  
**지원 서버:** AP / DB / 동시  
**임계값:** 85% → WARN / 95% → CRITICAL  
**참고:** 응답값은 소수 → 파싱 시 ×100 필요

```python
def check_memory(instance: str, from_ms: str, to_ms: str,
                 interval_ms: int = 300000) -> dict:
    expr = (
        f"(1 - (node_memory_MemFree_bytes{{instance=~\"{instance}\"}}"
        f" + node_memory_Cached_bytes"
        f" + node_memory_Buffers_bytes)"
        f" / node_memory_MemTotal_bytes)"
    )
    q   = build_query(expr, legend="{{instance}} MEM%", interval_ms=interval_ms)
    raw = call_api([q], from_ms, to_ms)
    return raw
    # 값 단위: 소수 (0~1) → ×100 = %
    # 임계값: warn=0.85, critical=0.95
```

---

### CHECK-03. 네트워크 Rx/Tx (이더넷)

**목적:** 이더넷 트래픽 트렌드 확인  
**지원 서버:** AP 전용 (DB는 InfiniBand 위주 — CHECK-03b 참조)  
**임계값:** Rx 150Mbps → WARN / 200Mbps → CRITICAL  
**참고:** Multi-query (Rx + Tx 동시)

```python
def check_network_eth(instance: str, from_ms: str, to_ms: str,
                      interval_ms: int = 300000) -> dict:
    devices = "ens192|ens224"
    qA = build_query(
        f"sum by(instance)(irate(node_network_receive_bytes_total{{instance=~\"{instance}\",device=~\"({devices})\",device!~\"^lo\"}}[5m])*8)",
        ref_id="A", legend="{{instance}} - Rx", interval_ms=interval_ms
    )
    qB = build_query(
        f"sum by(instance)(irate(node_network_transmit_bytes_total{{instance=~\"{instance}\",device=~\"({devices})\",device!~\"^lo\"}}[5m])*8)",
        ref_id="B", legend="{{instance}} - Tx", interval_ms=interval_ms
    )
    raw = call_api([qA, qB], from_ms, to_ms)
    return raw
    # 값 단위: bps → ÷1e6 = Mbps
    # 파싱: results["A"] = Rx, results["B"] = Tx
```

### CHECK-03b. 네트워크 Rx/Tx (전체 NIC — InfiniBand 포함)

**목적:** InfiniBand 포함 전체 트래픽 실시간 감시  
**지원 서버:** AP / DB / 동시

```python
def check_network_all(instance: str, from_ms: str, to_ms: str,
                      interval_ms: int = 15000) -> dict:
    devices = (
        "bond0|bond1|bond2|ens192|ens224|"
        "r001i01s00p0|r001i01s00p1|r001i01s00p2|r001i01s00p3|"
        "r001i01s01p0|r001i01s01p1|r001i01s07p0|r001i01s07p1|"
        "r001i01s10p0|r001i01s10p1|r001i01s15p0|r001i01s15p1|"
        "r001i06s02p0|r001i06s02p1|r001i06s07p0|r001i06s07p1|"
        "r001i06s10p0|r001i06s10p1|r001i06s15p0|r001i06s15p1|"
        "r001i11s02p0|r001i11s02p1|r001i11s07p0|r001i11s07p1|"
        "r001i11s10p0|r001i11s10p1"
    )
    qA = build_query(
        f"sum by(instance)(irate(node_network_receive_bytes_total{{instance=~\"{instance}\",device=~\"({devices})\",device!~\"^lo\"}}[5m])*8)",
        ref_id="A", legend="{{instance}} - Rx", interval_ms=interval_ms
    )
    qB = build_query(
        f"sum by(instance)(irate(node_network_transmit_bytes_total{{instance=~\"{instance}\",device=~\"({devices})\",device!~\"^lo\"}}[5m])*8)",
        ref_id="B", legend="{{instance}} - Tx", interval_ms=interval_ms
    )
    return call_api([qA, qB], from_ms, to_ms)
```

---

### CHECK-04. 디스크 Read/Write 속도

**목적:** 디스크 I/O 이상 감지  
**지원 서버:** AP / DB / 동시  
**임계값:** Read 10MB/s → WARN / 50MB/s → CRITICAL  
**참고:** ×8 변환 없음 (bytes/s 그대로)

```python
def check_disk(instance: str, from_ms: str, to_ms: str,
               interval_ms: int = 300000) -> dict:
    devices = "sda|sdb|sdc|sdd|sde|sdf"
    qA = build_query(
        f"sum by(instance)(irate(node_disk_read_bytes_total{{instance=~\"{instance}\",device=~\"({devices})\"}}[5m]))",
        ref_id="A", legend="{{instance}} - Read", interval_ms=interval_ms
    )
    qB = build_query(
        f"sum by(instance)(irate(node_disk_written_bytes_total{{instance=~\"{instance}\",device=~\"({devices})\"}}[5m]))",
        ref_id="B", legend="{{instance}} - Write", interval_ms=interval_ms
    )
    return call_api([qA, qB], from_ms, to_ms)
    # 값 단위: bytes/s → ÷1e6 = MB/s (×8 불필요)
    # 파싱: results["A"] = Read, results["B"] = Write
```

---

### CHECK-05. 프로세스 수 (가용성 감시)

**목적:** 핵심 프로세스 생존 여부 확인  
**지원 서버:** AP / DB / 동시 (서버별 BASELINE 분리)  
**임계값:** 기대값과 다르면 즉시 WARN / 0개면 CRITICAL

```python
# 서버별 프로세스 기대값 (SQR325 분석 기준)
PROCESS_BASELINE = {
    "prautap1": {
        "CMS": 1, "CloudESM": 1, "Control-M Agent": 8,
        "Control-Minder": 5, "NTP": 1,
        "Secuguard System Explorer": 1, "Symagent": 2, "ds_agent": 6,
    },
    "prautdb1": {
        "AUT_mgauge(mxg_obsd)": 1, "AUT_mgauge(mxg_rts)": 1,
        "AUT_mgauge(mxg_sndf)": 1, "CloudESM": 1, "NTP": 1,
        "Netbackup(/usr/openv/netbackup/bin)": 9,
        "Process DB(ora_ckpt_AUTDBP)": 1, "Process DB(ora_pmon_AUTDBP)": 1,
        "Process DB(ora_smon_AUTDBP)": 1, "Process DB(tnslsnr)": 2,
        "Process SMS(ovcd)": 11, "SEOS": 5,
        "SecuMS": 1, "Symagent": 2, "Trend Micro": 6,
    }
}

def check_process(instance: str, from_ms: str, to_ms: str) -> dict:
    q   = build_query(
        f"namedprocess_namegroup_num_procs{{instance=~\"{instance}\"}}",
        legend="{{groupname}} - {{instance}}",
        interval_ms=15000, max_dp=1   # 최신값 1개만
    )
    return call_api([q], from_ms, to_ms)
    # 파싱: labels["groupname"] + labels["instance"] → 기대값 비교
```

---

### CHECK-06. 프로세스별 CPU 점유율

**목적:** CPU 소비 상위 프로세스 분해  
**지원 서버:** AP / DB / 동시  
**임계값:** ds_agent 0.5% → WARN / 0.8% → CRITICAL

```python
def check_process_cpu(instance: str, from_ms: str, to_ms: str,
                      interval_ms: int = 300000) -> dict:
    expr = (
        f"sum by (instance, groupname)"
        f"(rate(namedprocess_namegroup_cpu_seconds_total{{instance=~\"{instance}\"}}[2m]))"
        f" / on(instance) group_left"
        f" sum by (instance)(rate(node_cpu_seconds_total{{instance=~\"{instance}\"}}[2m]))"
    )
    q = build_query(expr, legend="{{groupname}} [{{instance}}]",
                    interval_ms=interval_ms)
    return call_api([q], from_ms, to_ms)
    # 값 단위: 소수 → ×100 = %
```

---

### CHECK-07. 프로세스별 메모리 점유율

**목적:** 메모리 소비 상위 프로세스 분해  
**지원 서버:** AP / DB / 동시  
**임계값:** ds_agent 1.0% → WARN / 2.0% → CRITICAL

```python
def check_process_memory(instance: str, from_ms: str, to_ms: str,
                         interval_ms: int = 300000) -> dict:
    expr = (
        f"sum(namedprocess_namegroup_memory_bytes{{instance=~\"{instance}\",memtype=\"resident\"}})"
        f" by(instance, groupname)"
        f" / on(instance) group_left"
        f" sum(node_memory_MemTotal_bytes{{instance=~\"{instance}\"}}) by(instance)"
    )
    q = build_query(expr, legend="{{groupname}} [{{instance}}]",
                    interval_ms=interval_ms)
    return call_api([q], from_ms, to_ms)
    # 값 단위: 소수 → ×100 = %
```

---

## 6. 통합 점검 실행

```python
import requests
import time
from datetime import datetime, date, timedelta

def run_health_check(
    env:          str       = "pr",    # 환경: pr / te / dv
    app:          str       = "aut",   # 업무코드: aut / ...
    roles:        list      = None,    # 역할: ["ap"] / ["db"] / ["ap","db"] / None=전체
    nums:         list      = None,    # 번호: [1] / [1,2] / None=전체
    time_mode:    str       = "today",
    checks:       list[str] = ["cpu", "memory", "network", "disk", "process", "proc_cpu", "proc_mem"],
    **time_kwargs
) -> dict:
    """
    파라미터:
        env        : 환경 — "pr"(운영) / "te"(테스트) / "dv"(개발)
        app        : 업무코드 — "aut"(승인) / 기타
        roles      : 서버 역할 — ["ap"] / ["db"] / ["ap","db"] / None(전체)
        nums       : 서버 번호 — [1] / [1,2] / None(전체)
        time_mode  : "realtime" / "today" / "yesterday" / "date" / "range" / "hours"
        checks     : 실행할 점검 항목 목록 (생략 시 전체)
        **time_kwargs: time_range() 에 전달할 추가 인자

    사용 예:
        # 운영 AP서버 오늘 전체 점검
        run_health_check(env="pr", app="aut", roles=["ap"], time_mode="today")

        # 운영 AP+DB 어제 점검
        run_health_check(env="pr", app="aut", time_mode="yesterday")

        # 운영 AP 1번 서버 장애 구간 집중 점검
        run_health_check(env="pr", app="aut", roles=["ap"], nums=[1],
                         time_mode="range",
                         start="2025-05-01 13:00", end="2025-05-01 15:00",
                         checks=["cpu", "memory", "network"])

        # 테스트 전체 서버 최근 1시간
        run_health_check(env="te", app="aut", time_mode="hours", hours=1)

        # 개발 AP서버만 오늘 CPU/메모리
        run_health_check(env="dv", app="aut", roles=["ap"],
                         time_mode="today", checks=["cpu", "memory"])
    """

    instance    = make_instance_filter(env, app, roles, nums)
    from_ms, to_ms = time_range(time_mode, **time_kwargs)
    interval_ms = auto_interval(from_ms, to_ms)
    report      = {"instance": instance, "from": from_ms, "to": to_ms, "checks": {}}

    # CHECK-01: CPU
    if "cpu" in checks:
        raw    = check_cpu(instance, from_ms, to_ms, interval_ms)
        result = {}
        for frame in raw["results"]["A"]["frames"]:
            inst   = frame["schema"]["fields"][1]["labels"].get("instance", "?")
            vals   = frame["data"]["values"][1]
            result[inst] = {
                "avg_pct": round(sum(vals) / len(vals), 2),
                "max_pct": round(max(vals), 2),
                "status":  "critical" if max(vals) > 95 else "warn" if max(vals) > 80 else "ok"
            }
        report["checks"]["cpu"] = result

    # CHECK-02: 메모리
    if "memory" in checks:
        raw    = check_memory(instance, from_ms, to_ms, interval_ms)
        result = {}
        for frame in raw["results"]["A"]["frames"]:
            inst   = frame["schema"]["fields"][1]["labels"].get("instance", "?")
            vals   = [v * 100 for v in frame["data"]["values"][1]]
            result[inst] = {
                "latest_pct": round(vals[-1], 2),
                "max_pct":    round(max(vals), 2),
                "status":     "critical" if vals[-1] > 95 else "warn" if vals[-1] > 85 else "ok"
            }
        report["checks"]["memory"] = result

    # CHECK-03: 네트워크
    if "network" in checks:
        raw    = check_network_eth(instance, from_ms, to_ms, interval_ms)
        result = {}
        for frame in raw["results"]["A"]["frames"]:
            inst  = frame["schema"]["fields"][1]["labels"].get("instance", "?")
            vals  = frame["data"]["values"][1]
            result[inst] = {
                "rx_avg_mbps": round(sum(vals)/len(vals)/1e6, 2),
                "rx_max_mbps": round(max(vals)/1e6, 2),
                "status":      "warn" if max(vals) > 150e6 else "ok"
            }
        report["checks"]["network"] = result

    # CHECK-05: 프로세스 수
    if "process" in checks:
        raw       = check_process(instance, from_ms, to_ms)
        anomalies = {}
        for frame in raw["results"]["A"]["frames"]:
            labels = frame["schema"]["fields"][1]["labels"]
            inst   = labels.get("instance", "?")
            grp    = labels.get("groupname", "?")
            actual = frame["data"]["values"][1][-1] if frame["data"]["values"][1] else 0
            baseline_inst = PROCESS_BASELINE.get(inst, {})
            if grp in baseline_inst and actual != baseline_inst[grp]:
                anomalies.setdefault(inst, {})[grp] = {
                    "expected": baseline_inst[grp], "actual": actual,
                    "status": "critical" if actual == 0 else "warn"
                }
        report["checks"]["process"] = {
            "anomalies": anomalies,
            "status":    "critical" if any(
                v.get("status") == "critical"
                for inst_dict in anomalies.values()
                for v in inst_dict.values()
            ) else "warn" if anomalies else "ok"
        }

    return report


# ── 결과 출력 ───────────────────────────────────────────
def print_report(report: dict):
    print(f"\n{'='*55}")
    print(f"  점검 대상: {report['instance']}")
    ts = lambda ms: datetime.fromtimestamp(int(ms)/1000).strftime("%Y-%m-%d %H:%M")
    print(f"  점검 구간: {ts(report['from'])} ~ {ts(report['to'])}")
    print(f"{'='*55}")

    icons = {"ok": "🟢", "warn": "🟡", "critical": "🔴"}

    for check, data in report["checks"].items():
        print(f"\n[{check.upper()}]")
        if isinstance(data, dict) and "anomalies" in data:
            icon = icons.get(data.get("status", "ok"), "❓")
            print(f"  {icon} 이상 프로세스: {data['anomalies'] or '없음'}")
        else:
            for inst, d in data.items():
                icon = icons.get(d.get("status", "ok"), "❓")
                print(f"  {icon} {inst}: {d}")


# ── 실행 예시 ───────────────────────────────────────────
if __name__ == "__main__":

    # 예시 1: 운영 AP서버 오늘 전체 점검
    report = run_health_check(env="pr", app="aut", roles=["ap"],
                              time_mode="today")
    print_report(report)

    # 예시 2: 운영 AP+DB 어제 CPU/메모리만
    report = run_health_check(env="pr", app="aut",
                              time_mode="yesterday",
                              checks=["cpu", "memory"])
    print_report(report)

    # 예시 3: 운영 AP 1번 서버 장애 구간 집중 점검
    report = run_health_check(env="pr", app="aut", roles=["ap"], nums=[1],
                              time_mode="range",
                              start="2025-05-01 13:00",
                              end="2025-05-01 15:00",
                              checks=["cpu", "memory", "network", "process"])
    print_report(report)

    # 예시 4: 테스트 환경 전체 서버 최근 1시간
    report = run_health_check(env="te", app="aut",
                              time_mode="hours", hours=1)
    print_report(report)
```

---

## 7. 임계값 기준표

### 서버 공통

| Check | 메트릭 | WARN | CRITICAL | 단위 처리 |
|---|---|---|---|---|
| CHECK-01 | CPU 사용률 | 80% | 95% | 이미 ×100 적용 |
| CHECK-02 | 메모리 사용률 | 85% | 95% | 소수 ×100 필요 |
| CHECK-03 | 네트워크 Rx | 150 Mbps | 200 Mbps | bps ÷1e6 |
| CHECK-04 | 디스크 Read | 10 MB/s | 50 MB/s | bytes/s ÷1e6 |
| CHECK-05 | 프로세스 수 | 기대값 불일치 | 0개 (소멸) | 정수 그대로 |
| CHECK-06 | 프로세스 CPU | 0.5% | 0.8% | 소수 ×100 필요 |
| CHECK-07 | 프로세스 MEM | 1.0% | 2.0% | 소수 ×100 필요 |

### 서버별 기준값 참고 (실측 기준)

| 항목 | prautap1 (AP) | prautdb1 (DB) |
|---|---|---|
| CPU 평균 | ~24% | ~37% |
| 메모리 평균 | ~14.85% | ~8.94% |
| 네트워크 Rx 피크 | ~121 Mbps (이더넷) | ~1,560 Mbps (InfiniBand 포함) |
| 디스크 Write 평균 | ~1 MB/s | 미측정 |

---

## 8. 빠른 사용 가이드

```
호스트명 구조  →  {환경(pr/te/dv)}{업무코드(aut)}{역할(ap/db)}{번호(1,2...)}

점검 대상 선택 →  make_instance_filter(env, app, roles, nums)
                  env  : "pr"(운영) / "te"(테스트) / "dv"(개발)
                  app  : "aut"(승인)
                  roles: ["ap"] / ["db"] / ["ap","db"] / None(전체)
                  nums : [1] / [1,2] / None(전체)

시간 범위 선택 →  time_range("today"/"yesterday"/"date"/"range"/"hours"/"realtime")
점검 항목 선택 →  checks=["cpu","memory","network","disk","process","proc_cpu","proc_mem"]
실행           →  run_health_check(env, app, roles, nums, time_mode, checks, **kwargs)
결과 출력      →  print_report(report)
```

---

*기준 데이터: Chrome DevTools 캡처 API 분석 (SQR203~SQR328)*  
*호스트명 규칙: {환경(pr/te/dv)}{업무코드(aut)}{역할(ap/db)}{번호(1,2...)}*  
*실측 서버: prautap1 (운영 승인 AP 1번), prautdb1 (운영 승인 DB 1번)*