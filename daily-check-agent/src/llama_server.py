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
          context_size: int = 2048, threads: int = 4,
          server_exe: str = None, lib_dir: str = None) -> subprocess.Popen:
    """llama-server 를 기동하고 프로세스 객체를 반환한다. 60초 안에 서버가 뜨지 않으면 예외.

    server_exe: 절대 경로 지정 시 해당 바이너리 사용 (개발 환경용)
    lib_dir:    dylib 검색 경로 (macOS, 절대 경로 지정 시 DYLD_LIBRARY_PATH 설정)
    """
    # 바이너리 경로: 절대 경로 우선, 없으면 resource_path 기반
    if server_exe:
        server_path = Path(server_exe).expanduser().resolve()
    else:
        server_path = _server_exe()

    # 모델 경로: 절대 경로 우선, 없으면 resource_path 기반
    model_path_obj = Path(model_file).expanduser()
    if model_path_obj.is_absolute() or str(model_file).startswith("~"):
        model_path = model_path_obj.expanduser().resolve()
    else:
        model_path = resource_path(model_file)

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
        "-ngl",   "99",       # Metal/CUDA GPU 가속 (CPU-only 환경에서는 무시됨)
    ]

    # Windows 에서는 별도 콘솔 창, 그 외에는 백그라운드 실행
    kwargs: dict = {}
    env = None
    if sys.platform == "win32":
        kwargs["creationflags"] = subprocess.CREATE_NEW_CONSOLE
    else:
        kwargs["stdout"] = subprocess.DEVNULL
        kwargs["stderr"] = subprocess.DEVNULL
        # macOS: dylib 검색 경로 설정
        if lib_dir:
            import os
            env = os.environ.copy()
            env["DYLD_LIBRARY_PATH"] = str(Path(lib_dir).expanduser().resolve())
    if env:
        kwargs["env"] = env

    proc = subprocess.Popen(cmd, **kwargs)

    health_url = f"http://127.0.0.1:{port}/health"
    for _ in range(120):   # 최대 120초 대기 (대형 모델 로딩 고려)
        try:
            r = requests.get(health_url, timeout=2)
            if r.status_code == 200:   # 200 = 완전히 준비됨 (503은 아직 로딩 중)
                return proc
        except Exception:
            pass
        time.sleep(1)

    proc.terminate()
    raise RuntimeError("llama.cpp 서버가 120초 내에 준비되지 않았습니다.")


def stop(proc: subprocess.Popen) -> None:
    if proc and proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
