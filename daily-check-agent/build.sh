#!/usr/bin/env bash
# build.sh — daily-check-agent PyInstaller 빌드 스크립트
#
# 사용법:
#   chmod +x build.sh
#   ./build.sh
#
# 결과물: dist/daily-check-agent/
# 패키지:  dist/daily-check-agent.zip  (폐쇄망 전달용)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="$SCRIPT_DIR/.venv"
DIST_DIR="$SCRIPT_DIR/dist/daily-check-agent"

# ── 1. 가상환경 활성화 ────────────────────────────────────────────────
echo "[1/5] 가상환경 활성화"
if [[ ! -d "$VENV_DIR" ]]; then
    echo "  .venv 없음 → python3 -m venv .venv 실행"
    python3 -m venv "$VENV_DIR"
fi
# shellcheck source=/dev/null
source "$VENV_DIR/bin/activate"

# ── 2. 의존성 설치 ────────────────────────────────────────────────────
echo "[2/5] 패키지 설치"
pip install -q -r "$SCRIPT_DIR/requirements.txt"
pip install -q pyinstaller

# ── 3. PyInstaller 빌드 ───────────────────────────────────────────────
echo "[3/5] PyInstaller 빌드"
cd "$SCRIPT_DIR"
pyinstaller daily_check_agent.spec \
    --clean \
    --noconfirm

# ── 4. 운영 파일 복사 ─────────────────────────────────────────────────
echo "[4/5] 운영 파일 복사"

# config.yaml (사용자가 편집해야 하므로 dist 루트에 배치)
cp "$SCRIPT_DIR/config.yaml"  "$DIST_DIR/config.yaml"

# templates (LLM 프롬프트 / 리포트 양식)
rm -rf "$DIST_DIR/templates"
cp -r  "$SCRIPT_DIR/templates" "$DIST_DIR/templates"

# sample_data (today / yesterday 만 배포, extra_* 제외)
rm -rf "$DIST_DIR/sample_data"
mkdir -p "$DIST_DIR/sample_data/today" "$DIST_DIR/sample_data/yesterday"
cp "$SCRIPT_DIR/sample_data/today/"*.json    "$DIST_DIR/sample_data/today/"
cp "$SCRIPT_DIR/sample_data/yesterday/"*.json "$DIST_DIR/sample_data/yesterday/"

# runtime/ (llama.cpp 모드용 — 폴더가 있을 때만 복사)
if [[ -d "$SCRIPT_DIR/runtime" ]]; then
    echo "  runtime/ 폴더 감지 → 복사 (llama.cpp 모드)"
    rm -rf "$DIST_DIR/runtime"
    cp -r "$SCRIPT_DIR/runtime" "$DIST_DIR/runtime"
fi

# reports 폴더 (비어 있어도 생성)
mkdir -p "$DIST_DIR/reports"

# ── 5. ZIP 패키지 생성 ────────────────────────────────────────────────
echo "[5/5] ZIP 패키지 생성"
cd "$SCRIPT_DIR/dist"
ZIP_NAME="daily-check-agent.zip"
rm -f "$ZIP_NAME"
zip -r -q "$ZIP_NAME" daily-check-agent/
echo "  → dist/$ZIP_NAME"

echo ""
echo "======================================"
echo "빌드 완료: dist/daily-check-agent/"
echo ""
echo "실행 방법:"
echo "  cd dist/daily-check-agent"
echo "  # config.yaml 편집 (Grafana URL, 토큰 등)"
echo "  ./daily-check-agent status    # Ollama 연결 확인"
echo "  ./daily-check-agent check     # 메트릭 점검"
echo "  ./daily-check-agent analyze   # AI 분석"
echo "======================================"
