"""당일 / 전일 summarize 결과를 비교해 delta 및 추세 반환."""


def _delta_entry(today_val: float, yesterday_val: float, unit: str = "") -> dict:
    delta = round(today_val - yesterday_val, 4)
    delta_pct = round(delta / yesterday_val * 100, 1) if yesterday_val else 0.0
    if delta_pct > 10:
        trend = "증가"
    elif delta_pct < -10:
        trend = "감소"
    else:
        trend = "유지"
    return {
        "today":     today_val,
        "yesterday": yesterday_val,
        "delta":     delta,
        "delta_pct": delta_pct,
        "trend":     trend,
        "unit":      unit,
    }


def compare(today: dict, yesterday: dict) -> dict:
    """
    summarize() 결과 두 개를 받아 서버별 지표 비교 dict 반환.

    today, yesterday: preprocessor.summarize() 반환값
      {"servers": {"prautap1": {"cpu": {...}, "memory": {...}, ...}, ...}}

    반환:
      {
        "prautap1": {
          "cpu_avg":        {"today": 53.7, "yesterday": 45.0, "delta": +8.7, "delta_pct": +19.3, "trend": "증가", "unit": "%"},
          "cpu_max":        {...},
          "mem_latest":     {...},
          "rx_max":         {...},
          "disk_read_max":  {...},
          "disk_write_max": {...},
        },
        ...
      }
    """
    result = {}
    today_servers     = today.get("servers", {})
    yesterday_servers = yesterday.get("servers", {})

    for inst in sorted(set(today_servers) | set(yesterday_servers)):
        td = today_servers.get(inst, {})
        yd = yesterday_servers.get(inst, {})

        def t(keys, default=0.0):
            obj = td
            for k in keys:
                obj = obj.get(k, {}) if isinstance(obj, dict) else default
            return obj if isinstance(obj, (int, float)) else default

        def y(keys, default=0.0):
            obj = yd
            for k in keys:
                obj = obj.get(k, {}) if isinstance(obj, dict) else default
            return obj if isinstance(obj, (int, float)) else default

        result[inst] = {
            "cpu_avg":        _delta_entry(t(["cpu", "avg_pct"]),         y(["cpu", "avg_pct"]),         "%"),
            "cpu_max":        _delta_entry(t(["cpu", "max_pct"]),         y(["cpu", "max_pct"]),         "%"),
            "mem_latest":     _delta_entry(t(["memory", "latest_pct"]),   y(["memory", "latest_pct"]),   "%"),
            "rx_max":         _delta_entry(t(["network", "rx_max_mbps"]), y(["network", "rx_max_mbps"]), "Mbps"),
            "disk_read_max":  _delta_entry(t(["disk", "read_max_mbps"]),  y(["disk", "read_max_mbps"]),  "MB/s"),
            "disk_write_max": _delta_entry(t(["disk", "write_max_mbps"]), y(["disk", "write_max_mbps"]), "MB/s"),
        }

    return result


TREND_ICON = {"증가": "↑", "감소": "↓", "유지": "↔"}

METRIC_LABELS = {
    "cpu_avg":        "CPU avg",
    "cpu_max":        "CPU max",
    "mem_latest":     "MEM latest",
    "rx_max":         "Rx max",
    "disk_read_max":  "Disk Read max",
    "disk_write_max": "Disk Write max",
}


def comparison_text(comparison: dict) -> str:
    """LLM 프롬프트에 포함할 전일 비교 텍스트 생성."""
    lines = ["[전일 대비 변화]"]
    for inst, metrics in comparison.items():
        lines.append(f"\n{inst}:")
        for key, d in metrics.items():
            icon  = TREND_ICON[d["trend"]]
            sign  = "+" if d["delta"] >= 0 else ""
            lines.append(
                f"  {METRIC_LABELS[key]}: {d['yesterday']}{d['unit']} → {d['today']}{d['unit']} "
                f"({sign}{d['delta_pct']}%) {icon} {d['trend']}"
            )
    return "\n".join(lines)
