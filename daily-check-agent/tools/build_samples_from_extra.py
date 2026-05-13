#!/usr/bin/env python3
"""
extra_* 파일에서 첫 20포인트를 추출해 today/yesterday 샘플 데이터를 교체.

- yesterday/ : extra 파일의 원본 타임스탬프 (2026-05-13 09:00 ~ 10:35 KST)
- today/     : 타임스탬프를 +1일 시프트  (2026-05-14 09:00 ~ 10:35 KST)
- process_count.json 은 extra 파일이 비어 있으므로 기존 파일 유지
"""

import json
import os

SAMPLE_ROOT = os.path.join(os.path.dirname(__file__), "..", "sample_data")
N_POINTS    = 20
DAY_MS      = 86_400_000  # 1일(ms)

# extra 파일명 → 출력 파일명 매핑
FILE_MAP = {
    "extra_cpu_sample_data.json":           "cpu.json",
    "extra_memory_sample_data.json":        "memory.json",
    "extra_network_sample_data.json":       "network.json",
    "extra_disk_sample_data.json":          "disk.json",
    "extra_process_cpu_usage_data.json":    "process_cpu.json",
    "extra_process_memomry_sample_data.json": "process_memory.json",
}


def slim_frame(frame: dict, n: int, ts_offset: int = 0) -> dict:
    """frame에서 첫 n포인트만 추출하고 타임스탬프에 offset 적용."""
    fields = frame.get("schema", {}).get("fields", [])
    labels: dict = {}
    if len(fields) > 1:
        raw = fields[1].get("labels", {})
        if "instance"  in raw: labels["instance"]  = raw["instance"]
        if "groupname" in raw: labels["groupname"] = raw["groupname"]

    values_raw    = frame.get("data", {}).get("values", [[], []])
    timestamps    = [t + ts_offset for t in (values_raw[0] if values_raw else [])[:n]]
    metric_values = (values_raw[1] if len(values_raw) > 1 else [])[:n]

    return {
        "schema": {
            "fields": [{}, {"labels": labels}]
        },
        "data": {
            "values": [timestamps, metric_values]
        },
    }


def slim_response(data: dict, n: int, ts_offset: int = 0) -> dict:
    slim = {"results": {}}
    for ref_id, ref_data in data.get("results", {}).items():
        slim["results"][ref_id] = {
            "frames": [slim_frame(f, n, ts_offset) for f in ref_data.get("frames", [])]
        }
    return slim


def write_json(path: str, obj: dict) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)


def process_all(n: int = N_POINTS) -> None:
    # extra 파일로부터 첫 타임스탬프 확인 (meta 계산용)
    first_ts = last_ts = None

    for extra_name, out_name in FILE_MAP.items():
        src = os.path.join(SAMPLE_ROOT, extra_name)
        if not os.path.exists(src) or os.path.getsize(src) == 0:
            print(f"  SKIP (없음/빈파일): {extra_name}")
            continue

        with open(src, encoding="utf-8") as f:
            data = json.load(f)

        # 첫 번째 프레임의 타임스탬프로 범위 파악
        for ref_data in data.get("results", {}).values():
            for frame in ref_data.get("frames", []):
                ts_arr = frame.get("data", {}).get("values", [[]])[0]
                if ts_arr:
                    if first_ts is None or ts_arr[0] < first_ts:
                        first_ts = ts_arr[0]
                    end_ts = ts_arr[min(n - 1, len(ts_arr) - 1)]
                    if last_ts is None or end_ts > last_ts:
                        last_ts = end_ts
                break
            break

        # yesterday: 원본 타임스탬프
        yd_slim = slim_response(data, n, ts_offset=0)
        write_json(os.path.join(SAMPLE_ROOT, "yesterday", out_name), yd_slim)

        # today: 타임스탬프 +1일
        td_slim = slim_response(data, n, ts_offset=DAY_MS)
        write_json(os.path.join(SAMPLE_ROOT, "today", out_name), td_slim)

        # 통계
        total_frames = sum(
            len(v.get("frames", []))
            for v in yd_slim.get("results", {}).values()
        )
        orig_size = os.path.getsize(src)
        print(f"  {extra_name} ({orig_size:,}B) → {out_name} | frames={total_frames}")

    # _meta.json 갱신
    if first_ts and last_ts:
        _write_meta(first_ts, last_ts, n)


def _ms_to_kst(ms: int) -> str:
    """Unix ms → KST 'HH:MM:SS' 문자열."""
    import datetime
    dt_utc = datetime.datetime.utcfromtimestamp(ms / 1000)
    dt_kst = dt_utc + datetime.timedelta(hours=9)
    return dt_kst.strftime("%H:%M:%S")


def _ms_to_date(ms: int) -> str:
    import datetime
    dt = datetime.datetime.utcfromtimestamp(ms / 1000) + datetime.timedelta(hours=9)
    return dt.strftime("%Y-%m-%d")


def _write_meta(from_ms: int, to_ms: int, n: int) -> None:
    interval_sec = round((to_ms - from_ms) / max(n - 1, 1) / 1000)

    yd_meta = {
        "date":       _ms_to_date(from_ms),
        "time_range": f"{_ms_to_kst(from_ms)} ~ {_ms_to_kst(to_ms)} KST",
        "from_ms":    str(from_ms),
        "to_ms":      str(to_ms),
        "interval_sec": interval_sec,
        "points":     n,
        "note":       "extra 실측 데이터 기반 샘플 (slim_json 처리, 첫 20포인트)",
    }
    write_json(os.path.join(SAMPLE_ROOT, "yesterday", "_meta.json"), yd_meta)

    td_from = from_ms + DAY_MS
    td_to   = to_ms   + DAY_MS
    td_meta = {
        "date":       _ms_to_date(td_from),
        "time_range": f"{_ms_to_kst(td_from)} ~ {_ms_to_kst(td_to)} KST",
        "from_ms":    str(td_from),
        "to_ms":      str(td_to),
        "interval_sec": interval_sec,
        "points":     n,
        "note":       "extra 실측 데이터 기반 샘플 (slim_json 처리, 첫 20포인트 +1일 시프트)",
    }
    write_json(os.path.join(SAMPLE_ROOT, "today", "_meta.json"), td_meta)

    print(f"\n_meta.json 갱신:")
    print(f"  yesterday: {yd_meta['date']} {yd_meta['time_range']}")
    print(f"  today    : {td_meta['date']} {td_meta['time_range']}")


if __name__ == "__main__":
    print(f"extra → sample_data 변환 (첫 {N_POINTS}포인트)")
    process_all()
    print("완료.")
