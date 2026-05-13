#!/usr/bin/env python3
"""
Grafana API 응답 JSON에서 MVP 에이전트가 필요한 키만 추출.

사용법:
    python3 tools/slim_json.py <입력파일.json> [출력파일.json]

    # 단일 파일
    python3 tools/slim_json.py real_data/cpu_real.json sample_data/today/cpu.json

    # 폴더 전체 일괄 처리 (같은 이름으로 출력 폴더에 저장)
    python3 tools/slim_json.py real_data/ sample_data/today/

필요한 키만 남기는 기준 (data_loader.py 파싱 로직 기반):
    results.{refId}.frames[].schema.fields[1].labels.instance
    results.{refId}.frames[].schema.fields[1].labels.groupname  (process 파일만)
    results.{refId}.frames[].data.values[1]                     (수치 배열)

삭제되는 키:
    - frames[].schema.meta / refId / name
    - frames[].schema.fields[*].name/type/typeInfo/config
    - frames[].schema.fields[0] 내용 (위치 자리만 유지)
    - frames[].data.values[0] (타임스탬프 배열)
    - results.{refId}.status / error 등
"""

import json
import os
import sys


def slim_frame(frame: dict) -> dict:
    """frame 하나에서 필요한 키만 추출."""
    fields = frame.get("schema", {}).get("fields", [])

    # fields[1].labels 만 필요 (instance, groupname)
    labels = {}
    if len(fields) > 1:
        labels = fields[1].get("labels", {})
    slim_labels = {}
    if "instance"  in labels: slim_labels["instance"]  = labels["instance"]
    if "groupname" in labels: slim_labels["groupname"] = labels["groupname"]

    # data.values[1] 만 필요 (수치 배열)
    values_raw = frame.get("data", {}).get("values", [[], []])
    metric_values = values_raw[1] if len(values_raw) > 1 else []

    return {
        "schema": {
            "fields": [
                {},   # fields[0]: Time 자리 (내용 불필요, 인덱스 유지용)
                {"labels": slim_labels},
            ]
        },
        "data": {
            "values": [
                [],             # values[0]: 타임스탬프 자리 (읽지 않음)
                metric_values,  # values[1]: 실제 수치
            ]
        },
    }


def slim_response(data: dict) -> dict:
    """응답 JSON 전체 슬림화."""
    slim = {"results": {}}
    for ref_id, ref_data in data.get("results", {}).items():
        slim_frames = [slim_frame(f) for f in ref_data.get("frames", [])]
        slim["results"][ref_id] = {"frames": slim_frames}
    return slim


def process_file(src: str, dst: str):
    with open(src, "r", encoding="utf-8") as f:
        data = json.load(f)

    original_size = os.path.getsize(src)
    slimmed = slim_response(data)

    os.makedirs(os.path.dirname(dst) if os.path.dirname(dst) else ".", exist_ok=True)
    with open(dst, "w", encoding="utf-8") as f:
        json.dump(slimmed, f, ensure_ascii=False, indent=2)

    slimmed_size = os.path.getsize(dst)
    ratio = (1 - slimmed_size / original_size) * 100 if original_size else 0

    # 프레임 수 집계
    total_frames = sum(
        len(v.get("frames", []))
        for v in slimmed.get("results", {}).values()
    )
    print(f"  {os.path.basename(src)}: {original_size:,}B → {slimmed_size:,}B "
          f"({ratio:.0f}% 감소) | frames={total_frames}")


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    src = sys.argv[1]
    dst = sys.argv[2] if len(sys.argv) > 2 else None

    if os.path.isdir(src):
        # 폴더 일괄 처리
        out_dir = dst or src + "_slim"
        os.makedirs(out_dir, exist_ok=True)
        print(f"폴더 처리: {src} → {out_dir}")
        for fname in sorted(os.listdir(src)):
            if fname.endswith(".json"):
                process_file(
                    os.path.join(src, fname),
                    os.path.join(out_dir, fname),
                )
    else:
        # 단일 파일
        out_file = dst or src.replace(".json", "_slim.json")
        print(f"파일 처리: {src} → {out_file}")
        process_file(src, out_file)

    print("완료.")


if __name__ == "__main__":
    main()
