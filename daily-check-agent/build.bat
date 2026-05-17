@echo off
REM build.bat — daily-check-agent PyInstaller 빌드 스크립트 (Windows)
REM
REM 사용법:
REM   build.bat
REM
REM 결과물: dist\daily-check-agent\
REM 패키지:  dist\daily-check-agent.zip  (폐쇄망 전달용)

setlocal enabledelayedexpansion

set SCRIPT_DIR=%~dp0
set VENV_DIR=%SCRIPT_DIR%.venv
set DIST_DIR=%SCRIPT_DIR%dist\daily-check-agent

REM ── 1. 가상환경 활성화 ──────────────────────────────────────────────
echo [1/5] 가상환경 활성화
if not exist "%VENV_DIR%" (
    echo .venv 없음 -^> python -m venv .venv 실행
    python -m venv "%VENV_DIR%"
)
call "%VENV_DIR%\Scripts\activate.bat"

REM ── 2. 의존성 설치 ──────────────────────────────────────────────────
echo [2/5] 패키지 설치
pip install -q -r "%SCRIPT_DIR%requirements.txt"
pip install -q pyinstaller

REM ── 3. PyInstaller 빌드 ─────────────────────────────────────────────
echo [3/5] PyInstaller 빌드
cd /d "%SCRIPT_DIR%"
pyinstaller daily_check_agent.spec --clean --noconfirm
if errorlevel 1 (
    echo [오류] PyInstaller 빌드 실패
    exit /b 1
)

REM ── 4. 운영 파일 복사 ───────────────────────────────────────────────
echo [4/5] 운영 파일 복사

copy /Y "%SCRIPT_DIR%config.yaml" "%DIST_DIR%\config.yaml"

if exist "%DIST_DIR%\templates" rmdir /s /q "%DIST_DIR%\templates"
xcopy /e /i /q "%SCRIPT_DIR%templates" "%DIST_DIR%\templates"

if exist "%DIST_DIR%\sample_data" rmdir /s /q "%DIST_DIR%\sample_data"
mkdir "%DIST_DIR%\sample_data\today"
mkdir "%DIST_DIR%\sample_data\yesterday"
copy /Y "%SCRIPT_DIR%sample_data\today\*.json"    "%DIST_DIR%\sample_data\today\"
copy /Y "%SCRIPT_DIR%sample_data\yesterday\*.json" "%DIST_DIR%\sample_data\yesterday\"

if not exist "%DIST_DIR%\reports" mkdir "%DIST_DIR%\reports"

REM runtime/ (llama.cpp 모드용 — 폴더가 있을 때만 복사)
if exist "%SCRIPT_DIR%runtime" (
    echo   runtime\ 폴더 감지 -^> 복사 (llama.cpp 모드)
    if exist "%DIST_DIR%\runtime" rmdir /s /q "%DIST_DIR%\runtime"
    xcopy /e /i /q "%SCRIPT_DIR%runtime" "%DIST_DIR%\runtime"
)

REM ── 5. ZIP 패키지 생성 (PowerShell 사용) ────────────────────────────
echo [5/5] ZIP 패키지 생성
cd /d "%SCRIPT_DIR%dist"
if exist daily-check-agent.zip del daily-check-agent.zip
powershell -Command "Compress-Archive -Path 'daily-check-agent' -DestinationPath 'daily-check-agent.zip' -Force"
echo   -^> dist\daily-check-agent.zip

echo.
echo ======================================
echo 빌드 완료: dist\daily-check-agent\
echo.
echo 실행 방법:
echo   cd dist\daily-check-agent
echo   daily-check-agent.exe status
echo   daily-check-agent.exe check
echo   daily-check-agent.exe analyze
echo ======================================

endlocal
