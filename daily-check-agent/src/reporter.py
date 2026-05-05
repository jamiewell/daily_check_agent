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


def print_llm_analysis(analysis: str) -> None:
    console.print(Panel(analysis, title="[bold green]AI 분석 결과[/bold green]", border_style="green"))


def save_report(summary: dict, analysis: str, timestamp: str, output_dir: str,
                template_path: str = None) -> str:
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
            "## 알림 목록\n\n{alerts_list}\n\n---\n\n"
            "## AI 분석 결과\n\n{ai_analysis}\n"
        )

    content = tpl.format(
        timestamp=timestamp,
        metrics_table="\n".join(metrics_rows),
        alerts_list="\n".join(alert_lines),
        ai_analysis=analysis,
    )

    with open(filepath, "w", encoding="utf-8") as f:
        f.write(content)

    return filepath
