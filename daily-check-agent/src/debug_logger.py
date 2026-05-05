"""디버그 모드 유틸리티 — 파일/라인 에러 추적, HTTP 통신 로깅, 진단 도구."""

import sys
import os
import traceback
import json
import time
import importlib.metadata
from datetime import datetime

from rich.console import Console, Group
from rich.panel import Panel
from rich.syntax import Syntax
from rich.table import Table
from rich.text import Text
from rich import box

console = Console()

# 디버그 모드 전역 플래그
_debug_enabled = False


def enable():
    global _debug_enabled
    _debug_enabled = True


def is_enabled() -> bool:
    return _debug_enabled


# ---------------------------------------------------------------------------
# 예외 핸들러 — 파일명 + 라인 번호 강조 출력
# ---------------------------------------------------------------------------

def install_exception_hook():
    """sys.excepthook 을 교체해 파일/라인 정보를 Rich로 출력."""
    def _hook(exc_type, exc_value, exc_tb):
        console.print("\n[bold red]── 예외 발생 ──────────────────────────────[/bold red]")
        tb_lines = traceback.extract_tb(exc_tb)
        for frame in tb_lines:
            rel = os.path.relpath(frame.filename)
            console.print(
                f"  [cyan]{rel}[/cyan]:[yellow]{frame.lineno}[/yellow]  "
                f"in [bold]{frame.name}[/bold]"
            )
            console.print(f"    [dim]{frame.line}[/dim]")
        console.print(f"\n[bold red]{exc_type.__name__}[/bold red]: {exc_value}\n")

    sys.excepthook = _hook


# ---------------------------------------------------------------------------
# HTTP 통신 로거
# ---------------------------------------------------------------------------

def log_request(label: str, url: str, payload: dict):
    if not _debug_enabled:
        return
    body = json.dumps(payload, ensure_ascii=False, indent=2)
    console.print(Panel(
        Group(Text.from_markup(f"[bold]URL:[/bold] {url}\n"), Syntax(body, "json", theme="monokai")),
        title=f"[bold yellow]▶ HTTP 요청 — {label}[/bold yellow]",
        border_style="yellow",
    ))


def log_response(label: str, status: int, data: dict, elapsed: float):
    if not _debug_enabled:
        return
    body = json.dumps(data, ensure_ascii=False, indent=2)[:2000]
    console.print(Panel(
        Group(
            Text.from_markup(f"[bold]Status:[/bold] {status}  [bold]응답시간:[/bold] {elapsed:.2f}초\n"),
            Syntax(body, "json", theme="monokai"),
        ),
        title=f"[bold green]◀ HTTP 응답 — {label}[/bold green]",
        border_style="green",
    ))


def log_error(label: str, exc: Exception):
    if not _debug_enabled:
        return
    tb = traceback.format_exc()
    console.print(Panel(
        f"[bold red]{type(exc).__name__}[/bold red]: {exc}\n\n"
        f"[dim]{tb}[/dim]",
        title=f"[bold red]✗ 오류 — {label}[/bold red]",
        border_style="red",
    ))


def log_step(msg: str):
    if not _debug_enabled:
        return
    console.print(f"[dim cyan][DEBUG] {msg}[/dim cyan]")


# ---------------------------------------------------------------------------
# 전체 진단 커맨드
# ---------------------------------------------------------------------------

def run_diagnostics(cfg: dict, config_path: str):
    """전체 환경 진단 — debug 커맨드에서 호출."""
    import requests
    console.print(Panel(
        f"[bold cyan]일일점검 에이전트 — 디버그 진단[/bold cyan]\n"
        f"실행 시각: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        expand=False,
    ))

    results = []

    # ── 1. Python 환경 ──────────────────────────────────────────────────────
    pv = sys.version.split()[0]
    results.append(("Python 버전", pv, pv >= "3.12", ""))

    # ── 2. 패키지 설치 상태 ─────────────────────────────────────────────────
    required = ["click", "rich", "pyyaml", "requests"]
    for pkg in required:
        try:
            ver = importlib.metadata.version(pkg)
            results.append((f"패키지 {pkg}", ver, True, ""))
        except importlib.metadata.PackageNotFoundError:
            results.append((f"패키지 {pkg}", "미설치", False, "pip install " + pkg))

    # ── 3. 설정 파일 ─────────────────────────────────────────────────────────
    results.append(("config.yaml", config_path,
                    os.path.exists(config_path), "파일 없음"))

    # ── 4. 템플릿 파일 ───────────────────────────────────────────────────────
    base = os.path.dirname(os.path.abspath(config_path))
    tpl_dir = os.path.join(base, cfg.get("templates", {}).get("dir", "templates"))
    for f in ["prompt_analyze.txt", "prompt_system.txt", "report.md.template"]:
        p = os.path.join(tpl_dir, f)
        results.append((f"템플릿 {f}", p, os.path.exists(p), "파일 없음"))

    # ── 5. 샘플 데이터 ───────────────────────────────────────────────────────
    sd = os.path.join(base, cfg["data"]["sample_dir"])
    for f in ["cpu.json", "memory.json", "network.json"]:
        p = os.path.join(sd, f)
        results.append((f"샘플 {f}", p, os.path.exists(p), "파일 없음"))

    # ── 6. Ollama 연결 ───────────────────────────────────────────────────────
    ollama_base = cfg["ollama"]["url"].replace("/api/generate", "")
    try:
        t0 = time.time()
        r = requests.get(f"{ollama_base}/api/tags", timeout=5)
        models = [m["name"] for m in r.json().get("models", [])]
        elapsed = time.time() - t0
        results.append(("Ollama 연결", f"OK ({elapsed:.2f}s) — {', '.join(models)}", True, ""))
    except Exception as e:
        results.append(("Ollama 연결", str(e), False, "ollama serve 실행 확인"))

    # ── 7. Qwen3 응답 테스트 ─────────────────────────────────────────────────
    model = cfg["ollama"]["model"]
    try:
        t0 = time.time()
        r = requests.post(
            cfg["ollama"]["url"],
            json={"model": model, "prompt": "1+1=?", "stream": False,
                  "options": {"num_predict": 10}},
            timeout=60,
        )
        r.raise_for_status()
        answer = r.json().get("response", "").strip()
        elapsed = time.time() - t0
        tok = r.json().get("eval_count", 0)
        results.append((f"{model} 응답 테스트",
                        f'"{answer}" ({elapsed:.1f}s, {tok}tok)', True, ""))
    except Exception as e:
        results.append((f"{model} 응답 테스트", str(e), False, "모델 설치 확인"))

    # ── 8. Grafana API 연결 (token이 설정된 경우만) ──────────────────────────
    g = cfg.get("grafana", {})
    if g.get("token") and g["token"] != "glsa_...":
        gurl = g["url"].replace("/api/ds/query", "/api/health")
        try:
            t0 = time.time()
            r = requests.get(gurl,
                             headers={"Authorization": f"Bearer {g['token']}"},
                             verify=g.get("verify_ssl", False), timeout=10)
            elapsed = time.time() - t0
            results.append(("Grafana API 연결",
                            f"HTTP {r.status_code} ({elapsed:.2f}s)", r.status_code == 200,
                            "" if r.status_code == 200 else r.text[:100]))
        except Exception as e:
            results.append(("Grafana API 연결", str(e), False, "URL/Token/포트 확인"))
    else:
        results.append(("Grafana API 연결", "config.yaml 미설정 — 샘플 모드", None, ""))

    # ── 결과 테이블 출력 ─────────────────────────────────────────────────────
    table = Table(box=box.ROUNDED, header_style="bold magenta", show_header=True)
    table.add_column("항목", min_width=22)
    table.add_column("결과", min_width=40)
    table.add_column("상태", justify="center", min_width=6)
    table.add_column("조치 필요", min_width=24)

    for name, value, ok, fix in results:
        if ok is True:
            status = "[green]OK[/green]"
        elif ok is False:
            status = "[red]FAIL[/red]"
        else:
            status = "[dim]SKIP[/dim]"
        table.add_row(name, str(value), status, fix)

    console.print(table)

    fail_count = sum(1 for _, _, ok, _ in results if ok is False)
    if fail_count == 0:
        console.print("[bold green]모든 항목 정상[/bold green]")
    else:
        console.print(f"[bold red]실패 항목 {fail_count}건 — 위 조치 필요 컬럼 확인[/bold red]")
