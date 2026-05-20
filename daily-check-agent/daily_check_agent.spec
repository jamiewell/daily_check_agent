# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec — daily-check-agent

빌드 방법:
    source .venv/bin/activate
    pyinstaller daily_check_agent.spec

출력: dist/daily-check-agent/
  ├── daily-check-agent      ← 실행 파일 (Windows: .exe)
  ├── _internal/             ← Python 런타임·라이브러리 (건드리지 말 것)
  ├── config.yaml            ← build.sh 이 복사 (사용자 편집)
  ├── templates/             ← build.sh 이 복사
  ├── sample_data/           ← build.sh 이 복사
  ├── runtime/               ← build.sh 이 복사 (llama_cpp 모드 시)
  │   ├── llama-server.exe   ←   llama.cpp 바이너리 (별도 준비)
  │   └── models/
  │       └── *.gguf         ←   Qwen3 모델 파일 (별도 준비)
  └── reports/               ← 실행 시 자동 생성

주의: templates/, sample_data/, config.yaml, runtime/ 은 datas 로 번들하지 않음.
      build.sh / build.bat 이 dist 폴더로 직접 복사한다.
      사용자는 dist/daily-check-agent/ 폴더 안에서 실행해야 한다.
"""

# runtime/ 은 build.bat 이 dist/ 로 직접 복사 — spec 에서 번들하지 않음
# (GGUF 모델 파일이 수백MB 이므로 PyInstaller 번들에서 제외해야 빌드 안정)

a = Analysis(
    ['main.py'],
    pathex=['.'],
    binaries=[],
    datas=[],
    hiddenimports=[
        # PyYAML (C 확장 모듈 포함)
        'yaml',
        '_yaml',
        # Rich (동적 import 가 많아 명시 필요)
        'rich',
        'rich.box',
        'rich.console',
        'rich.live',
        'rich.markup',
        'rich.highlighter',
        'rich.panel',
        'rich.progress',
        'rich.spinner',
        'rich.status',
        'rich.table',
        'rich.text',
        'rich.theme',
        # Requests / 인증서
        'requests',
        'certifi',
        'charset_normalizer',
        'urllib3',
        'idna',
        # Click
        'click',
        # 내부 모듈 (src.*)
        'src',
        'src.comparator',
        'src.data_loader',
        'src.debug_logger',
        'src.grafana_client',
        'src.llama_server',
        'src.llm_client',
        'src.preprocessor',
        'src.process_baseline',
        'src.reporter',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # 사용하지 않는 대형 패키지 제외
        'tkinter',
        'matplotlib',
        'numpy',
        'pandas',
        'scipy',
        'PIL',
        'cv2',
    ],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,       # one-dir 모드 (one-file 보다 실행 빠름)
    name='daily-check-agent',
    debug=False,
    strip=False,
    upx=False,                   # UPX 압축 비활성 (폐쇄망 AV 오탐 방지)
    console=True,
    argv_emulation=False,        # macOS 전용 옵션 (필요 없음)
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name='daily-check-agent',
)
