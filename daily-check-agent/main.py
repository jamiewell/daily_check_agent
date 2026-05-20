#!/usr/bin/env python3
"""Daily Check Agent — CLI entry point."""

import os
import sys
from datetime import datetime, timezone, timedelta

# Windows 콘솔 UTF-8 강제 설정 (한글 깨짐 방지)
if sys.platform == "win32":
    import ctypes
    ctypes.windll.kernel32.SetConsoleCP(65001)
    ctypes.windll.kernel32.SetConsoleOutputCP(65001)
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

_KST = timezone(timedelta(hours=9))


def _kst_now() -> datetime:
    """현재 한국 표준시 (KST = UTC+9). 머신 timezone에 무관하게 항상 KST 반환."""
    return datetime.now(_KST)


def _kst_timestamp() -> str:
    return _kst_now().strftime("%Y-%m-%d %H:%M:%S KST")

import click
import yaml

# Allow running from project root without installing package (dev mode only)
# PyInstaller frozen builds handle sys.path automatically via bundled modules
if not getattr(sys, 'frozen', False):
    sys.path.insert(0, os.path.dirname(__file__))

from src.data_loader import load_all, load_forecast_data
from src.preprocessor import summarize
from src.llm_client import OllamaClient, LlamaCppClient
from src.reporter import console, print_summary, print_comparison, print_llm_analysis, save_report, print_forecast
from src.comparator import compare as do_compare, comparison_text
from src.forecaster import forecast_all, forecast_to_text
from src import debug_logger as dbg
from src import llama_server

# exe 더블클릭(인자 없음) 시 chat --auto-analyze 모드로 진입
# → analyze 결과를 먼저 출력한 뒤 대화 루프를 유지 (quit/종료 전까지 실행)
if getattr(sys, 'frozen', False) and len(sys.argv) == 1:
    sys.argv += ['chat', '--auto-analyze']


def _load_config(config_path: str) -> dict:
    with open(config_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def _resolve_sample_dir(cfg: dict, config_path: str) -> str:
    base = os.path.dirname(os.path.abspath(config_path))
    return os.path.join(base, cfg["data"]["sample_dir"])


def _load_yesterday(cfg: dict, config_path: str, thresholds: dict):
    """전일 샘플 데이터 로드 및 요약. 디렉토리 없으면 None 반환."""
    yd_key = cfg["data"].get("sample_dir_yesterday")
    if not yd_key:
        return None
    base = os.path.dirname(os.path.abspath(config_path))
    yd_dir = os.path.join(base, yd_key)
    if not os.path.isdir(yd_dir):
        return None
    raw_yd = load_all(yd_dir)
    return summarize(raw_yd, thresholds)


def _resolve_templates(cfg: dict, config_path: str) -> dict:
    base = os.path.dirname(os.path.abspath(config_path))
    tpl_dir = os.path.join(base, cfg.get("templates", {}).get("dir", "templates"))
    tpl = cfg.get("templates", {})
    return {
        "dir": tpl_dir,
        "prompt_analyze": tpl.get("prompt_analyze", "prompt_analyze.txt"),
        "prompt_system":  tpl.get("prompt_system",  "prompt_system.txt"),
        "report":         os.path.join(tpl_dir, tpl.get("report", "report.md.template")),
    }


def _print_llm_status(result, prefix: str = "") -> None:
    """LLM 응답 메타데이터를 한 줄 상태로 출력."""
    console.print(
        f"[dim]{prefix}모델: {result.model if hasattr(result, 'model') else 'qwen3'} │ "
        f"전송 {result.prompt_tokens}tok → 수신 {result.response_tokens}tok │ "
        f"응답시간 {result.elapsed:.1f}초[/dim]"
    )


def _make_llm(cfg: dict, config_path: str):
    """config.yaml 의 llama_cpp.enabled 여부에 따라 클라이언트 선택."""
    tpl = _resolve_templates(cfg, config_path)
    common = dict(
        templates_dir=tpl["dir"],
        prompt_analyze_file=tpl["prompt_analyze"],
        prompt_system_file=tpl["prompt_system"],
    )
    lc_cfg = cfg.get("llama_cpp", {})
    if lc_cfg.get("enabled", False):
        return LlamaCppClient(
            host=lc_cfg.get("host", "127.0.0.1"),
            port=lc_cfg.get("port", 8080),
            temperature=lc_cfg.get("temperature", 0.3),
            max_tokens=lc_cfg.get("max_tokens", 512),
            **common,
        )
    return OllamaClient(
        url=cfg["ollama"]["url"],
        model=cfg["ollama"]["model"],
        temperature=cfg["ollama"]["temperature"],
        num_predict=cfg["ollama"]["num_predict"],
        **common,
    )


def _start_llama_server_if_needed(cfg: dict):
    """llama_cpp.enabled 이고 서버가 꺼져 있으면 기동. 프로세스 객체 반환(없으면 None)."""
    lc_cfg = cfg.get("llama_cpp", {})
    if not lc_cfg.get("enabled", False):
        return None
    port = lc_cfg.get("port", 8080)
    import requests as _req
    try:
        _req.get(f"http://127.0.0.1:{port}/health", timeout=1)
        console.print(f"[dim]llama-server 이미 실행 중 (port {port})[/dim]")
        return None
    except Exception:
        pass
    console.print(f"[bold]llama-server 시작 중 (port {port})...[/bold]")
    proc = llama_server.start(
        port=port,
        model_file=lc_cfg.get("model_file", "runtime/models/qwen3-0.6b-q4_k_m.gguf"),
        context_size=lc_cfg.get("context_size", 2048),
        threads=lc_cfg.get("threads", 4),
        server_exe=lc_cfg.get("server_exe"),
        lib_dir=lc_cfg.get("lib_dir"),
    )
    console.print("[green]llama-server 시작 완료[/green]")
    return proc


@click.group()
@click.option("--config", default="config.yaml", show_default=True, help="설정 파일 경로")
@click.option("--debug", is_flag=True, default=False, help="디버그 모드 (HTTP 통신·에러 상세 출력)")
@click.pass_context
def cli(ctx, config, debug):
    """금융시스템 일일점검 AI 에이전트"""
    ctx.ensure_object(dict)
    if debug:
        dbg.enable()
        dbg.install_exception_hook()
        console.print("[bold yellow][DEBUG MODE ON][/bold yellow]")
    cfg = _load_config(config)
    ctx.obj["cfg"] = cfg
    ctx.obj["config_path"] = config


@cli.command()
@click.option("--save/--no-save", default=False, show_default=True, help="리포트 파일 저장 여부")
@click.pass_context
def check(ctx, save):
    """메트릭 수집 + 요약 테이블 + 전일 비교 출력 (LLM 분석 없음)"""
    cfg = ctx.obj["cfg"]
    sample_dir = _resolve_sample_dir(cfg, ctx.obj["config_path"])
    timestamp = _kst_timestamp()
    today_lbl, yesterday_lbl = _date_labels()

    console.print("[bold]데이터 로딩 중...[/bold]")
    raw = load_all(sample_dir)
    summary = summarize(raw, cfg["thresholds"])
    print_summary(summary, timestamp)

    # 전일 비교
    summary_yd  = _load_yesterday(cfg, ctx.obj["config_path"], cfg["thresholds"])
    comparison  = do_compare(summary, summary_yd) if summary_yd else None
    if comparison:
        print_comparison(comparison, today_lbl, yesterday_lbl)
    else:
        console.print("[dim]전일 데이터 없음 — 비교 생략[/dim]")

    if save:
        tpl = _resolve_templates(cfg, ctx.obj["config_path"])
        path = save_report(summary, "(LLM 분석 생략)", timestamp,
                           cfg["reports"]["output_dir"], tpl["report"], comparison)
        console.print(f"\n[dim]리포트 저장됨: {path}[/dim]")


@cli.command()
@click.option("--save/--no-save", default=False, show_default=True, help="리포트 파일 저장 여부")
@click.pass_context
def analyze(ctx, save):
    """메트릭 수집 + 전일 비교 + AI 분석 (Ollama 또는 llama.cpp)"""
    cfg = ctx.obj["cfg"]
    sample_dir = _resolve_sample_dir(cfg, ctx.obj["config_path"])
    timestamp = _kst_timestamp()
    today_lbl, yesterday_lbl = _date_labels()

    server_proc = _start_llama_server_if_needed(cfg)
    try:
        console.print("[bold]데이터 로딩 중...[/bold]")
        raw = load_all(sample_dir)
        summary = summarize(raw, cfg["thresholds"])
        print_summary(summary, timestamp)

        # 전일 비교
        summary_yd = _load_yesterday(cfg, ctx.obj["config_path"], cfg["thresholds"])
        comparison = do_compare(summary, summary_yd) if summary_yd else None
        if comparison:
            print_comparison(comparison, today_lbl, yesterday_lbl)

        tpl = _resolve_templates(cfg, ctx.obj["config_path"])
        llm = _make_llm(cfg, ctx.obj["config_path"])
        with console.status("[bold]AI 분석 중...[/bold]", spinner="dots"):
            result = llm.analyze(summary, comparison=comparison)
        _print_llm_status(result)
        print_llm_analysis(str(result))

        if save:
            path = save_report(summary, str(result), timestamp,
                               cfg["reports"]["output_dir"], tpl["report"], comparison)
            console.print(f"[dim]리포트 저장됨: {path}[/dim]")
    finally:
        llama_server.stop(server_proc)


@cli.command()
@click.option("--metric", default="all",
              type=click.Choice(["all", "cpu", "memory", "network", "disk"]),
              show_default=True, help="예측 대상 메트릭")
@click.option("--horizon", default="1,3,6", show_default=True,
              help="예측 구간 (시간, 콤마 구분)")
@click.option("--llm/--no-llm", default=True, show_default=True,
              help="LLM 자연어 해석 포함 여부")
@click.pass_context
def predict(ctx, metric, horizon, llm):
    """사용률 예측 — 전일 24h 시계열 분석 (slope A/B/C 방식)"""
    cfg = ctx.obj["cfg"]
    horizon_hours = [int(h.strip()) for h in horizon.split(",")]
    predict_hour  = _kst_now().hour

    forecast_dir = _resolve_forecast_dir(cfg, ctx.obj["config_path"])
    console.print("[bold]24h 예측 데이터 로딩 중...[/bold]")
    fc_data = load_forecast_data(forecast_dir)
    if not fc_data:
        console.print(f"[red]예측 데이터 없음: {forecast_dir}[/red]")
        return

    sample_dir = _resolve_sample_dir(cfg, ctx.obj["config_path"])
    raw_today  = load_all(sample_dir)

    results = forecast_all(
        forecast_data=fc_data,
        raw_today=raw_today,
        predict_hour=predict_hour,
        horizon_hours=horizon_hours,
        thresholds=cfg["thresholds"],
        metric_filter=metric,
    )
    print_forecast(results, horizon_hours, predict_hour)

    if llm:
        server_proc = _start_llama_server_if_needed(cfg)
        try:
            llm_client = _make_llm(cfg, ctx.obj["config_path"])
            fc_text = forecast_to_text(results, horizon_hours)
            messages = [
                {"role": "system", "content": "당신은 금융 IT 인프라 운영 전문가입니다. 한국어로 답변하세요."},
                {"role": "user",   "content": _build_predict_context(fc_text)},
            ]
            with console.status("[bold]AI 예측 해석 중...[/bold]", spinner="dots"):
                llm_result = llm_client.chat(messages)
            _print_llm_status(llm_result)
            print_llm_analysis(str(llm_result))
        finally:
            llama_server.stop(server_proc)


CHECK_KEYWORDS        = ("일일점검", "점검", "분석해줘", "서버 점검", "check", "분석 시작", "점검 시작")
COMPARE_KEYWORDS      = ("전일 비교", "전일대비", "어제와 비교", "오늘 vs 어제", "어제 비교", "전일과 비교", "비교 분석", "비교분석", "당일 비교", "전일 당일", "당일 전일", "어제오늘", "오늘어제", "전일비교", "오늘비교")
QUICK_CHECK_KEYWORDS  = ("현황 확인", "현황 보여", "빠른 점검", "메트릭만", "표만", "지표 확인")
REPORT_KEYWORDS       = ("리포트 만들어", "리포트 생성", "report 만들어", "report 생성", "리포트 저장")
PREDICT_KEYWORDS      = ("예측", "사용률 예측", "트렌드", "증가 추세", "앞으로 어떻게")
HELP_KEYWORDS         = ("도움말", "help", "명령어", "사용법", "?")


def _is_check_request(text: str) -> bool:
    return any(kw in text for kw in CHECK_KEYWORDS)


def _is_compare_request(text: str) -> bool:
    return any(kw in text for kw in COMPARE_KEYWORDS)


def _is_quick_check_request(text: str) -> bool:
    return any(kw in text for kw in QUICK_CHECK_KEYWORDS)


def _is_report_request(text: str) -> bool:
    return any(kw in text for kw in REPORT_KEYWORDS)


def _is_predict_request(text: str) -> bool:
    return any(kw in text for kw in PREDICT_KEYWORDS)


def _is_help_request(text: str) -> bool:
    return text.strip() in HELP_KEYWORDS or any(kw in text for kw in HELP_KEYWORDS)


def _print_chat_help() -> None:
    from rich.table import Table
    from rich import box as rbox
    tbl = Table(box=rbox.SIMPLE_HEAD, title="[bold cyan]사용 가능한 명령어[/bold cyan]",
                header_style="bold", expand=False)
    tbl.add_column("입력 예시", style="cyan", min_width=32)
    tbl.add_column("기능", min_width=38)
    rows = [
        ("현황 확인  /  현황 보여  /  빠른 점검",  "현재 메트릭 테이블만 출력  (AI 없음, 빠름)"),
        ("일일점검  /  점검  /  분석해줘",          "현재 시점 메트릭 + AI 분석"),
        ("전일 비교  /  어제와 비교  /  비교 분석", "전일↔당일 비교 테이블 + AI 추세 분석"),
        ("예측해줘  /  사용률 예측  /  트렌드",     "시계열 예측 1h/3h/6h + AI 해석"),
        ("리포트 만들어줘  /  리포트 생성",         "마지막 점검 결과를 Markdown 파일로 저장"),
        ("도움말  /  help  /  ?",                  "이 도움말 표시"),
        ("exit  /  quit  /  종료  /  에이전트 종료", "에이전트 종료"),
        ("─ 대상 필터 (모든 기능에 조합 가능) ─", "─────────────────────────────────────"),
        ("승인계 / aut / 전체",                    "AP + DB 전체 서버 대상"),
        ("서버 / 미들웨어 / AP서버",               "AP 서버만 대상"),
        ("DB / 디비 / 데이터베이스",               "DB 서버만 대상"),
    ]
    for kw, desc in rows:
        tbl.add_row(kw, desc)
    console.print(tbl)


def _date_labels() -> tuple:
    """(today_label, yesterday_label) — 비교 테이블 컬럼 헤더용 KST 날짜 문자열."""
    now = _kst_now()
    return (
        f"당일 ({now.strftime('%m-%d')})",
        f"전일 ({(now - timedelta(days=1)).strftime('%m-%d')})",
    )


def _resolve_forecast_dir(cfg: dict, config_path: str) -> str:
    base = os.path.dirname(os.path.abspath(config_path))
    return os.path.join(base, cfg.get("data", {}).get("forecast_dir", "sample_data/forecast"))


def _build_predict_context(forecast_text: str) -> str:
    now = _kst_now()
    return (
        f"현재 시각: {now.strftime('%Y-%m-%d %H:%M KST')}\n\n"
        f"아래는 서버 사용률 시계열 예측 결과야.\n\n"
        f"{forecast_text}\n\n"
        f"예측 결과를 해석하고 주의가 필요한 서버/메트릭을 알려줘. "
        f"임계치 도달 예상이 있으면 구체적인 조치를 권고해줘."
    )


# ── 서버 역할 필터 ────────────────────────────────────────────────────────────
ALL_FILTER_KEYWORDS = ("전체", "모두", "전부", "aut", "승인계")
DB_FILTER_KEYWORDS  = ("디비", "DB", "데이터베이스", "db서버", "DB서버")
AP_FILTER_KEYWORDS  = ("미들웨어", "ap서버", "AP서버", "ap 서버", "AP 서버", "애플리케이션", "서버")


def _detect_role_filter(text: str) -> str:
    """입력에서 서버 역할 필터 감지. 반환: 'ap' | 'db' | 'all'
    우선순위: DB 명시 > AP 명시 > 전체 명시 > 기본(전체)
    '승인계 AP서버' 처럼 혼용 시 구체적 역할(AP/DB)이 우선한다.
    """
    for kw in DB_FILTER_KEYWORDS:
        if kw in text:
            return "db"
    for kw in AP_FILTER_KEYWORDS:
        if kw in text:
            return "ap"
    for kw in ALL_FILTER_KEYWORDS:
        if kw in text:
            return "all"
    return "all"


def _role_label(role: str) -> str:
    return {"ap": "AP서버", "db": "DB서버", "all": "전체 서버"}.get(role, "전체 서버")


def _filter_summary(summary: dict, role: str) -> dict:
    """summary['servers']에서 role에 맞는 서버만 남긴 새 dict 반환."""
    if role == "all":
        return summary
    import copy
    filtered = copy.deepcopy(summary)
    filtered["servers"] = {
        inst: data
        for inst, data in summary["servers"].items()
        if role in inst.lower()
    }
    return filtered


def _filter_forecast(results: dict, role: str) -> dict:
    """forecast results에서 role에 맞는 서버만 남긴 dict 반환."""
    if role == "all":
        return results
    return {
        server: metrics
        for server, metrics in results.items()
        if role in server.lower()
    }


def _build_check_context(summary: dict, comparison=None, role: str = "all") -> str:
    import json
    now = _kst_now()
    servers_text = json.dumps(summary, ensure_ascii=False, indent=2)
    role_desc = {"ap": "AP서버(애플리케이션 서버)", "db": "DB서버(데이터베이스 서버)", "all": "전체 서버(AP+DB)"}.get(role, "전체 서버")
    return (
        f"현재 시각: {now.strftime('%Y-%m-%d %H:%M KST')}\n\n"
        f"분석 대상: {role_desc}\n\n"
        f"아래는 현재 시점의 서버 메트릭 데이터야. 현재 상태를 분석하고 이상 징후와 주의사항을 정리해줘.\n\n"
        f"[현재 서버 메트릭]\n{servers_text}\n\n"
        f"점검 결과를 요약하고 즉시 조치가 필요한 사항이 있으면 알려줘."
    )


def _build_compare_context(summary_today: dict, summary_yesterday: dict, comparison, role: str = "all") -> str:
    from src.comparator import comparison_text as make_comparison_text, METRIC_LABELS, TREND_ICON
    now = _kst_now()
    today_str     = now.strftime("%Y-%m-%d")
    yesterday_str = (now - timedelta(days=1)).strftime("%Y-%m-%d")
    cmp_text  = make_comparison_text(comparison) if comparison else "(비교 데이터 없음)"
    role_desc = {"ap": "AP서버(애플리케이션 서버)", "db": "DB서버(데이터베이스 서버)", "all": "전체 서버(AP+DB)"}.get(role, "전체 서버")

    # 변화가 있는 모든 항목 추출 — 소형 LLM이 반드시 언급하도록 명시
    change_lines = []
    if comparison:
        for inst, metrics in comparison.items():
            for key, d in metrics.items():
                if d["delta_pct"] != 0.0:
                    sign  = "+" if d["delta_pct"] >= 0 else ""
                    flag  = " ★중요" if abs(d["delta_pct"]) >= 10 else ""
                    change_lines.append(
                        f"  - {inst} {METRIC_LABELS[key]}: "
                        f"{d['yesterday']}{d['unit']} → {d['today']}{d['unit']} "
                        f"({sign}{d['delta_pct']}%) {TREND_ICON[d['trend']]} {d['trend']}{flag}"
                    )
    if change_lines:
        change_section = (
            "[변화 감지 항목 — 아래 각 항목을 반드시 분석에 포함할 것]\n"
            + "\n".join(change_lines)
        )
        instruct = "각 변화 항목을 한 문장씩 설명하고, ★중요 항목은 원인 추정과 모니터링 권고를 포함해줘."
    else:
        change_section = "[변화 감지 항목]\n  - 없음 (모든 지표 변화 없음)"
        instruct = "전체적으로 안정적인 상태임을 요약해줘."

    return (
        f"현재 시각: {now.strftime('%Y-%m-%d %H:%M KST')}\n\n"
        f"분석 대상: {role_desc}\n\n"
        f"전일({yesterday_str}) → 당일({today_str}) 상태 변화:\n{cmp_text}\n\n"
        f"{change_section}\n\n"
        f"{instruct}"
    )


@cli.command()
@click.option("--auto-analyze", "auto_analyze", is_flag=True, default=False,
              help="시작 시 analyze 자동 실행 후 대화 루프 진입 (exe 더블클릭 기본 동작)")
@click.pass_context
def chat(ctx, auto_analyze):
    """대화형 AI 에이전트 — '일일점검' 키워드 입력 시 점검 실행"""
    cfg = ctx.obj["cfg"]
    sample_dir = _resolve_sample_dir(cfg, ctx.obj["config_path"])
    tpl = _resolve_templates(cfg, ctx.obj["config_path"])

    server_proc = _start_llama_server_if_needed(cfg)
    try:
        llm = _make_llm(cfg, ctx.obj["config_path"])

        # 백엔드에 맞는 모델 정보 표시
        lc_cfg = cfg.get("llama_cpp", {})
        if lc_cfg.get("enabled", False):
            model_info = (f"llama.cpp │ 온도: {lc_cfg.get('temperature', 0.3)} │ "
                          f"최대 토큰: {lc_cfg.get('max_tokens', 512)}")
        else:
            model_info = (f"모델: {cfg['ollama']['model']} │ "
                          f"온도: {cfg['ollama']['temperature']} │ "
                          f"최대 토큰: {cfg['ollama']['num_predict']}")

        messages = [
            {
                "role": "system",
                "content": (
                    "당신은 금융 IT 인프라 운영 전문가입니다. 한국어로 답변하세요. "
                    "사용자가 '일일점검' 또는 '점검'을 요청하면 서버 메트릭 데이터를 분석합니다."
                ),
            }
        ]

        console.print("[bold cyan]일일점검 AI 에이전트[/bold cyan] 시작")
        console.print(f"[dim]{model_info}[/dim]")
        console.print("[dim]'도움말' 또는 '?' 입력 시 전체 명령어 목록을 확인할 수 있습니다.[/dim]\n")

        # 마지막 점검 결과 — 리포트 요청 시 재사용
        last_summary    = None
        last_comparison = None
        last_analysis   = ""
        last_timestamp  = ""

        # 토큰 사용량 추적
        lc_cfg_chat = cfg.get("llama_cpp", {})
        ctx_size = lc_cfg_chat.get("context_size", 4096) if lc_cfg_chat.get("enabled", False) else 4096
        tok_warn  = int(ctx_size * 0.9)
        current_tokens = 0

        # exe 더블클릭 시 analyze 자동 선행 실행
        if auto_analyze:
            console.print("[bold]시작 시 자동 점검을 실행합니다...[/bold]\n")
            last_timestamp = _kst_timestamp()
            raw = load_all(sample_dir)
            last_summary = summarize(raw, cfg["thresholds"])
            last_comparison = None
            print_summary(last_summary, last_timestamp)
            messages.append({"role": "user", "content": _build_check_context(last_summary)})
            with console.status("[bold]AI 분석 중...[/bold]", spinner="dots"):
                result = llm.analyze(last_summary, comparison=None)
            _print_llm_status(result)
            last_analysis = str(result)
            print_llm_analysis(last_analysis)
            messages.append({"role": "assistant", "content": last_analysis})
            if result.prompt_tokens > 0:
                current_tokens = result.prompt_tokens + result.response_tokens
            console.print("[dim]분석 완료. 추가 질문을 입력하거나 'exit' / 'quit' / '종료' 로 종료하세요.[/dim]\n")

        while True:
            # 토큰 임계치 경고 및 초기화 선택 (임시 비활성화)
            # if current_tokens >= tok_warn:
            #     pct = current_tokens / ctx_size * 100
            #     console.print(
            #         f"\n[bold yellow]⚠  토큰 정리 필요[/bold yellow]  "
            #         f"[yellow]{current_tokens}/{ctx_size}tok ({pct:.0f}%)[/yellow]"
            #     )
            #     try:
            #         answer = input("대화 이력을 초기화하시겠습니까? (y/n) > ").strip().lower()
            #     except (EOFError, KeyboardInterrupt):
            #         console.print("\n[dim]대화 종료.[/dim]")
            #         break
            #     if answer in ("y", "yes", "예", "네"):
            #         messages = [m for m in messages if m["role"] == "system"]
            #         current_tokens = 0
            #         console.print("[green]대화 이력 초기화 완료.[/green]\n")
            #         continue

            # 입력 프롬프트 (토큰 수 표시)
            tok_label = f" [{current_tokens}/{ctx_size}tok]" if current_tokens > 0 else ""
            try:
                user_input = input(f"You{tok_label} > ").strip()
            except (EOFError, KeyboardInterrupt):
                console.print("\n[dim]대화 종료.[/dim]")
                break

            if not user_input:
                continue
            if user_input.lower() in ("exit", "quit", "종료", "q", "에이전트 종료"):
                console.print("[dim]에이전트를 종료합니다.[/dim]")
                break

            # 도움말 키워드
            if _is_help_request(user_input):
                _print_chat_help()
                continue

            # 빠른 현황 키워드 (LLM 없이 테이블 + 전일 비교만)
            if _is_quick_check_request(user_input):
                role = _detect_role_filter(user_input)
                last_timestamp = _kst_timestamp()
                today_lbl, yesterday_lbl = _date_labels()
                console.print(f"\n[bold]데이터 로딩 중... [{_role_label(role)}][/bold]")
                raw = load_all(sample_dir)
                last_summary = _filter_summary(summarize(raw, cfg["thresholds"]), role)
                print_summary(last_summary, last_timestamp)
                summary_yd_full = _load_yesterday(cfg, ctx.obj["config_path"], cfg["thresholds"])
                if summary_yd_full:
                    summary_yd = _filter_summary(summary_yd_full, role)
                    last_comparison = do_compare(last_summary, summary_yd)
                    print_comparison(last_comparison, today_lbl, yesterday_lbl)
                else:
                    last_comparison = None
                    console.print("[dim]전일 데이터 없음 — 비교 생략[/dim]")
                console.print("[dim]AI 분석이 필요하면 '점검해줘'를 입력하세요.[/dim]\n")
                continue

            # 예측 키워드 감지
            if _is_predict_request(user_input):
                role   = _detect_role_filter(user_input)
                p_hour = _kst_now().hour
                fc_dir = _resolve_forecast_dir(cfg, ctx.obj["config_path"])
                fc_data = load_forecast_data(fc_dir)
                if not fc_data:
                    console.print(f"[yellow]예측 데이터 없음: {fc_dir}[/yellow]")
                else:
                    raw_t = load_all(sample_dir)
                    fc_results = _filter_forecast(forecast_all(
                        forecast_data=fc_data,
                        raw_today=raw_t,
                        predict_hour=p_hour,
                        horizon_hours=[1, 3, 6],
                        thresholds=cfg["thresholds"],
                    ), role)
                    console.print(f"[dim]예측 대상: {_role_label(role)}[/dim]")
                    print_forecast(fc_results, [1, 3, 6], p_hour)
                    fc_text = forecast_to_text(fc_results, [1, 3, 6])
                    predict_ctx = _build_predict_context(fc_text)
                    predict_messages = [
                        {"role": "system", "content": "당신은 금융 IT 인프라 운영 전문가입니다. 한국어로 간결하게 답변하세요."},
                        {"role": "user",   "content": predict_ctx},
                    ]
                    with console.status("[bold]AI 예측 해석 중...[/bold]", spinner="dots"):
                        result = llm.chat(predict_messages)
                    _print_llm_status(result)
                    messages.append({"role": "user",      "content": predict_ctx})
                    messages.append({"role": "assistant", "content": str(result)})
                    print_llm_analysis(str(result))
                    if result.prompt_tokens > 0:
                        current_tokens = result.prompt_tokens + result.response_tokens
                continue

            # 전일 비교 키워드 감지
            if _is_compare_request(user_input):
                role = _detect_role_filter(user_input)
                last_timestamp = _kst_timestamp()
                today_lbl, yesterday_lbl = _date_labels()
                console.print(f"\n[bold]데이터 로딩 중... [{_role_label(role)}][/bold]")
                raw = load_all(sample_dir)
                last_summary = _filter_summary(summarize(raw, cfg["thresholds"]), role)
                summary_yd_full = _load_yesterday(cfg, ctx.obj["config_path"], cfg["thresholds"])
                if summary_yd_full is None:
                    console.print("[yellow]전일 데이터 없음 — 비교를 진행할 수 없습니다.[/yellow]")
                    continue
                summary_yd = _filter_summary(summary_yd_full, role)
                last_comparison = do_compare(last_summary, summary_yd)
                # ── 1. 전일↔당일 비교 테이블 먼저 출력 ──────────────────────
                console.print(f"\n[bold cyan]■ 전일 대비 당일 시스템 현황 비교  [{_role_label(role)}][/bold cyan]  [dim]{last_timestamp}[/dim]")
                print_comparison(last_comparison, today_lbl, yesterday_lbl)
                # ── 2. AI 비교 분석 (독립 메시지 — 누적 이력 배제로 토큰 절약) ──
                compare_ctx = _build_compare_context(last_summary, summary_yd, last_comparison, role=role)
                compare_messages = [
                    {"role": "system", "content": "당신은 금융 IT 인프라 운영 전문가입니다. 한국어로 간결하게 답변하세요."},
                    {"role": "user",   "content": compare_ctx},
                ]
                with console.status("[bold]AI 비교 분석 중...[/bold]", spinner="dots"):
                    result = llm.chat(compare_messages)
                _print_llm_status(result)
                last_analysis = str(result)
                messages.append({"role": "user",      "content": compare_ctx})
                messages.append({"role": "assistant", "content": last_analysis})
                print_llm_analysis(last_analysis)
                if result.prompt_tokens > 0:
                    current_tokens = result.prompt_tokens + result.response_tokens
                console.print("[dim]리포트를 저장하려면 '리포트 만들어줘'라고 입력하세요.[/dim]\n")
                continue

            # 리포트 저장 키워드 감지
            if _is_report_request(user_input):
                if last_summary is None:
                    console.print("[yellow]먼저 점검을 실행해 주세요. ('일일점검' 또는 '점검' 입력)[/yellow]")
                    continue
                path = save_report(last_summary, last_analysis, last_timestamp,
                                   cfg["reports"]["output_dir"], tpl["report"], last_comparison)
                console.print(f"[green]리포트 저장됨:[/green] {path}\n")
                continue

            # 점검 키워드 감지
            if _is_check_request(user_input):
                role = _detect_role_filter(user_input)
                last_timestamp = _kst_timestamp()
                console.print(f"\n[bold]데이터 로딩 중... [{_role_label(role)}][/bold]")
                raw = load_all(sample_dir)
                last_summary = _filter_summary(summarize(raw, cfg["thresholds"]), role)
                last_comparison = None
                print_summary(last_summary, last_timestamp)

                check_ctx = _build_check_context(last_summary, role=role)
                check_messages = [
                    {"role": "system", "content": "당신은 금융 IT 인프라 운영 전문가입니다. 한국어로 간결하게 답변하세요."},
                    {"role": "user",   "content": check_ctx},
                ]
                with console.status("[bold]AI 점검 분석 중...[/bold]", spinner="dots"):
                    result = llm.chat(check_messages)
                _print_llm_status(result)
                last_analysis = str(result)
                messages.append({"role": "user",      "content": check_ctx})
                messages.append({"role": "assistant", "content": last_analysis})
                print_llm_analysis(last_analysis)
                if result.prompt_tokens > 0:
                    current_tokens = result.prompt_tokens + result.response_tokens
                console.print("[dim]리포트를 저장하려면 '리포트 만들어줘'라고 입력하세요.[/dim]\n")
                continue

            # 일반 대화
            messages.append({"role": "user", "content": user_input})
            with console.status("[bold]AI 응답 중...[/bold]", spinner="dots"):
                result = llm.chat(messages)
            _print_llm_status(result)
            messages.append({"role": "assistant", "content": str(result)})
            print_llm_analysis(str(result))
            if result.prompt_tokens > 0:
                current_tokens = result.prompt_tokens + result.response_tokens

    finally:
        llama_server.stop(server_proc)


@cli.command(name="debug")
@click.pass_context
def debug_cmd(ctx):
    """전체 환경 진단 — 연결·패키지·파일·LLM 응답 일괄 점검"""
    dbg.enable()
    dbg.install_exception_hook()
    from src.debug_logger import run_diagnostics
    run_diagnostics(ctx.obj["cfg"], ctx.obj["config_path"])


@cli.command()
@click.pass_context
def status(ctx):
    """Ollama 서버 연결 상태 확인"""
    import requests
    cfg = ctx.obj["cfg"]
    base_url = cfg["ollama"]["url"].replace("/api/generate", "")
    try:
        r = requests.get(f"{base_url}/api/tags", timeout=5)
        models = [m["name"] for m in r.json().get("models", [])]
        console.print(f"[green]Ollama 연결 성공[/green] — 설치 모델: {', '.join(models) or '없음'}")
    except Exception as e:
        console.print(f"[red]Ollama 연결 실패[/red]: {e}")
        console.print("실행 방법: [bold]brew services start ollama[/bold]")


if __name__ == "__main__":
    cli()
