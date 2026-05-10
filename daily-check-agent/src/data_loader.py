"""Load and parse Grafana API sample JSON responses."""

import json
import os


def _load_json(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _extract_frames(data: dict, ref_id: str) -> list:
    # 응답 구조: { "results": { "A": { "frames": [...] } } }
    # ref_id ("A" 또는 "B") 로 쿼리 결과를 구분 — 네트워크는 A=Rx, B=Tx
    return data.get("results", {}).get(ref_id, {}).get("frames", [])


def _latest_values(frame: dict) -> tuple[str, list]:
    """
    frame 하나에서 (서버명, 수치 시계열) 을 꺼냅니다.

    frame 구조:
      schema.fields[0]  → Time 필드  (타임스탬프 배열, 여기서는 사용 안 함)
      schema.fields[1]  → Value 필드
        .labels.instance → 서버 식별자  예) "prautap1"
      data.values[0]    → 타임스탬프 배열  예) [1714878600000, ...]
      data.values[1]    → 수치 배열        예) [21.3, 45.7, 91.4, ...]
    """
    fields = frame["schema"]["fields"]

    # fields[1] = Value 필드 / labels.instance = 서버명  예) "prautap1"
    instance = fields[1].get("labels", {}).get("instance", "unknown")

    # data.values[1] = 수치 시계열 배열 (values[0] 은 타임스탬프라 무시)
    values = frame["data"]["values"][1]

    return instance, values


def load_cpu(sample_dir: str) -> dict:
    """
    CPU 사용률 파싱 — API-1 (SQR292), refId: A

    응답 단위: % (이미 ×100 적용된 값)  → 변환 없이 그대로 사용
    반환: { "prautap1": [21.3, 45.7, ..., 91.4], "prautdb1": [...] }
    """
    data = _load_json(os.path.join(sample_dir, "cpu.json"))
    result = {}
    for frame in _extract_frames(data, "A"):          # refId "A" 에서 frame 순회
        instance, values = _latest_values(frame)
        result[instance] = values                      # % 값 그대로 저장
    return result


def load_memory(sample_dir: str) -> dict:
    """
    메모리 사용률 파싱 — API-4 (SQR326), refId: A

    응답 단위: 소수 0~1  → ×100 변환 후 % 로 사용
      예) 0.682  →  68.2%
    반환: { "prautap1": [14.2, ..., 17.5], "prautdb1": [60.1, ..., 68.2] }
    """
    data = _load_json(os.path.join(sample_dir, "memory.json"))
    result = {}
    for frame in _extract_frames(data, "A"):          # refId "A" 에서 frame 순회
        instance, values = _latest_values(frame)
        result[instance] = [round(v * 100, 2) for v in values]   # 소수 → %
    return result


def load_network(sample_dir: str) -> dict:
    """
    네트워크 Rx/Tx 파싱 — API-6 (SQR328), 멀티 refId 패턴

    refId "A" = Rx (수신 bps)
    refId "B" = Tx (송신 bps)
    응답 단위: bps  → ÷1,000,000 변환 후 Mbps 로 사용
      예) 421938471 bps  →  421.938 Mbps

    반환:
      {
        "prautap1": { "rx_mbps": [...], "tx_mbps": [...] },
        "prautdb1": { "rx_mbps": [...], "tx_mbps": [...] }
      }
    """
    data = _load_json(os.path.join(sample_dir, "network.json"))
    result: dict = {}

    # --- Rx (수신) : refId "A" ---
    for frame in _extract_frames(data, "A"):
        instance, values = _latest_values(frame)
        if instance not in result:
            result[instance] = {}
        result[instance]["rx_mbps"] = [round(v / 1e6, 3) for v in values]  # bps → Mbps

    # --- Tx (송신) : refId "B" ---
    for frame in _extract_frames(data, "B"):
        instance, values = _latest_values(frame)
        if instance not in result:
            result[instance] = {}
        result[instance]["tx_mbps"] = [round(v / 1e6, 3) for v in values]  # bps → Mbps

    return result


def load_all(sample_dir: str) -> dict:
    """세 가지 메트릭을 한 번에 로드해 반환."""
    return {
        "cpu":     load_cpu(sample_dir),
        "memory":  load_memory(sample_dir),
        "network": load_network(sample_dir),
    }
