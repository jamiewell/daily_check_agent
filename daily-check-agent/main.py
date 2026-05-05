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
        path = save_report(summary, "(LLM 분석 생략)", timestamp, cfg["reports"]["output_dir"])
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

    console.print("\n[bold]AI 분석 중... (Ollama/Qwen3)[/bold]")
    llm = OllamaClient(
        url=cfg["ollama"]["url"],
        model=cfg["ollama"]["model"],
        temperature=cfg["ollama"]["temperature"],
        num_predict=cfg["ollama"]["num_predict"],
    )
    analysis = llm.analyze(summary)
    print_llm_analysis(analysis)

    if save:
        path = save_report(summary, analysis, timestamp, cfg["reports"]["output_dir"])
        console.print(f"\n[dim]리포트 저장됨: {path}[/dim]")


@cli.command()
@click.pass_context
def chat(ctx):
    """메트릭 로드 후 AI와 대화형 분석 (멀티턴 채팅)"""
    cfg = ctx.obj["cfg"]
    sample_dir = _resolve_sample_dir(cfg, ctx.obj["config_path"])
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    console.print("[bold]데이터 로딩 중...[/bold]")
    raw = load_all(sample_dir)
    summary = summarize(raw, cfg["thresholds"])

    print_summary(summary, timestamp)

    llm = OllamaClient(
        url=cfg["ollama"]["url"],
        model=cfg["ollama"]["model"],
        temperature=cfg["ollama"]["temperature"],
        num_predict=cfg["ollama"]["num_predict"],
    )

    # 시스템 메시지에 현재 메트릭 데이터 주입
    messages = [
        {"role": "system", "content": llm.build_system_message(summary)},
    ]

    # 첫 인사 — AI가 먼저 요약 분석 제공
    console.print("\n[bold]AI 초기 분석 중...[/bold]")
    messages.append({
        "role": "user",
        "content": "현재 서버 상태를 간략히 요약하고 주의사항을 알려줘."
    })
    first_reply = llm.chat(messages)
    messages.append({"role": "assistant", "content": first_reply})
    print_llm_analysis(first_reply)

    console.print("[dim]─── 대화를 시작하세요. 종료: [bold]exit[/bold] 또는 [bold]quit[/bold] ───[/dim]\n")

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

        messages.append({"role": "user", "content": user_input})
        console.print("[dim]AI 응답 중...[/dim]")
        reply = llm.chat(messages)
        messages.append({"role": "assistant", "content": reply})
        print_llm_analysis(reply)


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
