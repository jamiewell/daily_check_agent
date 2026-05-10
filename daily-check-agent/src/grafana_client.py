"""Grafana API client — parameterized query builder for Prometheus datasource."""

import time
import requests
from datetime import datetime, date, timedelta

from src import debug_logger as dbg


# ---------------------------------------------------------------------------
# 인스턴스 필터 빌더
# ---------------------------------------------------------------------------

def build_instance_filter(env: str, biz: str, roles: list, numbers: list) -> str:
    """
    Prometheus instance=~"..." 에 사용하는 정규식 문자열을 생성합니다.

    명명 규칙: {env}{biz}{role}{number}
      env  : pr=운영, dv=개발, te=테스트
      biz  : aut 등 업무코드
      role : ap=애플리케이션서버, db=데이터베이스

    예시:
      build_instance_filter("pr", "aut", ["ap"], [1, 2])
      → "(prautap1|prautap2)"

      build_instance_filter("pr", "aut", ["ap", "db"], [1, 2])
      → "(prautap1|prautap2|prautdb1|prautdb2)"
    """
    instances = [
        f"{env}{biz}{role}{n}"
        for role in roles
        for n in numbers
    ]
    return f"({'|'.join(instances)})"


def instance_filter_from_config(cfg: dict) -> str:
    """config.yaml의 grafana.instance 섹션으로 필터 문자열 반환."""
    inst = cfg["grafana"]["instance"]
    return build_instance_filter(
        env=inst["env"],
        biz=inst["biz"],
        roles=inst["roles"],
        numbers=inst["numbers"],
    )


# ---------------------------------------------------------------------------
# 시간 범위 빌더
# ---------------------------------------------------------------------------

def build_time_range(cfg: dict) -> tuple:
    """
    config.yaml의 grafana 섹션으로 (from_ms, to_ms) 튜플 반환.

    우선순위:
      1. from_ms / to_ms 직접 지정 값
      2. range_minutes 기준 현재 시각에서 역산
    """
    g = cfg["grafana"]
    to_ms = int(g["to_ms"]) if g.get("to_ms") else int(time.time() * 1000)
    if g.get("from_ms"):
        from_ms = int(g["from_ms"])
    else:
        from_ms = to_ms - int(g.get("range_minutes", 60)) * 60 * 1000
    return from_ms, to_ms


def time_range(mode: str = "today", **kwargs) -> tuple:
    """
    조회 시간 범위 (from_ms, to_ms) 문자열 튜플 반환.

    mode:
      "realtime"  — 현재 기준 최근 N분        kwargs: minutes=5
      "today"     — 오늘 00:00 ~ 현재
      "yesterday" — 어제 00:00 ~ 23:59
      "date"      — 특정 날짜 전체             kwargs: date="2025-05-01"
      "range"     — 임의 구간                  kwargs: start="2025-05-01 09:00", end="2025-05-01 18:00"
      "hours"     — 현재 기준 최근 N시간       kwargs: hours=6
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


def auto_interval(from_ms: str, to_ms: str, max_dp: int = 300) -> int:
    """조회 범위에 따라 intervalMs 자동 계산. 최솟값 15초(15000ms) 보정."""
    duration_ms = int(to_ms) - int(from_ms)
    return max(duration_ms // max_dp, 15000)


# ---------------------------------------------------------------------------
# 공통 쿼리 실행
# ---------------------------------------------------------------------------

class GrafanaClient:
    def __init__(self, cfg: dict):
        g = cfg["grafana"]
        self.url = g["url"]
        self.headers = {
            "Authorization": f"Bearer {g['token']}",
            "Content-Type": "application/json",
        }
        self.ds_uid = g["ds_uid"]
        self.ds_id = g["ds_id"]
        self.verify_ssl = g.get("verify_ssl", False)

        self.instance_filter = instance_filter_from_config(cfg)
        self.window = g.get("window", "15m")
        self.from_ms, self.to_ms = build_time_range(cfg)

    def query(self, expr: str, ref_id: str = "A",
              interval_ms: int = 15000, max_dp: int = 300,
              legend_format: str = "") -> dict:
        """단일 PromQL 쿼리 실행."""
        payload = {
            "queries": [self._build_query(expr, ref_id, interval_ms, max_dp, legend_format)],
            "from": str(self.from_ms),
            "to": str(self.to_ms),
        }
        return self._post(payload)

    def multi_query(self, queries: list) -> dict:
        """
        복수 쿼리 실행 (네트워크 Rx/Tx 등 multi-refId 패턴).

        queries: [
            {"expr": "...", "ref_id": "A", "interval_ms": 15000, "max_dp": 376, "legend_format": "{{instance}}"},
            {"expr": "...", "ref_id": "B", "interval_ms": 15000, "max_dp": 376},
        ]
        """
        payload = {
            "queries": [
                self._build_query(
                    q["expr"],
                    q.get("ref_id", "A"),
                    q.get("interval_ms", 15000),
                    q.get("max_dp", 300),
                    q.get("legend_format", ""),
                )
                for q in queries
            ],
            "from": str(self.from_ms),
            "to": str(self.to_ms),
        }
        return self._post(payload)

    def _build_query(self, expr: str, ref_id: str,
                     interval_ms: int, max_dp: int,
                     legend_format: str = "") -> dict:
        q = {
            "datasource": {"type": "prometheus", "uid": self.ds_uid},
            "expr": expr,
            "refId": ref_id,
            "range": True,
            "intervalMs": interval_ms,
            "maxDataPoints": max_dp,
            "datasourceId": self.ds_id,
            "utcOffsetSec": 32400,
            "scopes": [],
            "adhocFilters": [],
        }
        if legend_format:
            q["legendFormat"] = legend_format
        return q

    def _post(self, payload: dict) -> dict:
        dbg.log_request("Grafana /api/ds/query", self.url, payload)
        t0 = time.time()
        try:
            resp = requests.post(
                self.url,
                headers=self.headers,
                json=payload,
                verify=self.verify_ssl,
                timeout=30,
            )
            resp.raise_for_status()
            data = resp.json()
            dbg.log_response("Grafana /api/ds/query", resp.status_code, data, time.time() - t0)
            return data
        except Exception as e:
            dbg.log_error("Grafana API 오류", e)
            raise


# ---------------------------------------------------------------------------
# API별 쿼리 함수 (INSTANCE_FILTER, WINDOW 자동 치환)
# ---------------------------------------------------------------------------

def get_cpu_overview(client: GrafanaClient) -> dict:
    """API-1 (SQR292): CPU 사용률 15분 윈도우. 응답 단위: % (변환 불필요)."""
    f = client.instance_filter
    w = client.window
    expr = (
        f'(sum by(instance)(irate(node_cpu_seconds_total{{instance=~"{f}",mode!="idle"}}[{w}]))'
        f'/on(instance) group_left '
        f'sum by(instance)(irate(node_cpu_seconds_total{{instance=~"{f}"}}[{w}])))*100'
    )
    return client.query(expr, ref_id="A", interval_ms=15000, max_dp=120)


def get_memory_usage(client: GrafanaClient) -> dict:
    """API-4 (SQR326): 서버 전체 메모리 사용률. 응답 단위: 소수(0~1) → ×100 필요."""
    f = client.instance_filter
    expr = (
        f'(1-(node_memory_MemFree_bytes{{instance=~"{f}"}}'
        f'+node_memory_Cached_bytes{{instance=~"{f}"}}'
        f'+node_memory_Buffers_bytes{{instance=~"{f}"}})'
        f'/node_memory_MemTotal_bytes{{instance=~"{f}"}})'
    )
    return client.query(expr, ref_id="A", interval_ms=15000, max_dp=376)


def get_network_io(client: GrafanaClient) -> dict:
    """API-6 (SQR328): 네트워크 Rx/Tx. 응답 단위: bps → ÷1e6(Mbps) 필요."""
    f = client.instance_filter
    w = client.window
    devices = "ens192|ens224"
    return client.multi_query([
        {
            "expr": f'sum by(instance)(irate(node_network_receive_bytes_total{{instance=~"{f}",device=~"({devices})",device!~"^lo"}}[{w}])*8)',
            "ref_id": "A", "interval_ms": 15000, "max_dp": 376,
            "legend_format": "{{instance}} - Rx",
        },
        {
            "expr": f'sum by(instance)(irate(node_network_transmit_bytes_total{{instance=~"{f}",device=~"({devices})",device!~"^lo"}}[{w}])*8)',
            "ref_id": "B", "interval_ms": 15000, "max_dp": 376,
            "legend_format": "{{instance}} - Tx",
        },
    ])


def get_disk_io(client: GrafanaClient) -> dict:
    """CHECK-04: 디스크 Read/Write 속도. 응답 단위: bytes/s → ÷1e6 = MB/s."""
    f = client.instance_filter
    w = client.window
    devices = "sda|sdb|sdc|sdd|sde|sdf"
    return client.multi_query([
        {
            "expr": f'sum by(instance)(irate(node_disk_read_bytes_total{{instance=~"{f}",device=~"({devices})"}}[{w}]))',
            "ref_id": "A", "interval_ms": 15000, "max_dp": 300,
            "legend_format": "{{instance}} - Read",
        },
        {
            "expr": f'sum by(instance)(irate(node_disk_written_bytes_total{{instance=~"{f}",device=~"({devices})"}}[{w}]))',
            "ref_id": "B", "interval_ms": 15000, "max_dp": 300,
            "legend_format": "{{instance}} - Write",
        },
    ])


def get_process_count(client: GrafanaClient) -> dict:
    """CHECK-05 (SQR325): 프로세스 수 가용성 감시. 응답 단위: 정수 (변환 불필요)."""
    f = client.instance_filter
    expr = f'namedprocess_namegroup_num_procs{{instance=~"{f}"}}'
    return client.query(expr, ref_id="A", interval_ms=15000, max_dp=1,
                        legend_format="{{groupname}} - {{instance}}")


def get_process_cpu(client: GrafanaClient) -> dict:
    """CHECK-06: 프로세스별 CPU 점유율. 응답 단위: 소수 → ×100 = %."""
    f = client.instance_filter
    expr = (
        f'sum by(instance, groupname)(rate(namedprocess_namegroup_cpu_seconds_total{{instance=~"{f}"}}[2m]))'
        f' / on(instance) group_left'
        f' sum by(instance)(rate(node_cpu_seconds_total{{instance=~"{f}"}}[2m]))'
    )
    return client.query(expr, ref_id="A", interval_ms=15000, max_dp=300,
                        legend_format="{{groupname}} [{{instance}}]")


def get_process_memory(client: GrafanaClient) -> dict:
    """CHECK-07 (SQR327): 프로세스별 메모리 점유율. 응답 단위: 소수 → ×100 = %."""
    f = client.instance_filter
    expr = (
        f'sum(namedprocess_namegroup_memory_bytes{{instance=~"{f}",memtype="resident"}})'
        f' by(instance, groupname)'
        f' / on(instance) group_left'
        f' sum(node_memory_MemTotal_bytes{{instance=~"{f}"}}) by(instance)'
    )
    return client.query(expr, ref_id="A", interval_ms=15000, max_dp=300,
                        legend_format="{{groupname}} [{{instance}}]")
