"""프로세스 가용성 감시 기준값 (PROCESS_BASELINE) 및 이상 감지."""

# CHECK-05 기준값 — SQR325 실측 분석 결과 (prautap1 8개 / prautdb1 15개)
PROCESS_BASELINE: dict = {
    "prautap1": {
        "CMS": 1,
        "CloudESM": 1,
        "Control-M Agent": 8,
        "Control-Minder": 5,
        "NTP": 1,
        "Secuguard System Explorer": 1,
        "Symagent": 2,
        "ds_agent": 6,
    },
    "prautdb1": {
        "AUT_mgauge(mxg_obsd)": 1,
        "AUT_mgauge(mxg_rts)": 1,
        "AUT_mgauge(mxg_sndf)": 1,
        "CloudESM": 1,
        "NTP": 1,
        "Netbackup(/usr/openv/netbackup/bin)": 9,
        "Process DB(ora_ckpt_AUTDBP)": 1,
        "Process DB(ora_pmon_AUTDBP)": 1,
        "Process DB(ora_smon_AUTDBP)": 1,
        "Process DB(tnslsnr)": 2,
        "Process SMS(ovcd)": 11,
        "SEOS": 5,
        "SecuMS": 1,
        "Symagent": 2,
        "Trend Micro": 6,
    },
}


def detect_anomalies(process_count: dict) -> list:
    """
    process_count: load_process_count() 반환값
      { "prautap1": { "CMS": [1,1,...], ... }, ... }

    반환:
      [
        { "instance": "prautap1", "groupname": "CMS",
          "expected": 1, "actual": 0, "status": "critical" },
        ...
      ]

    - actual == 0          → status: "critical" (프로세스 소멸)
    - actual != expected   → status: "warn"     (수 불일치)
    - BASELINE에 없는 그룹 → 무시 (미감시 대상)
    """
    alerts = []
    for instance, groups in process_count.items():
        baseline = PROCESS_BASELINE.get(instance, {})
        for groupname, values in groups.items():
            if groupname not in baseline:
                continue
            actual = round(values[-1]) if values else 0
            expected = baseline[groupname]
            if actual != expected:
                alerts.append({
                    "instance":  instance,
                    "groupname": groupname,
                    "expected":  expected,
                    "actual":    actual,
                    "status":    "critical" if actual == 0 else "warn",
                })
    return alerts
