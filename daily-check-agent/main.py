#!/usr/bin/env python3
"""Daily Check Agent — CLI entry point."""

import os
import sys
from datetime import datetime

import click
import yaml

# Allow running from project root without installing package (dev mode only)
# PyInstaller frozen builds handle sys.path automatically via bundled modules
if not getattr(sys, 'frozen', False):
    sys.path.insert(0, os.path.dirname(__file__))

from src.data_loader import load_all
from src.preprocessor import summarize
from src.llm_client import OllamaClient, LlamaCppClient
from src.reporter import console, print_summary, print_comparison, print_llm_analysis, save_report
from src.comparator import compare as do_compare, comparison_text
from src import debug_logger as dbg
from src import llama_server

# exe 더블클릭(인자 없음) 시 analyze 모드 자동 실행
if getattr(sys, 'frozen', False) and len(sys.argv) == 1:
    sys.argv.append('analyze')


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
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    console.print("[bold]데이터 로딩 중...[/bold]")
    raw = load_all(sample_dir)
    summary = summarize(raw, cfg["thresholds"])
    print_summary(summary, timestamp)

    # 전일 비교
    summary_yd  = _load_yesterday(cfg, ctx.obj["config_path"], cfg["thresholds"])
    comparison  = do_compare(summary, summary_yd) if summary_yd else None
    if comparison:
        print_comparison(comparison)
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
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

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
            print_comparison(comparison)

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


CHECK_KEYWORDS  = ("일일점검", "점검", "서버 점검", "check", "분석 시작", "점검 시작")
REPORT_KEYWORDS = ("리포트 만들어", "리포트 생성", "report 만들어", "report 생성", "리포트 저장")


def _is_check_request(text: str) -> bool:
    return any(kw in text for kw in CHECK_KEYWORDS)


def _is_report_request(text: str) -> bool:
    return any(kw in text for kw in REPORT_KEYWORDS)


def _build_check_context(summary: dict, comparison=None) -> str:
    import json
    from src.comparator import comparison_text as make_comparison_text
    servers_text = json.dumps(summary, ensure_ascii=False, indent=2)
    cmp = make_comparison_text(comparison) if comparison else "(전일 데이터 없음)"
    return (
        f"아래 서버 점검 데이터를 분석해줘.\n\n"
        f"[서버 메트릭]\n{servers_text}\n\n"
        f"[전일 대비]\n{cmp}\n\n"
        f"점검 결과를 요약하고 주의사항을 알려줘."
    )


@cli.command()
@click.pass_context
def chat(ctx):
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
        console.print("[dim]'일일점검' 또는 '점검' 입력 시 서버 점검 | '리포트 만들어줘' 입력 시 파일 저장 | 종료: exit[/dim]\n")

        # 마지막 점검 결과 — 리포트 요청 시 재사용
        last_summary    = None
        last_comparison = None
        last_analysis   = ""
        last_timestamp  = ""

        while True:
            try:
                user_input = input("You > ").strip()
            except (EOFError, KeyboardInterrupt):
                console.print("\n[dim]대화 종료.[/dim]")
                break

            if not user_input:
                continue
            if user_input.lower() in ("exit", "quit", "종료", "q"):
                console.print("[dim]대화 종료.[/dim]")
                break

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
                last_timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                console.print("\n[bold]데이터 로딩 중...[/bold]")
                raw = load_all(sample_dir)
                last_summary = summarize(raw, cfg["thresholds"])
                print_summary(last_summary, last_timestamp)

                summary_yd = _load_yesterday(cfg, ctx.obj["config_path"], cfg["thresholds"])
                last_comparison = do_compare(last_summary, summary_yd) if summary_yd else None
                if last_comparison:
                    print_comparison(last_comparison)
                else:
                    console.print("[dim]전일 데이터 없음 — 비교 생략[/dim]")

                messages.append({"role": "user", "content": _build_check_context(last_summary, last_comparison)})
                with console.status("[bold]AI 점검 분석 중...[/bold]", spinner="dots"):
                    result = llm.chat(messages)
                _print_llm_status(result)
                last_analysis = str(result)
                messages.append({"role": "assistant", "content": last_analysis})
                print_llm_analysis(last_analysis)
                console.print("[dim]리포트를 저장하려면 '리포트 만들어줘'라고 입력하세요.[/dim]\n")
                continue

            # 일반 대화
            messages.append({"role": "user", "content": user_input})
            with console.status("[bold]AI 응답 중...[/bold]", spinner="dots"):
                result = llm.chat(messages)
            _print_llm_status(result)
            messages.append({"role": "assistant", "content": str(result)})
            print_llm_analysis(str(result))

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
