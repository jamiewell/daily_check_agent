#!/usr/bin/env python3
"""Daily Check Agent — CLI entry point."""

import os
import sys
from datetime import datetime

import click
import yaml

# Allow running from project root without installing package
sys.path.insert(0, os.path.dirname(__file__))

from src.data_loader import load_all
from src.preprocessor import summarize
from src.llm_client import OllamaClient
from src.reporter import console, print_summary, print_llm_analysis, save_report


def _load_config(config_path: str) -> dict:
    with open(config_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def _resolve_sample_dir(cfg: dict, config_path: str) -> str:
    base = os.path.dirname(os.path.abspath(config_path))
    return os.path.join(base, cfg["data"]["sample_dir"])


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


def _make_llm(cfg: dict, config_path: str) -> OllamaClient:
    tpl = _resolve_templates(cfg, config_path)
    return OllamaClient(
        url=cfg["ollama"]["url"],
        model=cfg["ollama"]["model"],
        temperature=cfg["ollama"]["temperature"],
        num_predict=cfg["ollama"]["num_predict"],
        templates_dir=tpl["dir"],
        prompt_analyze_file=tpl["prompt_analyze"],
        prompt_system_file=tpl["prompt_system"],
    )


@click.group()
@click.option("--config", default="config.yaml", show_default=True, help="설정 파일 경로")
@click.pass_context
def cli(ctx, config):
    """금융시스템 일일점검 AI 에이전트"""
    ctx.ensure_object(dict)
    cfg = _load_config(config)
    ctx.obj["cfg"] = cfg
    ctx.obj["config_path"] = config


@cli.command()
@click.option("--save/--no-save", default=True, show_default=True, help="리포트 파일 저장 여부")
@click.pass_context
def check(ctx, save):
    """메트릭 수집 + 요약 테이블 출력 (LLM 분석 없음)"""
    cfg = ctx.obj["cfg"]
    sample_dir = _resolve_sample_dir(cfg, ctx.obj["config_path"])
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    console.print("[bold]데이터 로딩 중...[/bold]")
    raw = load_all(sample_dir)
    summary = summarize(raw, cfg["thresholds"])
    print_summary(summary, timestamp)

    if save:
        tpl = _resolve_templates(cfg, ctx.obj["config_path"])
        path = save_report(summary, "(LLM 분석 생략)", timestamp, cfg["reports"]["output_dir"], tpl["report"])
        console.print(f"\n[dim]리포트 저장됨: {path}[/dim]")


@cli.command()
@click.option("--save/--no-save", default=True, show_default=True, help="리포트 파일 저장 여부")
@click.pass_context
def analyze(ctx, save):
    """메트릭 수집 + AI 분석 (Ollama/Qwen3)"""
    cfg = ctx.obj["cfg"]
    sample_dir = _resolve_sample_dir(cfg, ctx.obj["config_path"])
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    console.print("[bold]데이터 로딩 중...[/bold]")
    raw = load_all(sample_dir)
    summary = summarize(raw, cfg["thresholds"])
    print_summary(summary, timestamp)

    tpl = _resolve_templates(cfg, ctx.obj["config_path"])
    llm = _make_llm(cfg, ctx.obj["config_path"])
    with console.status("[bold]Qwen3 분석 중...[/bold]", spinner="dots"):
        result = llm.analyze(summary)
    _print_llm_status(result)
    print_llm_analysis(str(result))

    if save:
        path = save_report(summary, str(result), timestamp, cfg["reports"]["output_dir"], tpl["report"])
        console.print(f"[dim]리포트 저장됨: {path}[/dim]")


CHECK_KEYWORDS = ("일일점검", "점검", "서버 점검", "check", "분석 시작", "점검 시작")


def _is_check_request(text: str) -> bool:
    return any(kw in text for kw in CHECK_KEYWORDS)


def _build_check_context(llm: OllamaClient, summary: dict) -> str:
    return (
        f"다음은 방금 수집한 서버 점검 데이터야. 이 데이터를 바탕으로 이후 질문에 답해줘.\n\n"
        f"{llm.build_system_message(summary)}\n\n"
        f"점검 결과를 간략히 요약하고 주의사항을 알려줘."
    )


@cli.command()
@click.pass_context
def chat(ctx):
    """대화형 AI 에이전트 — '일일점검' 키워드 입력 시 점검 실행"""
    cfg = ctx.obj["cfg"]
    sample_dir = _resolve_sample_dir(cfg, ctx.obj["config_path"])
    tpl = _resolve_templates(cfg, ctx.obj["config_path"])
    llm = _make_llm(cfg, ctx.obj["config_path"])

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
    console.print(
        f"[dim]모델: {cfg['ollama']['model']} │ "
        f"온도: {cfg['ollama']['temperature']} │ "
        f"최대 토큰: {cfg['ollama']['num_predict']}[/dim]"
    )
    console.print("[dim]'일일점검' 또는 '점검' 입력 시 서버 점검을 실행합니다. 종료: exit[/dim]\n")

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

        # 점검 키워드 감지
        if _is_check_request(user_input):
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            console.print("\n[bold]데이터 로딩 중...[/bold]")
            raw = load_all(sample_dir)
            summary = summarize(raw, cfg["thresholds"])
            print_summary(summary, timestamp)

            messages.append({"role": "user", "content": _build_check_context(llm, summary)})
            with console.status("[bold]Qwen3 점검 분석 중...[/bold]", spinner="dots"):
                result = llm.chat(messages)
            _print_llm_status(result)
            messages.append({"role": "assistant", "content": str(result)})
            print_llm_analysis(str(result))

            path = save_report(summary, str(result), timestamp, cfg["reports"]["output_dir"], tpl["report"])
            console.print(f"[dim]리포트 저장됨: {path}[/dim]\n")
            continue

        # 일반 대화
        messages.append({"role": "user", "content": user_input})
        with console.status("[bold]Qwen3 응답 중...[/bold]", spinner="dots"):
            result = llm.chat(messages)
        _print_llm_status(result)
        messages.append({"role": "assistant", "content": str(result)})
        print_llm_analysis(str(result))


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
