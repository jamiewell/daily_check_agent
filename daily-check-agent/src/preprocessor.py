"""Aggregate raw time-series into per-instance summary metrics."""

from typing import Any
from src.process_baseline import detect_anomalies


def _avg(values: list) -> float:
    return round(sum(values) / len(values), 2) if values else 0.0


def _max(values: list) -> float:
    return round(max(values), 2) if values else 0.0


def _latest(values: list) -> float:
    return round(values[-1], 3) if values else 0.0


def summarize(raw: dict, thresholds: dict) -> dict:
    """
    raw: output of data_loader.load_all()
    thresholds: config.yaml thresholds 섹션 전체

    Returns a summary dict suitable for LLM prompt and reporting.
    """
    servers = {}

    all_instances = (
        set(raw.get("cpu", {}).keys())
        | set(raw.get("memory", {}).keys())
        | set(raw.get("network", {}).keys())
        | set(raw.get("disk", {}).keys())
    )

    for inst in sorted(all_instances):
        cpu_vals = raw.get("cpu", {}).get(inst, [])
        mem_vals = raw.get("memory", {}).get(inst, [])
        net      = raw.get("network", {}).get(inst, {})
        disk     = raw.get("disk",    {}).get(inst, {})
        rx_vals  = net.get("rx_mbps",    [])
        tx_vals  = net.get("tx_mbps",    [])
        dr_vals  = disk.get("read_mbps",  [])
        dw_vals  = disk.get("write_mbps", [])

        cpu_avg    = _avg(cpu_vals)
        cpu_max    = _max(cpu_vals)
        mem_avg    = _avg(mem_vals)
        mem_latest = _latest(mem_vals)
        rx_max     = _max(rx_vals)
        rx_latest  = _latest(rx_vals)
        tx_max     = _max(tx_vals)
        tx_latest  = _latest(tx_vals)
        dr_max     = _max(dr_vals)
        dw_max     = _max(dw_vals)

        alerts = []

        # CPU
        if cpu_max >= thresholds["cpu_critical"]:
            alerts.append(f"CPU 최대값 {cpu_max}% — 위험 임계치({thresholds['cpu_critical']}%) 초과")
        elif cpu_max >= thresholds["cpu_warning"]:
            alerts.append(f"CPU 최대값 {cpu_max}% — 주의 임계치({thresholds['cpu_warning']}%) 초과")

        # 메모리
        if mem_latest >= thresholds["memory_critical"]:
            alerts.append(f"메모리 {mem_latest}% — 위험 임계치({thresholds['memory_critical']}%) 초과")
        elif mem_latest >= thresholds["memory_warning"]:
            alerts.append(f"메모리 {mem_latest}% — 주의 임계치({thresholds['memory_warning']}%) 초과")

        # 네트워크
        if rx_max >= thresholds["network_critical"]:
            alerts.append(f"Rx 최대값 {rx_max} Mbps — 위험 임계치({thresholds['network_critical']} Mbps) 초과")
        elif rx_max >= thresholds["network_warning"]:
            alerts.append(f"Rx 최대값 {rx_max} Mbps — 주의 임계치({thresholds['network_warning']} Mbps) 초과")

        # 디스크 Read
        dr_warn = thresholds.get("disk_read_warning", 10.0)
        dr_crit = thresholds.get("disk_read_critical", 50.0)
        if dr_max >= dr_crit:
            alerts.append(f"디스크 Read 최대값 {dr_max} MB/s — 위험 임계치({dr_crit} MB/s) 초과")
        elif dr_max >= dr_warn:
            alerts.append(f"디스크 Read 최대값 {dr_max} MB/s — 주의 임계치({dr_warn} MB/s) 초과")

        servers[inst] = {
            "cpu": {
                "avg_pct":    cpu_avg,
                "max_pct":    cpu_max,
                "latest_pct": _latest(cpu_vals),
            },
            "memory": {
                "avg_pct":    mem_avg,
                "latest_pct": mem_latest,
            },
            "network": {
                "rx_max_mbps":    rx_max,
                "rx_latest_mbps": rx_latest,
                "tx_max_mbps":    tx_max,
                "tx_latest_mbps": tx_latest,
            },
            "disk": {
                "read_max_mbps":  dr_max,
                "write_max_mbps": dw_max,
            },
            "alerts": alerts,
            "status": _status(alerts),
        }

    # 프로세스 수 이상 감지 — 인스턴스별이 아닌 전체 단위
    process_anomalies = []
    if raw.get("process_count"):
        process_anomalies = detect_anomalies(raw["process_count"])
        for a in process_anomalies:
            inst = a["instance"]
            if inst in servers:
                msg = (
                    f"프로세스 이상 [{a['groupname']}] "
                    f"기대:{a['expected']} 실제:{a['actual']}"
                )
                servers[inst]["alerts"].append(msg)
                if a["status"] == "critical" and servers[inst]["status"] != "위험":
                    servers[inst]["status"] = "위험"
                elif a["status"] == "warn" and servers[inst]["status"] == "정상":
                    servers[inst]["status"] = "주의"

    # 프로세스 CPU/메모리 상위 소비 프로세스 집계 (경보 없이 정보 제공)
    for inst in sorted(all_instances):
        proc_cpu = raw.get("process_cpu", {}).get(inst, {})
        proc_mem = raw.get("process_memory", {}).get(inst, {})

        if inst in servers:
            servers[inst]["process_cpu_top"] = _top_procs(proc_cpu, thresholds.get("process_cpu_critical", 0.8))
            servers[inst]["process_mem_top"] = _top_procs(proc_mem, thresholds.get("process_mem_critical", 2.0))

    return {
        "servers":          servers,
        "process_anomalies": process_anomalies,
        "total_alerts":     sum(len(v["alerts"]) for v in servers.values()),
    }


def _top_procs(proc_dict: dict, critical_pct: float, top_n: int = 5) -> list:
    """프로세스 dict에서 최신값 기준 상위 N개 + 임계 초과 여부 반환."""
    items = []
    for grp, values in proc_dict.items():
        latest = _latest(values)
        items.append({"groupname": grp, "latest_pct": latest,
                      "critical": latest >= critical_pct})
    return sorted(items, key=lambda x: x["latest_pct"], reverse=True)[:top_n]


def _status(alerts: list) -> str:
    if not alerts:
        return "정상"
    for a in alerts:
        if "위험" in a:
            return "위험"
    return "주의"
