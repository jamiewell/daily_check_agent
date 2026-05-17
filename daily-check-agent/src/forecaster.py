"""시계열 사용률 예측 — baseline + slope(A/B/C) 분석."""

import statistics
from dataclasses import dataclass, field


# ---------------------------------------------------------------------------
# 메트릭 설정 (label, unit, 데이터 추출 함수, 임계치 키)
# ---------------------------------------------------------------------------

METRIC_CONFIG = {
    "cpu": {
        "label": "CPU",
        "unit":  "%",
        "get_history": lambda srv: srv.get("cpu_pct", []),
        "get_today":   lambda raw, srv: raw.get("cpu", {}).get(srv, []),
        "warn_key": "cpu_warning",
        "crit_key": "cpu_critical",
    },
    "memory": {
        "label": "Memory",
        "unit":  "%",
        "get_history": lambda srv: srv.get("mem_pct", []),
        "get_today":   lambda raw, srv: raw.get("memory", {}).get(srv, []),
        "warn_key": "memory_warning",
        "crit_key": "memory_critical",
    },
    "rx": {
        "label": "Net Rx",
        "unit":  "Mbps",
        "get_history": lambda srv: srv.get("rx_mbps", []),
        "get_today":   lambda raw, srv: raw.get("network", {}).get(srv, {}).get("rx_mbps", []),
        "warn_key": "network_warning",
        "crit_key": "network_critical",
    },
    "tx": {
        "label": "Net Tx",
        "unit":  "Mbps",
        "get_history": lambda srv: srv.get("tx_mbps", []),
        "get_today":   lambda raw, srv: raw.get("network", {}).get(srv, {}).get("tx_mbps", []),
        "warn_key": "network_warning",
        "crit_key": "network_critical",
    },
    "disk_read": {
        "label": "Disk R",
        "unit":  "MB/s",
        "get_history": lambda srv: srv.get("disk_read_mbps", []),
        "get_today":   lambda raw, srv: raw.get("disk", {}).get(srv, {}).get("read_mbps", []),
        "warn_key": "disk_read_warning",
        "crit_key": "disk_read_critical",
    },
    "disk_write": {
        "label": "Disk W",
        "unit":  "MB/s",
        "get_history": lambda srv: srv.get("disk_write_mbps", []),
        "get_today":   lambda raw, srv: raw.get("disk", {}).get(srv, {}).get("write_mbps", []),
        "warn_key": "disk_read_warning",
        "crit_key": "disk_read_critical",
    },
}

METRIC_FILTER_MAP = {
    "all":     list(METRIC_CONFIG.keys()),
    "cpu":     ["cpu"],
    "memory":  ["memory"],
    "network": ["rx", "tx"],
    "disk":    ["disk_read", "disk_write"],
}


# ---------------------------------------------------------------------------
# 데이터 클래스
# ---------------------------------------------------------------------------

@dataclass
class SlopeInfo:
    slope: float      # 시간당 변화량 (단위는 메트릭에 따라 다름)
    direction: str    # "우상향" | "우하향" | "횡보"
    r2: float         # 결정계수 0~1 (신뢰도, 0.3 미만 = 불규칙)

    @property
    def icon(self) -> str:
        return {"우상향": "↑", "우하향": "↓", "횡보": "→"}.get(self.direction, "?")


@dataclass
class MetricForecast:
    metric: str
    server: str
    unit: str
    baseline: float               # 전일 24h 평균 (기준선)
    current_value: float          # 현재 측정값
    slope_a: SlopeInfo            # 오늘 T 직전 — 현재 진입 추세
    slope_b: SlopeInfo            # 어제 T 직전 — 과거 동일 진입 추세
    slope_c: dict                 # {h: SlopeInfo} 어제 T~T+h — 과거 이후 패턴
    predicted: dict               # {h: float} 예측값
    risk: dict                    # {h: "정상"|"주의"|"위험"}
    threshold_reach_h: float | None  # 주의 임계치 도달 예상 시간 (없으면 None)


# ---------------------------------------------------------------------------
# 핵심 수학 함수
# ---------------------------------------------------------------------------

def linear_regression(values: list) -> tuple:
    """최소제곱법 선형회귀 (외부 라이브러리 없음).

    반환: (slope, intercept, r2)
    slope 단위 = "값 변화 / 인덱스 1 증가분"
    """
    n = len(values)
    if n < 2:
        return 0.0, (values[0] if values else 0.0), 0.0

    xs = list(range(n))
    mean_x = n / 2 - 0.5           # sum(0..n-1)/n
    mean_y = statistics.mean(values)

    ss_xy = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, values))
    ss_xx = sum((x - mean_x) ** 2 for x in xs)

    if ss_xx == 0:
        return 0.0, mean_y, 0.0

    slope     = ss_xy / ss_xx
    intercept = mean_y - slope * mean_x

    ss_tot = sum((y - mean_y) ** 2 for y in values)
    if ss_tot == 0:
        r2 = 1.0
    else:
        ss_res = sum((y - (slope * x + intercept)) ** 2 for x, y in zip(xs, values))
        r2 = max(0.0, 1.0 - ss_res / ss_tot)

    return round(slope, 5), round(intercept, 4), round(r2, 3)


def classify_slope(slope: float, baseline: float) -> str:
    """slope 방향 판단. 기준선의 0.5%/h 미만이면 횡보."""
    threshold = abs(baseline) * 0.005 if baseline else 0.01
    if slope > threshold:
        return "우상향"
    if slope < -threshold:
        return "우하향"
    return "횡보"


def _risk(value: float, warn: float, crit: float) -> str:
    if value >= crit:
        return "위험"
    if value >= warn:
        return "주의"
    return "정상"


# ---------------------------------------------------------------------------
# 예측 함수
# ---------------------------------------------------------------------------

def forecast_metric(
    history_24h: list,
    today_window: list,
    predict_hour: int,
    horizon_hours: list,
    warn_threshold: float,
    crit_threshold: float,
    metric: str = "",
    server: str = "",
    unit: str = "",
) -> MetricForecast:
    """단일 메트릭 시계열 예측.

    history_24h  : 전일 00~23시 1h 단위 값 (24개)
    today_window : 오늘 현시점 직전 N포인트 (5분 간격)
    predict_hour : 현재 시각 (0-23)
    horizon_hours: 예측 구간 리스트 예) [1, 3, 6]
    """
    if not history_24h:
        empty_slope = SlopeInfo(0.0, "횡보", 0.0)
        return MetricForecast(metric, server, unit, 0.0, 0.0,
                              empty_slope, empty_slope, {}, {}, {}, None)

    # 1. 기준선 (baseline)
    baseline      = round(statistics.mean(history_24h), 3)
    current_value = round(today_window[-1], 3) if today_window else (
        history_24h[min(predict_hour, 23)] if predict_hour < 24 else baseline
    )

    # 2. slope_a — 오늘 T 직전 (5분 단위 → ×12 로 시간당 환산)
    if len(today_window) >= 2:
        raw_a, _, r2_a = linear_regression(today_window)
        slope_a_val = round(raw_a * 12, 5)   # 5분 → 1h
    else:
        slope_a_val, r2_a = 0.0, 0.0
    slope_a = SlopeInfo(slope_a_val, classify_slope(slope_a_val, baseline), r2_a)

    # 3. slope_b — 어제 T 직전 3h
    b_end   = max(1, min(predict_hour, 24))
    b_start = max(0, b_end - 3)
    hist_b  = history_24h[b_start:b_end]
    if len(hist_b) >= 2:
        sb, _, r2_b = linear_regression(hist_b)
    else:
        sb, r2_b = 0.0, 0.0
    slope_b = SlopeInfo(round(sb, 5), classify_slope(sb, baseline), r2_b)

    # 4. slope_c per horizon — 어제 T ~ T+h
    slope_c: dict = {}
    predicted: dict = {}
    risk: dict = {}
    threshold_reach_h: float | None = None

    for h in sorted(horizon_hours):
        c_start = min(predict_hour, 23)
        c_end   = min(24, predict_hour + h)
        hist_c  = history_24h[c_start:c_end]

        if len(hist_c) >= 2:
            sc, _, r2_c = linear_regression(hist_c)
        else:
            sc, r2_c = 0.0, 0.0

        slope_c[h] = SlopeInfo(round(sc, 5), classify_slope(sc, baseline), r2_c)

        # 예측값 = 현재값 + slope × 시간 (음수 불가)
        pred = round(max(0.0, current_value + sc * h), 2)
        predicted[h] = pred
        risk[h]      = _risk(pred, warn_threshold, crit_threshold)

        # 주의 임계치 도달 예상 시간
        if threshold_reach_h is None and sc > 0 and current_value < warn_threshold:
            t = (warn_threshold - current_value) / sc
            if 0 < t <= h:
                threshold_reach_h = round(t, 1)

    return MetricForecast(
        metric=metric, server=server, unit=unit,
        baseline=baseline, current_value=current_value,
        slope_a=slope_a, slope_b=slope_b, slope_c=slope_c,
        predicted=predicted, risk=risk,
        threshold_reach_h=threshold_reach_h,
    )


def forecast_all(
    forecast_data: dict,
    raw_today: dict,
    predict_hour: int,
    horizon_hours: list,
    thresholds: dict,
    metric_filter: str = "all",
) -> dict:
    """모든 서버·메트릭에 대한 예측 수행.

    반환: {server: {metric_key: MetricForecast}}
    """
    selected = METRIC_FILTER_MAP.get(metric_filter, list(METRIC_CONFIG.keys()))
    results: dict = {}

    for server, srv_data in forecast_data.items():
        results[server] = {}
        for mkey in selected:
            cfg         = METRIC_CONFIG[mkey]
            history_24h = cfg["get_history"](srv_data)
            today_window = cfg["get_today"](raw_today, server)
            if not history_24h:
                continue
            results[server][mkey] = forecast_metric(
                history_24h=history_24h,
                today_window=today_window,
                predict_hour=predict_hour,
                horizon_hours=horizon_hours,
                warn_threshold=thresholds.get(cfg["warn_key"], 80.0),
                crit_threshold=thresholds.get(cfg["crit_key"], 95.0),
                metric=mkey,
                server=server,
                unit=cfg["unit"],
            )

    return results


def forecast_to_text(results: dict, horizon_hours: list) -> str:
    """LLM 전달용 예측 요약 텍스트."""
    lines = ["[사용률 예측 결과]"]
    for server, metrics in results.items():
        lines.append(f"\n{server}:")
        for mkey, fc in metrics.items():
            cfg = METRIC_CONFIG[mkey]
            preds = ", ".join(
                f"{h}h→{fc.predicted.get(h, '?')}{fc.unit}({fc.risk.get(h, '?')})"
                for h in sorted(horizon_hours)
            )
            main_dir = fc.slope_c.get(max(horizon_hours), fc.slope_a).direction
            reach = f" ⚠{fc.threshold_reach_h}h후 주의" if fc.threshold_reach_h else ""
            lines.append(
                f"  {cfg['label']}: 기준선 {fc.baseline}{fc.unit} / "
                f"현재 {fc.current_value}{fc.unit} / {main_dir} / {preds}{reach}"
            )
    return "\n".join(lines)
