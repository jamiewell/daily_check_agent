# CLAUDE.md — daily_check_agent 프로젝트 인덱스

업무망 Grafana API 기반 AI LLM 운영지원 에이전트 개발 프로젝트.

## 문서 구조

| 파일 | 내용 |
|------|------|
| [CLAUDE_1_인프라구축.md](CLAUDE_1_인프라구축.md) | AWS 인프라 구성, EC2/RDS/ALB 운영, Terraform 백업 |
| [CLAUDE_2_모니터링스택_설치및연동.md](CLAUDE_2_모니터링스택_설치및연동.md) | Grafana / Alloy / Loki / Prometheus 설치 및 로컬 PC 연동 |
| [CLAUDE_3_일일점검에이전트_개발.md](CLAUDE_3_일일점검에이전트_개발.md) | 에이전트 개발 계획, Grafana API 목록, LLM 연동, 폐쇄망 반입 |

## 참조 문서

| 파일 | 내용 |
|------|------|
| [그라파나_api_분석.md](그라파나_api_분석.md) | Grafana API 상세 분석 (SQR292~328, PromQL, 파싱 코드) |
| [금융시스템_일일점검_에이전트_개발.md](금융시스템_일일점검_에이전트_개발.md) | 에이전트 개발 계획서 |
| [폐쇄망_에이전트_개발_api.md](폐쇄망_에이전트_개발_api.md) | 폐쇄망 환경 개발 가이드 |
| [AWS_EC2_운영_자동화_가이드.md](AWS_EC2_운영_자동화_가이드.md) | EC2 기동/중지/헬스체크 CLI 가이드 |
| [terraform-backup/](terraform-backup/) | 인프라 전체 Terraform 코드 |

## 빠른 참조

- **AWS 계정:** `locosalsa12` (503561457955) / `cotedazure12` (962088872927)
- **주요 서버:** hjcode-server (i-01202fdc8fb237804, us-east-1c, Ubuntu 24.04)
- **Grafana 엔드포인트:** `POST https://grafana.shinhancard.com:3000/api/ds/query`
- **GitHub:** `jamiewell/daily_check_agent` (private)
