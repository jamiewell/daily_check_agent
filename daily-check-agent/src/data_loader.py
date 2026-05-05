"""Load and parse Grafana API sample JSON responses."""

import json
import os
from pathlib import Path


def _load_json(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _extract_frames(data: dict, ref_id: str) -> list:
    return data.get("results", {}).get(ref_id, {}).get("frames", [])


def _latest_values(frame: dict) -> tuple[str, list]:
    """Return (instance_label, list_of_values) from a frame."""
    fields = frame["schema"]["fields"]
    instance = fields[1].get("labels", {}).get("instance", "unknown")
    values = frame["data"]["values"][1]
    return instance, values


def load_cpu(sample_dir: str) -> dict:
    """
    Returns {instance: [values...]} in % (already multiplied, no conversion needed).
    Corresponds to API-1 (SQR292).
    """
    data = _load_json(os.path.join(sample_dir, "cpu.json"))
    result = {}
    for frame in _extract_frames(data, "A"):
        instance, values = _latest_values(frame)
        result[instance] = values
    return result


def load_memory(sample_dir: str) -> dict:
    """
    Returns {instance: [values...]} in % (×100 applied here).
    Corresponds to API-4 (SQR326). Raw values are 0~1 decimals.
    """
    data = _load_json(os.path.join(sample_dir, "memory.json"))
    result = {}
    for frame in _extract_frames(data, "A"):
        instance, values = _latest_values(frame)
        result[instance] = [round(v * 100, 2) for v in values]
    return result


def load_network(sample_dir: str) -> dict:
    """
    Returns {instance: {"rx_mbps": [values...], "tx_mbps": [values...]}} in Mbps (÷1e6 applied).
    Corresponds to API-6 (SQR328). refId A = Rx, refId B = Tx.
    """
    data = _load_json(os.path.join(sample_dir, "network.json"))
    result: dict = {}

    for frame in _extract_frames(data, "A"):
        instance, values = _latest_values(frame)
        if instance not in result:
            result[instance] = {}
        result[instance]["rx_mbps"] = [round(v / 1e6, 3) for v in values]

    for frame in _extract_frames(data, "B"):
        instance, values = _latest_values(frame)
        if instance not in result:
            result[instance] = {}
        result[instance]["tx_mbps"] = [round(v / 1e6, 3) for v in values]

    return result


def load_all(sample_dir: str) -> dict:
    return {
        "cpu": load_cpu(sample_dir),
        "memory": load_memory(sample_dir),
        "network": load_network(sample_dir),
    }
