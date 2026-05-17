"""Rich terminal output + Markdown file reporter."""

import os
from datetime import datetime

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich import box

console = Console()


def _status_color(status: str) -> str:
    return {"정상": "green", "주의": "yellow", "위험": "red"}.get(status, "white")


def _load_template(path: str) -> str:
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def print_summary(summary: dict, timestamp: str) -> None:
    console.print(Panel(f"[bold cyan]일일점검 에이전트[/bold cyan]  {timestamp}", expand=False))

    table = Table(box=box.ROUNDED, show_header=True, header_style="bold magenta", expand=False)
    table.add_column("서버", style="cyan", min_width=12)
    table.add_column("상태", justify="center", min_width=6)
    table.add_column("CPU avg/max", justify="right", min_width=16)
    table.add_column("MEM latest", justify="right", min_width=12)
    table.add_column("Rx max(Mbps)", justify="right", min_width=14)
    table.add_column("Tx max(Mbps)", justify="right", min_width=14)
    table.add_column("알림", min_width=30)

    for inst, m in summary["servers"].items():
        color = _status_color(m["status"])
        cpu = m["cpu"]
        mem = m["memory"]
        net = m["network"]
        alerts_text = "\n".join(m["alerts"]) if m["alerts"] else "-"
        table.add_row(
            inst,
            f"[{color}]{m['status']}[/{color}]",
            f"{cpu['avg_pct']}% / {cpu['max_pct']}%",
            f"{mem['latest_pct']}%",
            f"{net['rx_max_mbps']}",
            f"{net['tx_max_mbps']}",
            f"[{color}]{alerts_text}[/{color}]",
        )

    console.print(table)


def print_comparison(comparison: dict) -> None:
    """전일 대비 비교 테이블 출력."""
    from src.comparator import METRIC_LABELS, TREND_ICON

    table = Table(box=box.SIMPLE_HEAD, show_header=True,
                  header_style="bold blue", expand=False,
                  title="[bold blue]전일 대비 비교[/bold blue]")
    table.add_column("지표",    style="dim",  min_width=14)
    table.add_column("서버",    style="cyan", min_width=12)
    table.add_column("전일",    justify="right", min_width=12)
    table.add_column("당일",    justify="right", min_width=12)
    table.add_column("변화(%)", justify="right", min_width=9)
    table.add_column("추세",    justify="center", min_width=6)

    TREND_COLOR = {"증가": "red", "감소": "green", "유지": "white"}

    for inst, metrics in comparison.items():
        for key, d in metrics.items():
            icon  = TREND_ICON[d["trend"]]
            color = TREND_COLOR[d["trend"]]
            sign  = "+" if d["delta_pct"] >= 0 else ""
            table.add_row(
                METRIC_LABELS[key],
                inst,
                f"{d['yesterday']}{d['unit']}",
                f"{d['today']}{d['unit']}",
                f"[{color}]{sign}{d['delta_pct']}%[/{color}]",
                f"[{color}]{icon} {d['trend']}[/{color}]",
            )

    console.print(table)


def print_llm_analysis(analysis: str) -> None:
    console.print(Panel(analysis, title="[bold green]AI 분석 결과[/bold green]", border_style="green"))


def print_forecast(results: dict, horizon_hours: list, predict_hour: int) -> None:
    """사용률 예측 결과를 Rich 테이블로 출력."""
    from src.forecaster import METRIC_CONFIG

    RISK_COLOR = {"정상": "green", "주의": "yellow", "위험": "red"}

    console.print(
        f"\n[bold magenta]사용률 예측[/bold magenta]  "
        f"[dim]기준 시각: {predict_hour:02d}:00 KST | "
        f"예측 구간: {', '.join(str(h)+'h' for h in sorted(horizon_hours))}[/dim]"
    )

    for server, metrics in results.items():
        if not metrics:
            continue

        tbl = Table(
            box=box.ROUNDED,
            title=f"[bold cyan]{server}[/bold cyan]",
            show_header=True,
            header_style="bold blue",
            expand=False,
        )
        tbl.add_column("메트릭",   style="dim",  min_width=10)
        tbl.add_column("기준선",   justify="right", min_width=9)
        tbl.add_column("현재값",   justify="right", min_width=9)
        tbl.add_column("추세A\n(오늘 진입)", justify="center", min_width=10)
        tbl.add_column("추세B\n(전일 진입)", justify="center", min_width=10)
        for h in sorted(horizon_hours):
            tbl.add_column(f"{h}h 예측", justify="right", min_width=9)
        tbl.add_column("임계 도달", justify="center", min_width=11)

        for mkey, fc in metrics.items():
            cfg = METRIC_CONFIG[mkey]
            unit = fc.unit

            def _slope_str(si):
                r2_note = " [dim](불규칙)[/dim]" if si.r2 < 0.3 else ""
                return f"{si.icon} {si.direction}{r2_note}"

            row = [
                cfg["label"],
                f"{fc.baseline}{unit}",
                f"{fc.current_value}{unit}",
                _slope_str(fc.slope_a),
                _slope_str(fc.slope_b),
            ]
            for h in sorted(horizon_hours):
                pred  = fc.predicted.get(h, "-")
                risk  = fc.risk.get(h, "정상")
                color = RISK_COLOR[risk]
                row.append(f"[{color}]{pred}{unit}[/{color}]")

            if fc.threshold_reach_h is not None:
                row.append(f"[yellow]~{fc.threshold_reach_h}h 후 주의[/yellow]")
            else:
                row.append("[dim]없음[/dim]")

            tbl.add_row(*row)

        console.print(tbl)

    _print_forecast_summary(results, horizon_hours)


def _print_forecast_summary(results: dict, horizon_hours: list) -> None:
    """종합 리스크 요약 테이블."""
    from src.forecaster import METRIC_CONFIG

    RISK_ORDER = {"정상": 0, "주의": 1, "위험": 2}
    RISK_COLOR = {"정상": "green", "주의": "yellow", "위험": "red"}
    max_h = max(horizon_hours)

    tbl = Table(
        box=box.SIMPLE_HEAD,
        title=f"[bold]종합 리스크 요약 ({max_h}h 기준)[/bold]",
        header_style="bold",
        expand=False,
    )
    tbl.add_column("서버", style="cyan", min_width=12)
    for mkey, cfg in METRIC_CONFIG.items():
        tbl.add_column(cfg["label"], justify="center", min_width=9)
    tbl.add_column("종합", justify="center", min_width=8)

    for server, metrics in results.items():
        row = [server]
        risks = []
        for mkey in METRIC_CONFIG:
            fc = metrics.get(mkey)
            if fc is None:
                row.append("[dim]-[/dim]")
                continue
            r     = fc.risk.get(max_h, "정상")
            color = RISK_COLOR[r]
            row.append(f"[{color}]{r}[/{color}]")
            risks.append(r)

        if risks:
            worst = max(risks, key=lambda r: RISK_ORDER.get(r, 0))
            row.append(f"[bold {RISK_COLOR[worst]}]{worst}[/bold {RISK_COLOR[worst]}]")
        else:
            row.append("[dim]-[/dim]")

        tbl.add_row(*row)

    console.print(tbl)


def save_report(summary: dict, analysis: str, timestamp: str, output_dir: str,
                template_path: str = None, comparison: dict = None) -> str:
    os.makedirs(output_dir, exist_ok=True)
    filename = f"report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.md"
    filepath = os.path.join(output_dir, filename)

    # 메트릭 테이블 행 생성
    metrics_rows = []
    for inst, m in summary["servers"].items():
        cpu = m["cpu"]
        mem = m["memory"]
        net = m["network"]
        metrics_rows.append(
            f"| {inst} | {m['status']} | {cpu['avg_pct']}% | {cpu['max_pct']}% "
            f"| {mem['latest_pct']}% | {net['rx_max_mbps']} Mbps | {net['tx_max_mbps']} Mbps |"
        )

    # 알림 목록 생성
    alert_lines = []
    for inst, m in summary["servers"].items():
        for alert in m["alerts"]:
            alert_lines.append(f"- **{inst}**: {alert}")
    if not alert_lines:
        alert_lines.append("- 이상 없음")

    # 전일 비교 테이블 (Markdown)
    comparison_rows = []
    if comparison:
        from src.comparator import METRIC_LABELS, TREND_ICON
        comparison_rows.append(
            "| 서버 | 지표 | 전일 | 당일 | 변화(%) | 추세 |"
        )
        comparison_rows.append("|---|---|---|---|---|---|")
        for inst, metrics in comparison.items():
            for key, d in metrics.items():
                sign = "+" if d["delta_pct"] >= 0 else ""
                comparison_rows.append(
                    f"| {inst} | {METRIC_LABELS[key]} | {d['yesterday']}{d['unit']} "
                    f"| {d['today']}{d['unit']} | {sign}{d['delta_pct']}% "
                    f"| {TREND_ICON[d['trend']]} {d['trend']} |"
                )

    # 템플릿 로드 및 치환
    if template_path and os.path.exists(template_path):
        tpl = _load_template(template_path)
    else:
        # 템플릿 파일 없을 때 내장 폴백
        tpl = (
            "# 일일점검 리포트\n\n"
            "**점검 시각:** {timestamp}\n\n---\n\n"
            "## 서버 메트릭 요약\n\n"
            "| 서버 | 상태 | CPU avg | CPU max | MEM | Rx max | Tx max |\n"
            "|------|------|---------|---------|-----|--------|--------|\n"
            "{metrics_table}\n\n"
            "## 전일 대비 비교\n\n{comparison_table}\n\n"
            "## 알림 목록\n\n{alerts_list}\n\n---\n\n"
            "## AI 분석 결과\n\n{ai_analysis}\n"
        )

    content = tpl.format(
        timestamp=timestamp,
        metrics_table="\n".join(metrics_rows),
        comparison_table="\n".join(comparison_rows) if comparison_rows else "전일 데이터 없음",
        alerts_list="\n".join(alert_lines),
        ai_analysis=analysis,
    )

    with open(filepath, "w", encoding="utf-8") as f:
        f.write(content)

    return filepath
