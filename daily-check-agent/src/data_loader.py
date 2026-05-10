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


def _latest_values(frame: dict) -> tuple[str, str, list]:
    """
    frame 하나에서 (서버명, 그룹명, 수치 시계열) 을 꺼냅니다.

    frame 구조:
      schema.fields[0]  → Time 필드  (타임스탬프 배열, 여기서는 사용 안 함)
      schema.fields[1]  → Value 필드
        .labels.instance  → 서버 식별자   예) "prautap1"
        .labels.groupname → 프로세스명    예) "Process DB(ora_pmon_AUTDBP)"  — API-3 전용
      data.values[0]    → 타임스탬프 배열  예) [1714878600000, ...]
      data.values[1]    → 수치 배열        예) [21.3, 45.7, 91.4, ...]
    """
    fields = frame["schema"]["fields"]
    labels = fields[1].get("labels", {})

    # labels.instance  = 서버명      예) "prautap1"
    instance  = labels.get("instance",  "unknown")
    # labels.groupname = 프로세스 그룹명 (API-3에만 존재, 나머지는 빈 문자열)
    groupname = labels.get("groupname", "")

    # data.values[1] = 수치 시계열 배열 (values[0] 은 타임스탬프라 무시)
    values = frame["data"]["values"][1]

    return instance, groupname, values


def load_cpu(sample_dir: str) -> dict:
    """
    CPU 사용률 파싱 — API-1 (SQR292), refId: A

    응답 단위: % (이미 ×100 적용된 값)  → 변환 없이 그대로 사용
    반환: { "prautap1": [21.3, 45.7, ..., 91.4], "prautdb1": [...] }
    """
    data = _load_json(os.path.join(sample_dir, "cpu.json"))
    result = {}
    for frame in _extract_frames(data, "A"):          # refId "A" 에서 frame 순회
        instance, _, values = _latest_values(frame)
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
        instance, _, values = _latest_values(frame)
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
        instance, _, values = _latest_values(frame)
        if instance not in result:
            result[instance] = {}
        result[instance]["rx_mbps"] = [round(v / 1e6, 3) for v in values]  # bps → Mbps

    # --- Tx (송신) : refId "B" ---
    for frame in _extract_frames(data, "B"):
        instance, _, values = _latest_values(frame)
        if instance not in result:
            result[instance] = {}
        result[instance]["tx_mbps"] = [round(v / 1e6, 3) for v in values]  # bps → Mbps

    return result


def load_disk(sample_dir: str) -> dict:
    """
    디스크 Read/Write 속도 파싱 — CHECK-04

    refId "A" = Read  (bytes/s)
    refId "B" = Write (bytes/s)
    응답 단위: bytes/s → ÷1,000,000 = MB/s

    반환:
      {
        "prautap1": { "read_mbps": [...], "write_mbps": [...] },
        "prautdb1": { "read_mbps": [...], "write_mbps": [...] }
      }
    """
    data = _load_json(os.path.join(sample_dir, "disk.json"))
    result: dict = {}

    for frame in _extract_frames(data, "A"):
        instance, _, values = _latest_values(frame)
        result.setdefault(instance, {})["read_mbps"] = [round(v / 1e6, 3) for v in values]

    for frame in _extract_frames(data, "B"):
        instance, _, values = _latest_values(frame)
        result.setdefault(instance, {})["write_mbps"] = [round(v / 1e6, 3) for v in values]

    return result


def load_process_count(sample_dir: str) -> dict:
    """
    프로세스 수 파싱 — CHECK-05 (SQR325), refId: A

    응답 단위: 정수 (프로세스 수, 변환 불필요)
    레이블 키: labels.instance + labels.groupname (둘 다 필요)

    반환:
      {
        "prautap1": { "CMS": [1,1,...], "ds_agent": [6,6,...] },
        "prautdb1": { "Process DB(ora_pmon_AUTDBP)": [1,1,...], ... }
      }
    """
    data = _load_json(os.path.join(sample_dir, "process_count.json"))
    result: dict = {}

    for frame in _extract_frames(data, "A"):
        instance, groupname, values = _latest_values(frame)   # groupname 사용
        result.setdefault(instance, {})[groupname] = values

    return result


def load_process_cpu(sample_dir: str) -> dict:
    """
    프로세스별 CPU 점유율 파싱 — CHECK-06, refId: A

    응답 단위: 소수 (0~1) → ×100 = %
      예) 0.0024 → 0.24%

    반환:
      {
        "prautap1": { "ds_agent": [0.24, ..., 0.31], ... },
        "prautdb1": { "Trend Micro": [0.18, ...], ... }
      }
    """
    data = _load_json(os.path.join(sample_dir, "process_cpu.json"))
    result: dict = {}

    for frame in _extract_frames(data, "A"):
        instance, groupname, values = _latest_values(frame)
        result.setdefault(instance, {})[groupname] = [round(v * 100, 4) for v in values]

    return result


def load_process_memory(sample_dir: str) -> dict:
    """
    프로세스별 메모리 점유율 파싱 — CHECK-07 (SQR327), refId: A

    응답 단위: 소수 (0~1) → ×100 = %
      예) 0.007 → 0.7%

    반환:
      {
        "prautap1": { "ds_agent": [0.7, ..., 0.8], ... },
        "prautdb1": { "Process DB(ora_pmon_AUTDBP)": [1.2, ...], ... }
      }
    """
    data = _load_json(os.path.join(sample_dir, "process_memory.json"))
    result: dict = {}

    for frame in _extract_frames(data, "A"):
        instance, groupname, values = _latest_values(frame)
        result.setdefault(instance, {})[groupname] = [round(v * 100, 4) for v in values]

    return result


def load_all(sample_dir: str) -> dict:
    """모든 메트릭을 한 번에 로드. 샘플 파일이 없는 항목은 빈 dict로 건너뜁니다."""
    result = {}
    loaders = [
        ("cpu",            load_cpu),
        ("memory",         load_memory),
        ("network",        load_network),
        ("disk",           load_disk),
        ("process_count",  load_process_count),
        ("process_cpu",    load_process_cpu),
        ("process_memory", load_process_memory),
    ]
    for key, fn in loaders:
        try:
            result[key] = fn(sample_dir)
        except FileNotFoundError:
            result[key] = {}
    return result
