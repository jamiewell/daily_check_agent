# Grafana AI 에이전트 MVP 설계 문서

> 목적: 금융시스템 업무PC 일일점검 자동화 데모 및 내부 테스트  
> 범위: 대화형 구조 + grafana_client.py + preprocessor.py  
> LLM: Ollama 로컬 (사내 LLM API 확정 전 Ollama로 대체)  
> 제약: 폐쇄망 EXE 배포, 외부 통신 금지

---

## 목차

1. [MVP 범위 정의](#1-mvp-범위-정의)
2. [전체 아키텍처](#2-전체-아키텍처)
3. [대화형 에이전트 구조 설계](#3-대화형-에이전트-구조-설계)
4. [grafana_client.py 설계](#4-grafana_clientpy-설계)
5. [preprocessor.py 설계](#5-preprocessorpy-설계)
6. [프로젝트 구조](#6-프로젝트-구조)
7. [config.yaml 설계](#7-configyaml-설계)
8. [실행 흐름 예시](#8-실행-흐름-예시)

---

## 1. MVP 범위 정의

### 포함

| 기능 | 설명 |
|---|---|
| 대화형 CLI | 자연어 질의 → 에이전트 응답 루프 |
| 일일점검 | 운영 AP/DB 서버 종합 상태 자동 수집·분석 |
| 단순 질의 | "prautap1 CPU 지금 어때?" 같은 즉석 조회 |
| LLM 분석 | 전처리 요약 → Ollama → 분석 코멘트 생성 |
| 결과 출력 | CLI 출력 + Markdown 파일 저장 |

### 제외 (MVP 이후)

- SMTP 메일 발송
- 사내 메신저 연동
- EXE 패키징 (개발 단계에서는 Python 직접 실행)
- 사내 LLM API 연동

---

## 2. 전체 아키텍처

```
[사용자 자연어 입력]
        │
        ▼
[main.py — 대화 루프]
        │
        ├─ 의도 분류 (Intent Classifier)
        │       │
        │       ├─ "일일점검"    ──▶ [grafana_client.py] ──▶ [preprocessor.py] ──▶ [ollama_client.py]
        │       ├─ "서버 조회"   ──▶ [grafana_client.py] ──▶ [preprocessor.py] ──▶ [ollama_client.py]
        │       ├─ "리포트 저장" ──▶ [reporter.py]
        │       └─ "종료"        ──▶ exit
        │
        ▼
[결과 출력 (CLI + 선택적 파일 저장)]
```

### 데이터 흐름

```
Grafana API 응답 (raw JSON)
        │
        ▼  grafana_client.py
frames 파싱 → {name, timestamps, values, latest, avg, max}
        │
        ▼  preprocessor.py
통계 집계 + 이상 감지 → 압축 요약 텍스트 (~1,500 토큰)
        │
        ▼  ollama_client.py
LLM 프롬프트 조합 → 분석 코멘트 (상태요약 / 원인 / 조치)
        │
        ▼
CLI 출력 / Markdown 저장
```

---

## 3. 대화형 에이전트 구조 설계

### 3.1 기본 구조 — 대화 루프

단발 CLI(`agent.exe --server app01`)가 아닌 **대화 루프** 방식.  
사용자가 종료 명령 전까지 맥락을 유지하며 연속 질의가 가능합니다.

```python
# main.py

def main():
    print("=== Grafana AI 에이전트 (MVP) ===")
    print("종료: 'exit' 또는 'quit'\n")

    agent = Agent()

    while True:
        try:
            user_input = input("질문 > ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n종료합니다.")
            break

        if not user_input:
            continue

        if user_input.lower() in ("exit", "quit", "종료"):
            print("종료합니다.")
            break

        response = agent.handle(user_input)
        print(f"\n{response}\n")
```

### 3.2 Agent 클래스 — 맥락 유지

```python
# src/agent.py

class Agent:
    def __init__(self):
        self.config    = load_config()           # config.yaml 로드
        self.client    = GrafanaClient(self.config)
        self.processor = Preprocessor()
        self.llm       = OllamaClient(self.config)
        self.context   = {}                      # 마지막 조회 결과 캐시

    def handle(self, user_input: str) -> str:
        intent, params = self._classify(user_input)

        if intent == "daily_check":
            return self._daily_check(params)

        elif intent == "server_query":
            return self._server_query(params)

        elif intent == "save_report":
            return self._save_report()

        elif intent == "show_last":
            return self._show_last()

        else:
            return self._fallback(user_input)

    def _classify(self, text: str) -> tuple:
        """
        간단한 키워드 기반 의도 분류 (MVP는 LLM 분류 없이 키워드만 사용)
        """
        text_lower = text.lower()

        # 일일점검
        if any(k in text for k in ["일일점검", "점검", "전체", "daily"]):
            env, app, roles, nums = self._extract_server_params(text)
            return "daily_check", {"env": env, "app": app,
                                   "roles": roles, "nums": nums}

        # 서버 단순 조회
        if any(k in text for k in ["CPU", "cpu", "메모리", "memory",
                                    "네트워크", "디스크", "프로세스"]):
            env, app, roles, nums = self._extract_server_params(text)
            metric = self._extract_metric(text)
            return "server_query", {"env": env, "app": app,
                                    "roles": roles, "nums": nums,
                                    "metric": metric}

        # 리포트 저장
        if any(k in text for k in ["저장", "파일", "리포트", "report", "save"]):
            return "save_report", {}

        # 이전 결과 보기
        if any(k in text for k in ["다시", "이전", "결과", "방금"]):
            return "show_last", {}

        return "unknown", {}

    def _extract_server_params(self, text: str) -> tuple:
        """텍스트에서 환경/역할/번호 추출 (키워드 매칭)"""
        env  = "te" if "테스트" in text else "dv" if "개발" in text else "pr"
        roles = []
        if any(k in text for k in ["AP", "ap", "앱", "애플리케이션"]):
            roles.append("ap")
        if any(k in text for k in ["DB", "db", "데이터베이스"]):
            roles.append("db")
        if not roles:
            roles = None  # 전체

        # 번호 추출 (1, 2, 3 ...)
        import re
        nums_found = re.findall(r'\b([1-9])\b', text)
        nums = [int(n) for n in nums_found] if nums_found else None

        return env, "aut", roles, nums

    def _extract_metric(self, text: str) -> str:
        if any(k in text for k in ["CPU", "cpu", "씨피유"]):
            return "cpu"
        if any(k in text for k in ["메모리", "memory", "mem"]):
            return "memory"
        if any(k in text for k in ["네트워크", "network", "트래픽"]):
            return "network"
        if any(k in text for k in ["디스크", "disk"]):
            return "disk"
        if any(k in text for k in ["프로세스", "process"]):
            return "process"
        return "all"
```

### 3.3 의도 분류 — MVP 키워드 방식

MVP에서는 LLM을 의도 분류에 쓰지 않습니다.  
키워드 매칭으로 충분하며, 분류 실패 시 사용 가이드를 안내합니다.

```python
def _fallback(self, user_input: str) -> str:
    return (
        "죄송합니다, 이해하지 못했습니다.\n\n"
        "사용 가능한 명령 예시:\n"
        "  • '일일점검' — 운영 서버 전체 상태 점검\n"
        "  • 'AP서버 CPU 확인' — 특정 메트릭 조회\n"
        "  • 'DB 1번 메모리' — 특정 서버 조회\n"
        "  • '리포트 저장' — 마지막 결과를 파일로 저장\n"
        "  • 'exit' — 종료"
    )
```

### 3.4 맥락 유지 방식

MVP는 단순하게 **마지막 조회 결과만 메모리에 보관**합니다.

```python
# context 구조
self.context = {
    "last_check_time": "2025-05-09 09:00:00",
    "last_instance":   "prautap1|prautdb1",
    "last_summary":    "...(전처리 요약 텍스트)...",
    "last_report":     "...(LLM 분석 결과)..."
}

# "다시 보여줘" 처리
def _show_last(self) -> str:
    if not self.context:
        return "아직 조회한 결과가 없습니다."
    return (
        f"[마지막 조회: {self.context['last_check_time']}]\n"
        f"대상: {self.context['last_instance']}\n\n"
        f"{self.context['last_report']}"
    )
```

---

## 4. grafana_client.py 설계

### 4.1 역할

- Grafana REST API 호출
- 응답 파싱 → 표준 데이터 구조 반환
- 호스트명 규칙 기반 instance 필터 자동 생성

### 4.2 전체 코드

```python
# src/grafana_client.py

import requests
import time
from datetime import datetime, date, timedelta


class GrafanaClient:

    def __init__(self, config: dict):
        self.url     = config["grafana"]["url"]          # https://grafana.xxx:3000/api/ds/query
        self.token   = config["grafana"]["token"]        # glsa_xxx...
        self.ds_uid  = config["grafana"]["ds_uid"]       # aenzqagld59fke
        self.ds_id   = config["grafana"]["ds_id"]        # 157
        self.headers = {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json"
        }

    # ── 호스트명 필터 ────────────────────────────────────
    def make_instance_filter(
        self,
        env:   str  = "pr",     # pr / te / dv
        app:   str  = "aut",    # 업무코드
        roles: list = None,     # ["ap"] / ["db"] / ["ap","db"] / None=전체
        nums:  list = None,     # [1] / [1,2] / None=전체
    ) -> str:
        """
        호스트명 규칙: {환경(pr/te/dv)}{업무코드(aut)}{역할(ap/db)}{번호}
        예: make_instance_filter("pr","aut",["ap"],[1]) → "prautap1"
            make_instance_filter("pr","aut",["ap"])     → "prautap[0-9]+"
            make_instance_filter("pr","aut")            → "praut(ap|db)[0-9]+"
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
                return f"{env}{app}({'|'.join(roles)})[0-9]+"

    # ── 시간 범위 ────────────────────────────────────────
    def time_range(self, mode: str = "today", **kwargs) -> tuple:
        """
        mode: realtime / today / yesterday / date / range / hours
        반환: (from_ms, to_ms) 문자열 튜플
        """
        now_ms = int(time.time() * 1000)

        if mode == "realtime":
            minutes = kwargs.get("minutes", 5)
            return str(now_ms - minutes * 60 * 1000), str(now_ms)

        elif mode == "today":
            d = date.today()
            start = int(datetime(d.year, d.month, d.day).timestamp() * 1000)
            return str(start), str(now_ms)

        elif mode == "yesterday":
            d = date.today() - timedelta(days=1)
            start = int(datetime(d.year, d.month, d.day, 0, 0, 0).timestamp() * 1000)
            end   = int(datetime(d.year, d.month, d.day, 23, 59, 59).timestamp() * 1000)
            return str(start), str(end)

        elif mode == "date":
            dt    = datetime.strptime(kwargs["date"], "%Y-%m-%d")
            start = int(dt.replace(hour=0,  minute=0,  second=0).timestamp()  * 1000)
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
            raise ValueError(f"알 수 없는 time mode: {mode}")

    def auto_interval(self, from_ms: str, to_ms: str, max_dp: int = 300) -> int:
        """조회 범위에 따라 intervalMs 자동 계산 (최솟값 15초)"""
        duration_ms = int(to_ms) - int(from_ms)
        return max(duration_ms // max_dp, 15000)

    # ── 공통 쿼리 빌더 ───────────────────────────────────
    def _build_query(
        self,
        expr:        str,
        ref_id:      str = "A",
        legend:      str = "{{instance}}",
        interval_ms: int = 300000,
        max_dp:      int = 300
    ) -> dict:
        return {
            "datasource":    {"type": "prometheus", "uid": self.ds_uid},
            "expr":          expr,
            "refId":         ref_id,
            "legendFormat":  legend,
            "range":         True,
            "intervalMs":    interval_ms,
            "maxDataPoints": max_dp,
            "datasourceId":  self.ds_id,
            "utcOffsetSec":  32400,
            "scopes":        [],
            "adhocFilters":  [],
            "interval":      ""
        }

    def _call(self, queries: list, from_ms: str, to_ms: str) -> dict:
        """실제 API 호출. requestId / ds_type 은 불필요 — URL에 포함하지 않음"""
        payload = {"queries": queries, "from": from_ms, "to": to_ms}
        resp = requests.post(
            self.url, headers=self.headers,
            json=payload, verify=False, timeout=30
        )
        resp.raise_for_status()
        return resp.json()

    # ── 응답 파싱 ────────────────────────────────────────
    def _parse_frames(self, raw: dict, ref_id: str = "A", scale: float = 1.0) -> list:
        """
        응답에서 핵심 3개 필드만 추출:
          labels     = frames[N].schema.fields[1].labels  → 누구의 데이터인지
          values[0]  = frames[N].data.values[0]           → 타임스탬프 배열 (Unix ms)
          values[1]  = frames[N].data.values[1]           → 측정값 배열

        반환: [{"name", "labels", "timestamps", "values", "latest", "avg", "max"}, ...]
        """
        result = []
        frames = raw.get("results", {}).get(ref_id, {}).get("frames", [])

        for frame in frames:
            labels = frame["schema"]["fields"][1].get("labels", {})
            name   = labels.get("groupname") or labels.get("instance", "unknown")
            ts     = frame["data"]["values"][0]
            vals   = [v * scale for v in frame["data"]["values"][1] if v is not None]

            if not vals:
                continue

            result.append({
                "name":       name,
                "labels":     labels,
                "timestamps": ts,
                "values":     vals,
                "latest":     round(vals[-1], 4),
                "avg":        round(sum(vals) / len(vals), 4),
                "max":        round(max(vals), 4),
                "min":        round(min(vals), 4),
            })

        return result

    # ── CHECK-01: CPU 사용률 ─────────────────────────────
    def get_cpu(self, instance: str, from_ms: str, to_ms: str) -> list:
        """
        반환값 단위: % (이미 ×100 적용됨)
        """
        interval_ms = self.auto_interval(from_ms, to_ms)
        expr = (
            f"(sum by(instance)(irate(node_cpu_seconds_total"
            f"{{instance=~\"{instance}\",mode!=\"idle\"}}[5m]))"
            f" / on(instance) group_left"
            f" sum by(instance)(irate(node_cpu_seconds_total"
            f"{{instance=~\"{instance}\"}}[5m]))) * 100"
        )
        q   = self._build_query(expr, legend="{{instance}} CPU%",
                                interval_ms=interval_ms)
        raw = self._call([q], from_ms, to_ms)
        return self._parse_frames(raw, "A", scale=1.0)

    # ── CHECK-02: 메모리 사용률 ──────────────────────────
    def get_memory(self, instance: str, from_ms: str, to_ms: str) -> list:
        """
        반환값 단위: % (소수값 ×100 변환 적용)
        """
        interval_ms = self.auto_interval(from_ms, to_ms)
        expr = (
            f"(1 - (node_memory_MemFree_bytes{{instance=~\"{instance}\"}}"
            f" + node_memory_Cached_bytes + node_memory_Buffers_bytes)"
            f" / node_memory_MemTotal_bytes)"
        )
        q   = self._build_query(expr, legend="{{instance}} MEM%",
                                interval_ms=interval_ms)
        raw = self._call([q], from_ms, to_ms)
        return self._parse_frames(raw, "A", scale=100.0)  # 소수 → %

    # ── CHECK-03: 네트워크 Rx/Tx ─────────────────────────
    def get_network(self, instance: str, from_ms: str, to_ms: str) -> dict:
        """
        반환값 단위: Mbps (bps ÷ 1e6 변환 적용)
        반환: {"rx": [...], "tx": [...]}
        """
        interval_ms = self.auto_interval(from_ms, to_ms)
        devices = "ens192|ens224"
        qA = self._build_query(
            f"sum by(instance)(irate(node_network_receive_bytes_total"
            f"{{instance=~\"{instance}\",device=~\"({devices})\",device!~\"^lo\"}}[5m])*8)",
            ref_id="A", legend="{{instance}} - Rx", interval_ms=interval_ms
        )
        qB = self._build_query(
            f"sum by(instance)(irate(node_network_transmit_bytes_total"
            f"{{instance=~\"{instance}\",device=~\"({devices})\",device!~\"^lo\"}}[5m])*8)",
            ref_id="B", legend="{{instance}} - Tx", interval_ms=interval_ms
        )
        raw = self._call([qA, qB], from_ms, to_ms)
        return {
            "rx": self._parse_frames(raw, "A", scale=1e-6),   # bps → Mbps
            "tx": self._parse_frames(raw, "B", scale=1e-6),
        }

    # ── CHECK-04: 디스크 I/O ─────────────────────────────
    def get_disk(self, instance: str, from_ms: str, to_ms: str) -> dict:
        """
        반환값 단위: MB/s (bytes/s ÷ 1e6 변환 적용)
        반환: {"read": [...], "write": [...]}
        """
        interval_ms = self.auto_interval(from_ms, to_ms)
        devices = "sda|sdb|sdc|sdd|sde|sdf"
        qA = self._build_query(
            f"sum by(instance)(irate(node_disk_read_bytes_total"
            f"{{instance=~\"{instance}\",device=~\"({devices})\"}}[5m]))",
            ref_id="A", legend="{{instance}} - Read", interval_ms=interval_ms
        )
        qB = self._build_query(
            f"sum by(instance)(irate(node_disk_written_bytes_total"
            f"{{instance=~\"{instance}\",device=~\"({devices})\"}}[5m]))",
            ref_id="B", legend="{{instance}} - Write", interval_ms=interval_ms
        )
        raw = self._call([qA, qB], from_ms, to_ms)
        return {
            "read":  self._parse_frames(raw, "A", scale=1e-6),
            "write": self._parse_frames(raw, "B", scale=1e-6),
        }

    # ── CHECK-05: 프로세스 수 ────────────────────────────
    def get_process_count(self, instance: str, from_ms: str, to_ms: str) -> list:
        """
        반환값 단위: 정수 (프로세스 수)
        """
        q = self._build_query(
            f"namedprocess_namegroup_num_procs{{instance=~\"{instance}\"}}",
            legend="{{groupname}} - {{instance}}",
            interval_ms=15000, max_dp=1
        )
        raw = self._call([q], from_ms, to_ms)
        return self._parse_frames(raw, "A", scale=1.0)

    # ── CHECK-06: 프로세스별 CPU ─────────────────────────
    def get_process_cpu(self, instance: str, from_ms: str, to_ms: str) -> list:
        """
        반환값 단위: % (소수 ×100 변환 적용)
        """
        interval_ms = self.auto_interval(from_ms, to_ms)
        expr = (
            f"sum by(instance, groupname)"
            f"(rate(namedprocess_namegroup_cpu_seconds_total"
            f"{{instance=~\"{instance}\"}}[2m]))"
            f" / on(instance) group_left"
            f" sum by(instance)(rate(node_cpu_seconds_total"
            f"{{instance=~\"{instance}\"}}[2m]))"
        )
        q   = self._build_query(expr, legend="{{groupname}} [{{instance}}]",
                                interval_ms=interval_ms)
        raw = self._call([q], from_ms, to_ms)
        return self._parse_frames(raw, "A", scale=100.0)

    # ── CHECK-07: 프로세스별 메모리 ─────────────────────
    def get_process_memory(self, instance: str, from_ms: str, to_ms: str) -> list:
        """
        반환값 단위: % (소수 ×100 변환 적용)
        """
        interval_ms = self.auto_interval(from_ms, to_ms)
        expr = (
            f"sum(namedprocess_namegroup_memory_bytes"
            f"{{instance=~\"{instance}\",memtype=\"resident\"}})"
            f" by(instance, groupname)"
            f" / on(instance) group_left"
            f" sum(node_memory_MemTotal_bytes{{instance=~\"{instance}\"}}) by(instance)"
        )
        q   = self._build_query(expr, legend="{{groupname}} [{{instance}}]",
                                interval_ms=interval_ms)
        raw = self._call([q], from_ms, to_ms)
        return self._parse_frames(raw, "A", scale=100.0)
```

---

## 5. preprocessor.py 설계

### 5.1 역할

- grafana_client가 반환한 파싱 데이터를 받아 **통계 집계 + 이상 감지**
- LLM에 넣을 **압축 요약 텍스트** 생성 (~1,500토큰 이내)
- raw JSON을 LLM에 직접 넣지 않는 이유: 28,000토큰 오버플로우 발생 (실측)

### 5.2 이상 감지 임계값

```python
THRESHOLDS = {
    "cpu":           {"warn": 80.0,  "critical": 95.0},   # %
    "memory":        {"warn": 85.0,  "critical": 95.0},   # %
    "network_rx":    {"warn": 150.0, "critical": 200.0},  # Mbps
    "disk_read":     {"warn": 10.0,  "critical": 50.0},   # MB/s
    "proc_cpu":      {"warn": 0.5,   "critical": 0.8},    # % (ds_agent 기준)
    "proc_memory":   {"warn": 1.0,   "critical": 2.0},    # %
}

# 프로세스 수 기대값 (SQR325 실측 기준)
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
```

### 5.3 전체 코드

```python
# src/preprocessor.py

from datetime import datetime


THRESHOLDS = {
    "cpu":         {"warn": 80.0,  "critical": 95.0},
    "memory":      {"warn": 85.0,  "critical": 95.0},
    "network_rx":  {"warn": 150.0, "critical": 200.0},
    "disk_read":   {"warn": 10.0,  "critical": 50.0},
    "proc_cpu":    {"warn": 0.5,   "critical": 0.8},
    "proc_memory": {"warn": 1.0,   "critical": 2.0},
}

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


class Preprocessor:

    def summarize(self, collected: dict) -> str:
        """
        grafana_client에서 수집한 전체 데이터를 압축 요약 텍스트로 변환.
        LLM 입력용 — 목표 1,500토큰 이내.

        collected = {
            "instance": "prautap1|prautdb1",
            "time_range": "2025-05-09 00:00 ~ 09:00",
            "cpu":     [...],   # get_cpu() 반환값
            "memory":  [...],   # get_memory() 반환값
            "network": {"rx": [...], "tx": [...]},
            "disk":    {"read": [...], "write": [...]},
            "process": [...],   # get_process_count() 반환값
            "proc_cpu": [...],  # get_process_cpu() 반환값
        }
        """
        lines = []
        lines.append(f"[점검 시각] {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        lines.append(f"[점검 대상] {collected.get('instance', '알 수 없음')}")
        lines.append(f"[점검 범위] {collected.get('time_range', '알 수 없음')}")
        lines.append("")

        # CPU
        if "cpu" in collected:
            lines.append("## CPU 사용률")
            for item in collected["cpu"]:
                status = self._status("cpu", item["max"])
                lines.append(
                    f"  {item['name']}: 평균={item['avg']:.1f}%, "
                    f"최대={item['max']:.1f}%, 현재={item['latest']:.1f}%"
                    f"  [{status}]"
                )
            lines.append("")

        # 메모리
        if "memory" in collected:
            lines.append("## 메모리 사용률")
            for item in collected["memory"]:
                status = self._status("memory", item["latest"])
                lines.append(
                    f"  {item['name']}: 평균={item['avg']:.1f}%, "
                    f"최대={item['max']:.1f}%, 현재={item['latest']:.1f}%"
                    f"  [{status}]"
                )
            lines.append("")

        # 네트워크
        if "network" in collected:
            lines.append("## 네트워크 (이더넷 Rx/Tx, Mbps)")
            for item in collected["network"].get("rx", []):
                status = self._status("network_rx", item["max"])
                lines.append(
                    f"  {item['name']} Rx: 평균={item['avg']:.1f}, "
                    f"최대={item['max']:.1f}  [{status}]"
                )
            for item in collected["network"].get("tx", []):
                lines.append(
                    f"  {item['name']} Tx: 평균={item['avg']:.1f}, "
                    f"최대={item['max']:.1f}"
                )
            lines.append("")

        # 디스크
        if "disk" in collected:
            lines.append("## 디스크 I/O (MB/s)")
            for item in collected["disk"].get("read", []):
                status = self._status("disk_read", item["max"])
                lines.append(
                    f"  {item['name']} Read: 평균={item['avg']:.2f}, "
                    f"최대={item['max']:.2f}  [{status}]"
                )
            for item in collected["disk"].get("write", []):
                lines.append(
                    f"  {item['name']} Write: 평균={item['avg']:.2f}, "
                    f"최대={item['max']:.2f}"
                )
            lines.append("")

        # 프로세스 수 이상 감지
        if "process" in collected:
            lines.append("## 프로세스 수 이상 감지")
            anomalies = self._check_process_baseline(collected["process"])
            if anomalies:
                for a in anomalies:
                    lines.append(f"  ⚠ {a}")
            else:
                lines.append("  정상 (모든 프로세스 기대값 일치)")
            lines.append("")

        # 프로세스별 CPU 상위
        if "proc_cpu" in collected:
            lines.append("## 프로세스별 CPU 점유율 (상위 5개)")
            top5 = sorted(collected["proc_cpu"],
                          key=lambda x: x["max"], reverse=True)[:5]
            for item in top5:
                status = self._status("proc_cpu", item["max"])
                lines.append(
                    f"  {item['name']}: 평균={item['avg']:.3f}%, "
                    f"최대={item['max']:.3f}%  [{status}]"
                )
            lines.append("")

        # 이상 요약 (LLM이 집중해야 할 항목)
        alerts = self._collect_alerts(collected)
        lines.append("## 이상 항목 요약")
        if alerts:
            for alert in alerts:
                lines.append(f"  {alert}")
        else:
            lines.append("  이상 항목 없음 — 전 구간 정상")

        return "\n".join(lines)

    def _status(self, metric: str, value: float) -> str:
        th = THRESHOLDS.get(metric, {})
        if value >= th.get("critical", float("inf")):
            return "🔴 CRITICAL"
        elif value >= th.get("warn", float("inf")):
            return "🟡 WARN"
        return "🟢 OK"

    def _check_process_baseline(self, process_data: list) -> list:
        """프로세스 수가 기대값과 다른 항목 반환"""
        anomalies = []
        for item in process_data:
            inst = item["labels"].get("instance", "")
            grp  = item["labels"].get("groupname", "")
            actual = int(item["latest"])
            baseline = PROCESS_BASELINE.get(inst, {})
            if grp in baseline and actual != baseline[grp]:
                expected = baseline[grp]
                flag = "🔴" if actual == 0 else "🟡"
                anomalies.append(
                    f"{flag} {inst} - {grp}: "
                    f"기대={expected}, 실제={actual}"
                )
        return anomalies

    def _collect_alerts(self, collected: dict) -> list:
        """전체 항목에서 WARN 이상인 항목만 추출"""
        alerts = []

        for item in collected.get("cpu", []):
            if item["max"] >= THRESHOLDS["cpu"]["warn"]:
                alerts.append(
                    f"🟡 CPU: {item['name']} 최대 {item['max']:.1f}%"
                )

        for item in collected.get("memory", []):
            if item["latest"] >= THRESHOLDS["memory"]["warn"]:
                alerts.append(
                    f"🟡 메모리: {item['name']} 현재 {item['latest']:.1f}%"
                )

        for item in collected.get("network", {}).get("rx", []):
            if item["max"] >= THRESHOLDS["network_rx"]["warn"]:
                alerts.append(
                    f"🟡 네트워크 Rx: {item['name']} 최대 {item['max']:.1f} Mbps"
                )

        for item in collected.get("proc_cpu", []):
            if item["max"] >= THRESHOLDS["proc_cpu"]["warn"]:
                alerts.append(
                    f"🟡 프로세스CPU: {item['name']} 최대 {item['max']:.3f}%"
                )

        # 프로세스 수 이상
        proc_anomalies = self._check_process_baseline(
            collected.get("process", [])
        )
        alerts.extend(proc_anomalies)

        return alerts
```

---

## 6. 프로젝트 구조

```
grafana-ai-agent/
├── main.py                  ← 대화 루프 진입점
├── config.yaml              ← API 토큰, URL, 모델명 등 설정 (하드코딩 금지)
│
├── src/
│   ├── agent.py             ← Agent 클래스 (의도 분류 + 맥락 유지)
│   ├── grafana_client.py    ← Grafana API 호출 + 파싱
│   ├── preprocessor.py      ← 통계 집계 + 이상 감지 + LLM용 요약 생성
│   ├── ollama_client.py     ← Ollama API 호출 + 프롬프트 조합
│   └── reporter.py          ← Markdown 파일 저장
│
├── logs/                    ← 실행 로그
└── reports/                 ← 저장된 점검 리포트
    └── report_20250509.md
```

---

## 7. config.yaml 설계

```yaml
# config.yaml — 소스코드에 절대 하드코딩 금지

grafana:
  url:    "https://grafana.shinhancard.com:3000/api/ds/query"
  token:  "glsa_cpeM80mba6oAaeh1TRZdfQ8BcnC69L4F_b2d9b460"
  ds_uid: "aenzqagld59fke"
  ds_id:  157

ollama:
  url:    "http://localhost:11434/api/generate"
  model:  "qwen3:8b"          # 최소 4B 이상 권장 (0.6B 실측 실패)
  timeout: 120

agent:
  default_env:  "pr"          # 기본 환경: 운영
  default_app:  "aut"         # 기본 업무코드: 승인
  default_time: "today"       # 기본 시간 범위

log:
  level: "INFO"               # DEBUG / INFO / WARNING
  file:  "logs/agent.log"
```

---

## 8. 실행 흐름 예시

### 시나리오 1 — 일일점검

```
질문 > 일일점검

[수집 중] 운영 승인 서버 전체 (praut(ap|db)[0-9]+) / 오늘 00:00 ~ 현재
  ✓ CPU 수집 완료
  ✓ 메모리 수집 완료
  ✓ 네트워크 수집 완료
  ✓ 디스크 수집 완료
  ✓ 프로세스 수집 완료

[분석 중] Ollama(qwen3:8b) 분석 요청...

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
 2025-05-09 09:00 일일점검 결과
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
🟢 CPU      prautap1  평균 24.1% / 최대 38.2%
🟢 CPU      prautdb1  평균 37.3% / 최대 52.1%
🟢 메모리   prautap1  현재 14.9%
🟡 메모리   prautdb1  현재 86.2%  ← WARN

[LLM 분석]
DB서버(prautdb1) 메모리가 86.2%로 경고 임계값(85%)을 초과했습니다.
현재 즉각적인 위험 수준은 아니나, 추가 상승 시 OOM 위험이 있습니다.
권장 조치: DB 세션 수 및 SGA/PGA 설정 확인, 불필요한 프로세스 정리를 권장합니다.

리포트를 저장하시겠습니까? (저장/아니요)
```

### 시나리오 2 — 단순 질의

```
질문 > AP서버 CPU 지금 어때?

[수집 중] prautap[0-9]+ / 최근 5분
  ✓ CPU 수집 완료

━━━━━━━━━━━━━━━━━━━━━━━━
 CPU 현황 (최근 5분)
━━━━━━━━━━━━━━━━━━━━━━━━
🟢 prautap1  현재 23.4%  (5분 평균 22.8%)
🟢 prautap2  현재 25.1%  (5분 평균 24.3%)

정상 범위입니다.
```

### 시나리오 3 — 연속 질의

```
질문 > AP 1번 메모리 상세하게 봐줘

[수집 중] prautap1 / 오늘 전체
  ✓ 메모리, 프로세스별 메모리 수집 완료

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
 prautap1 메모리 상세 (오늘)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
서버 전체:  평균 14.85%  최대 15.46%  현재 14.62%

프로세스별 점유 상위:
  ds_agent         평균 0.72%  최대 0.99%  🟡 WARN (심야 배치 감지)
  Control-M Agent  평균 0.05%
  Symagent         평균 0.03%

[LLM 분석]
ds_agent의 메모리 점유가 심야 시간대에 0.99%까지 상승했습니다.
평상시(0.72%) 대비 약 38% 증가한 수치로, 심야 배치 작업 실행과 일치합니다.
현재 상태는 정상 운영 범위 내이나 지속 모니터링을 권장합니다.

질문 > 리포트 저장

✓ 저장 완료: reports/report_prautap1_20250509_090512.md
```

---

## 부록. LLM 프롬프트 구조 (ollama_client.py 참고용)

```python
# src/ollama_client.py 에서 사용하는 프롬프트 구조

SYSTEM_PROMPT = """
당신은 금융 IT 인프라 운영 전문가 AI입니다.
Grafana 메트릭 데이터를 분석하고 운영자에게 간결하고 정확한 상태 요약과 조치 권고를 제공합니다.

출력 형식:
1. 상태 요약 (2~3줄)
2. 이상 항목 및 원인 추정 (있을 경우)
3. 권장 조치 (있을 경우)

규칙:
- 수치는 반드시 원문 데이터 기준으로 언급
- 불확실한 내용은 "추정" 또는 "가능성"으로 표현
- LLM 분석은 참고용이며 최종 판단은 운영자가 수행
"""

def build_prompt(summary_text: str) -> str:
    return f"{summary_text}\n\n위 데이터를 분석해주세요."
```

---

*작성 기준: Grafana API 실측 분석(SQR203~SQR328) + MVP 데모 목적*  
*LLM: Ollama 로컬 (사내 LLM 확정 시 ollama_client.py URL/model만 교체)*  
*호스트명 규칙: {{환경(pr/te/dv)}}{{업무코드(aut)}}{{역할(ap/db)}}{{번호(1,2...)}}*