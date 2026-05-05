"""Grafana API client — parameterized query builder for Prometheus datasource."""

import time
import requests


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
              interval_ms: int = 15000, max_dp: int = 300) -> dict:
        """단일 PromQL 쿼리 실행."""
        payload = {
            "queries": [self._build_query(expr, ref_id, interval_ms, max_dp)],
            "from": str(self.from_ms),
            "to": str(self.to_ms),
        }
        return self._post(payload)

    def multi_query(self, queries: list) -> dict:
        """
        복수 쿼리 실행 (네트워크 Rx/Tx 등 multi-refId 패턴).

        queries: [
            {"expr": "...", "ref_id": "A", "interval_ms": 15000, "max_dp": 376},
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
                )
                for q in queries
            ],
            "from": str(self.from_ms),
            "to": str(self.to_ms),
        }
        return self._post(payload)

    def _build_query(self, expr: str, ref_id: str,
                     interval_ms: int, max_dp: int) -> dict:
        return {
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

    def _post(self, payload: dict) -> dict:
        resp = requests.post(
            self.url,
            headers=self.headers,
            json=payload,
            verify=self.verify_ssl,
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json()


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
        f'+node_memory_Cached_bytes+node_memory_Buffers_bytes)'
        f'/node_memory_MemTotal_bytes)'
    )
    return client.query(expr, ref_id="A", interval_ms=15000, max_dp=376)


def get_network_io(client: GrafanaClient) -> dict:
    """API-6 (SQR328): 네트워크 Rx/Tx. 응답 단위: bps → ÷1e6(Mbps) 필요."""
    f = client.instance_filter
    w = client.window
    return client.multi_query([
        {
            "expr": f'sum by(instance)(irate(node_network_receive_bytes_total{{instance=~"{f}",device!~"^lo"}}[{w}])*8)',
            "ref_id": "A", "interval_ms": 15000, "max_dp": 376,
        },
        {
            "expr": f'sum by(instance)(irate(node_network_transmit_bytes_total{{instance=~"{f}",device!~"^lo"}}[{w}])*8)',
            "ref_id": "B", "interval_ms": 15000, "max_dp": 376,
        },
    ])
