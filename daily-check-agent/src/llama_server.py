"""llama.cpp 서버 프로세스 관리."""

import subprocess
import sys
import time
from pathlib import Path

import requests


def resource_path(relative: str) -> Path:
    """frozen exe 와 개발 환경 모두에서 올바른 절대 경로 반환."""
    if getattr(sys, 'frozen', False):
        # PyInstaller 빌드: 실행 파일 옆 디렉토리 기준
        base = Path(sys.executable).parent
    else:
        # 개발 환경: 프로젝트 루트 기준 (src/ 의 부모)
        base = Path(__file__).resolve().parent.parent
    return base / relative


def _server_exe() -> Path:
    name = "llama-server.exe" if sys.platform == "win32" else "llama-server"
    return resource_path(f"runtime/{name}")


def start(port: int = 8080, model_file: str = "runtime/models/qwen3-0.6b-q4_k_m.gguf",
          context_size: int = 2048, threads: int = 4) -> subprocess.Popen:
    """llama-server 를 기동하고 프로세스 객체를 반환한다. 60초 안에 서버가 뜨지 않으면 예외."""
    server_path = _server_exe()
    model_path  = resource_path(model_file)

    if not server_path.exists():
        raise FileNotFoundError(f"llama-server 바이너리 없음: {server_path}")
    if not model_path.exists():
        raise FileNotFoundError(f"모델 파일 없음: {model_path}")

    cmd = [
        str(server_path),
        "-m",     str(model_path),
        "--host", "127.0.0.1",
        "--port", str(port),
        "-c",     str(context_size),
        "-t",     str(threads),
    ]

    # Windows 에서는 별도 콘솔 창, 그 외에는 백그라운드 실행
    kwargs = {}
    if sys.platform == "win32":
        kwargs["creationflags"] = subprocess.CREATE_NEW_CONSOLE
    else:
        kwargs["stdout"] = subprocess.DEVNULL
        kwargs["stderr"] = subprocess.DEVNULL

    proc = subprocess.Popen(cmd, **kwargs)

    health_url = f"http://127.0.0.1:{port}/health"
    for _ in range(60):
        try:
            r = requests.get(health_url, timeout=1)
            if r.status_code in (200, 503):  # 503 = 모델 로딩 중 (정상)
                return proc
        except Exception:
            pass
        time.sleep(1)

    proc.terminate()
    raise RuntimeError("llama.cpp 서버가 60초 내에 시작되지 않았습니다.")


def stop(proc: subprocess.Popen) -> None:
    if proc and proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
