"""Aggregate raw time-series into per-instance summary metrics."""

from typing import Any


def _avg(values: list) -> float:
    return round(sum(values) / len(values), 2) if values else 0.0


def _max(values: list) -> float:
    return round(max(values), 2) if values else 0.0


def _latest(values: list) -> float:
    return round(values[-1], 3) if values else 0.0


def summarize(raw: dict, thresholds: dict) -> dict:
    """
    raw: output of data_loader.load_all()
    thresholds: dict with cpu_warning/critical, memory_warning/critical, network_warning/critical

    Returns a summary dict suitable for LLM prompt and reporting.
    """
    servers = {}

    all_instances = set(raw["cpu"].keys()) | set(raw["memory"].keys()) | set(raw["network"].keys())

    for inst in sorted(all_instances):
        cpu_vals = raw["cpu"].get(inst, [])
        mem_vals = raw["memory"].get(inst, [])
        net = raw["network"].get(inst, {})
        rx_vals = net.get("rx_mbps", [])
        tx_vals = net.get("tx_mbps", [])

        cpu_avg = _avg(cpu_vals)
        cpu_max = _max(cpu_vals)
        mem_avg = _avg(mem_vals)
        mem_latest = _latest(mem_vals)
        rx_max = _max(rx_vals)
        rx_latest = _latest(rx_vals)
        tx_max = _max(tx_vals)
        tx_latest = _latest(tx_vals)

        alerts = []
        if cpu_max >= thresholds["cpu_critical"]:
            alerts.append(f"CPU 최대값 {cpu_max}% — 위험 임계치({thresholds['cpu_critical']}%) 초과")
        elif cpu_max >= thresholds["cpu_warning"]:
            alerts.append(f"CPU 최대값 {cpu_max}% — 주의 임계치({thresholds['cpu_warning']}%) 초과")

        if mem_latest >= thresholds["memory_critical"]:
            alerts.append(f"메모리 {mem_latest}% — 위험 임계치({thresholds['memory_critical']}%) 초과")
        elif mem_latest >= thresholds["memory_warning"]:
            alerts.append(f"메모리 {mem_latest}% — 주의 임계치({thresholds['memory_warning']}%) 초과")

        if rx_max >= thresholds["network_critical"]:
            alerts.append(f"Rx 최대값 {rx_max} Mbps — 위험 임계치({thresholds['network_critical']} Mbps) 초과")
        elif rx_max >= thresholds["network_warning"]:
            alerts.append(f"Rx 최대값 {rx_max} Mbps — 주의 임계치({thresholds['network_warning']} Mbps) 초과")

        servers[inst] = {
            "cpu": {
                "avg_pct": cpu_avg,
                "max_pct": cpu_max,
                "latest_pct": _latest(cpu_vals),
            },
            "memory": {
                "avg_pct": mem_avg,
                "latest_pct": mem_latest,
            },
            "network": {
                "rx_max_mbps": rx_max,
                "rx_latest_mbps": rx_latest,
                "tx_max_mbps": tx_max,
                "tx_latest_mbps": tx_latest,
            },
            "alerts": alerts,
            "status": _status(alerts),
        }

    return {"servers": servers, "total_alerts": sum(len(v["alerts"]) for v in servers.values())}


def _status(alerts: list) -> str:
    if not alerts:
        return "정상"
    for a in alerts:
        if "위험" in a:
            return "위험"
    return "주의"
