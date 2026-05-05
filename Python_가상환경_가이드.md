# Python 설치 및 가상환경 가이드

---

## 1. Python 설치

### Windows

#### 공식 설치 파일로 설치 (권장)

1. [https://www.python.org/downloads/](https://www.python.org/downloads/) 접속
2. `Download Python 3.12.x` 버튼 클릭 (Windows 64-bit installer)
3. 설치 시 **반드시** 아래 옵션 체크:
   - ✅ `Add python.exe to PATH`
4. `Install Now` 클릭

#### 설치 확인

```powershell
python --version
# Python 3.12.x

pip --version
# pip 26.x.x from ...
```

> **주의:** 설치 후 PATH 반영을 위해 터미널(PowerShell/CMD)을 새로 열어야 합니다.

---

### macOS

#### Homebrew로 설치 (권장)

```bash
# Homebrew 없으면 먼저 설치
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"

# Python 설치
brew install python@3.12

# 설치 확인
python3.12 --version
# Python 3.12.x
```

#### 공식 설치 파일로 설치

1. [https://www.python.org/downloads/macos/](https://www.python.org/downloads/macos/) 접속
2. `macOS 64-bit universal2 installer` 다운로드
3. `.pkg` 파일 실행 후 안내에 따라 설치

#### 설치 확인

```bash
python3 --version
pip3 --version
```

---

## 2. 가상환경(venv)이란?

### 개념

Python 프로젝트마다 **독립된 패키지 설치 공간**을 분리하는 기능입니다.

```
[시스템 Python]
    │
    ├── 프로젝트 A용 venv ─── requests 2.28, click 7.x
    ├── 프로젝트 B용 venv ─── requests 2.31, click 8.x
    └── 프로젝트 C용 venv ─── requests 2.33, click 8.x
```

### 왜 필요한가?

| 상황 | 가상환경 없을 때 문제 | 가상환경 있을 때 |
|------|----------------------|-----------------|
| 프로젝트 A는 `requests 2.28` 필요 | 시스템 전체 버전 고정 → 충돌 | 각 프로젝트 독립 설치 |
| 프로젝트 B는 `requests 2.33` 필요 | 하나를 올리면 다른 게 깨짐 | 서로 영향 없음 |
| 팀원에게 환경 전달 | "내 PC에선 됩니다" 문제 발생 | `requirements.txt`로 동일 재현 |
| 서버 배포 | 시스템 Python 오염 위험 | 격리된 환경 그대로 배포 |

---

## 3. 가상환경 설치 및 구성

### 생성

가상환경은 프로젝트 폴더 안에 만드는 것이 표준입니다.

**Windows (PowerShell)**
```powershell
cd C:\Users\사용자명\프로젝트폴더
python -m venv .venv
```

**macOS**
```bash
cd ~/프로젝트폴더
python3 -m venv .venv
```

> `.venv`는 관례적인 이름입니다. `venv`, `env` 등 원하는 이름 사용 가능.

---

### 활성화 / 비활성화

가상환경을 사용하려면 반드시 **활성화**해야 합니다.

#### Windows

```powershell
# 활성화
.venv\Scripts\activate

# 비활성화
deactivate
```

> PowerShell에서 실행 오류 시 아래 명령어 한 번 실행 후 재시도:
> ```powershell
> Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
> ```

#### macOS

```bash
# 활성화
source .venv/bin/activate

# 비활성화
deactivate
```

#### 활성화 확인

활성화되면 터미널 프롬프트 앞에 `(.venv)`가 표시됩니다.

```bash
(.venv) user@MacBook 프로젝트폴더 %
```

---

### 패키지 설치

활성화 상태에서 `pip`으로 설치하면 가상환경 안에만 설치됩니다.

```bash
pip install requests click rich pyyaml
```

---

## 4. requirements.txt — 환경 공유

### 현재 설치된 패키지 저장

```bash
pip freeze > requirements.txt
```

`requirements.txt` 예시:
```
click==8.3.3
requests==2.33.1
rich==15.0.0
PyYAML==6.0.3
```

### 다른 PC에서 동일 환경 재현

```bash
# 1. 가상환경 생성
python -m venv .venv          # Windows
python3 -m venv .venv         # macOS

# 2. 활성화
.venv\Scripts\activate        # Windows
source .venv/bin/activate     # macOS

# 3. 패키지 일괄 설치
pip install -r requirements.txt
```

---

## 5. 가상환경 관리

### 폴더 구조 (이 프로젝트 기준)

```
daily-check-agent/
├── .venv/              ← 가상환경 (git에 올리지 않음)
├── requirements.txt    ← 패키지 목록 (git에 올림)
├── .gitignore          ← .venv/ 제외 설정
├── main.py
└── src/
```

### .gitignore 설정 (필수)

가상환경 폴더는 용량이 크고 OS마다 달라서 git에 올리지 않습니다.

```
# .gitignore
.venv/
__pycache__/
*.pyc
```

### 삭제

가상환경은 단순 폴더이므로 폴더째 삭제하면 됩니다.

```bash
rm -rf .venv          # macOS
rd /s /q .venv        # Windows
```

삭제 후 다시 생성하면 깨끗하게 초기화됩니다.

---

## 6. 이 프로젝트(daily-check-agent) 세팅 순서

```bash
# 1. 저장소 복제
git clone https://github.com/jamiewell/daily_check_agent.git
cd daily_check_agent/daily-check-agent

# 2. 가상환경 생성
python -m venv .venv          # Windows
python3 -m venv .venv         # macOS

# 3. 활성화
.venv\Scripts\activate        # Windows
source .venv/bin/activate     # macOS

# 4. 패키지 설치
pip install -r requirements.txt

# 5. 실행 확인
python main.py status
python main.py check
python main.py analyze
python main.py chat
```

---

## 7. 자주 쓰는 명령어 요약

| 작업 | Windows | macOS |
|------|---------|-------|
| 가상환경 생성 | `python -m venv .venv` | `python3 -m venv .venv` |
| 활성화 | `.venv\Scripts\activate` | `source .venv/bin/activate` |
| 비활성화 | `deactivate` | `deactivate` |
| 패키지 설치 | `pip install 패키지명` | `pip install 패키지명` |
| 패키지 목록 저장 | `pip freeze > requirements.txt` | `pip freeze > requirements.txt` |
| 패키지 일괄 설치 | `pip install -r requirements.txt` | `pip install -r requirements.txt` |
| 설치된 패키지 목록 | `pip list` | `pip list` |
| 패키지 삭제 | `pip uninstall 패키지명` | `pip uninstall 패키지명` |
| 가상환경 삭제 | `rd /s /q .venv` | `rm -rf .venv` |
