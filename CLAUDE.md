# CLAUDE.md — daily_check_agent 프로젝트

## 프로젝트 개요

금융시스템(업무망) Grafana API 기반 AI LLM 운영지원 에이전트 개발 프로젝트.
폐쇄망 환경에서의 AI 에이전트 구축 및 AWS 인프라 자동화를 다룬다.

## AWS 계정 정보

| 프로필 | 계정 ID | 용도 |
|--------|---------|------|
| `locosalsa12` | 503561457955 | 메인 인프라 계정 (us-east-1) |
| `cotedazure12` / `codedazure12` | 962088872927 | 서브 계정 (ap-northeast-2) |

## 주요 인프라 (503561457955 / us-east-1)

- **hjcode-server**: EC2 t3.small, Ubuntu 24.04, us-east-1c
  - IAM: cloudwatchagent-role (CloudWatch + SSM)
  - 모니터링 스택 설치됨: Grafana v13.0.1, Alloy v1.15.1, Loki v3.7.1, Prometheus v3.11.2
- **hjcode-alb**: Application Load Balancer (internet-facing, HTTP:80)
- **hjcode-database**: RDS MySQL 8.0, db.t4g.micro, us-east-1c
- **Kafka 서버들**: trfc-optr-kafka-broker, trfc-optr-kafka-broker-01, kafka-server

## SSH 접속 방법 (키페어 없는 서버)

```bash
# 임시 키 생성 및 EC2 Instance Connect로 접속
ssh-keygen -t rsa -b 2048 -f /tmp/hjcode-temp-key -N ""
aws ec2-instance-connect send-ssh-public-key \
  --instance-id i-01202fdc8fb237804 \
  --instance-os-user ubuntu \
  --ssh-public-key file:///tmp/hjcode-temp-key.pub \
  --availability-zone us-east-1c \
  --profile locosalsa12 --region us-east-1
ssh -i /tmp/hjcode-temp-key -o StrictHostKeyChecking=no ubuntu@<PUBLIC_IP>
```

## SES 이메일 설정 (locosalsa12)

- 발신: prorsumhj@gmail.com (인증 완료)
- 수신: fast2furious@naver.com (인증 완료)
- 리전: us-east-1

## GitHub 연동

- 리포지토리: `jamiewell/daily_check_agent` (private)
- 브랜치: `main`
- 로컬 경로: `/Users/hyojae/Documents/GrafanaAPI`

## 프로젝트 문서

| 파일 | 내용 |
|------|------|
| `그라파나_api_분석.md` | Grafana API 엔드포인트 분석 (shinhancard 업무망) |
| `금융시스템_일일점검_에이전트_개발.md` | AI LLM 운영지원 에이전트 개발 계획서 |
| `폐쇄망_에이전트_개발_api.md` | 폐쇄망 환경 AI 에이전트 개발 가이드 |
| `AWS_EC2_운영_자동화_가이드.md` | EC2 기동/중지/헬스체크/SES 자동화 CLI 가이드 |
| `terraform-backup/` | 현 인프라 전체 Terraform 코드 백업 |
