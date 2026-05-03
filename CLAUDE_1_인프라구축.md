# CLAUDE 1 — AWS 인프라 구축 가이드

## 개요

AWS 계정 `503561457955` (프로필: `locosalsa12`) 기반 us-east-1 인프라 구성 및 운영 자동화.

---

## AWS 계정 정보

| 프로필 | 계정 ID | 리전 | 용도 |
|--------|---------|------|------|
| `locosalsa12` | 503561457955 | us-east-1 | 메인 인프라 |
| `cotedazure12` / `codedazure12` | 962088872927 | ap-northeast-2 | 서브 계정 |

---

## 현재 인프라 구성 (us-east-1)

### VPC
- VPC CIDR: `172.31.0.0/16`
- 퍼블릭 서브넷 6개 (us-east-1a ~ 1f)
- Internet Gateway 연결, NAT Gateway 없음

### EC2 인스턴스

| Name | Instance ID | Type | OS | AZ | 상태 |
|------|-------------|------|----|----|------|
| hjcode-server | i-01202fdc8fb237804 | t3.small | Ubuntu 24.04 | us-east-1c | stopped |
| trfc-optr-kafka-broker | i-007f11d5981a81732 | t3.small | Ubuntu 24.04 | us-east-1c | stopped |
| trfc-optr-kafka-broker-01 | i-0b424471497c4420a | t4g.small | Ubuntu 24.04 ARM | us-east-1c | stopped |
| K6-server | i-005a516de9c3712f8 | t3a.small | Ubuntu 24.04 | us-east-1a | stopped |
| kafka-server | i-0e28ae3b19ddc359e | t2.medium | - | us-east-1b | stopped |

### RDS
- 식별자: `hjcode-database`
- Engine: MySQL 8.0.44
- 인스턴스: db.t4g.micro
- 스토리지: 20GB gp2 (최대 1TB 자동 확장)
- 엔드포인트: `hjcode-database.cm7weks4ul39.us-east-1.rds.amazonaws.com:3306`
- 암호화: 활성화, Public: 허용

### ALB
- 이름: `hjcode-alb`
- DNS: `hjcode-alb-1849878305.us-east-1.elb.amazonaws.com`
- 타입: internet-facing, HTTP:80
- 타겟 그룹: `hjcode-server-target-group` → hjcode-server:80 (헬스체크: `/health`)
- AZ: 6개 전체 (월 ~$15.66 고정 비용 발생)

### IAM
- Role: `cloudwatchagent-role`
  - CloudWatchAgentServerPolicy
  - AmazonSSMManagedInstanceCore

---

## EC2 운영 CLI

### 인스턴스 시작/중지

```bash
# 시작
aws ec2 start-instances --instance-ids i-01202fdc8fb237804 \
  --profile locosalsa12 --region us-east-1

# running 대기
aws ec2 wait instance-running --instance-ids i-01202fdc8fb237804 \
  --profile locosalsa12 --region us-east-1

# 중지
aws ec2 stop-instances --instance-ids i-01202fdc8fb237804 \
  --profile locosalsa12 --region us-east-1
```

### 헬스체크

```bash
aws ec2 describe-instance-status \
  --instance-ids i-01202fdc8fb237804 \
  --profile locosalsa12 --region us-east-1 --output table
```

### SSH 접속 (키페어 없는 서버 — EC2 Instance Connect)

```bash
# 1. 임시 키 생성
ssh-keygen -t rsa -b 2048 -f /tmp/hjcode-temp-key -N ""

# 2. 공개키 주입 (60초 유효)
aws ec2-instance-connect send-ssh-public-key \
  --instance-id i-01202fdc8fb237804 \
  --instance-os-user ubuntu \
  --ssh-public-key file:///tmp/hjcode-temp-key.pub \
  --availability-zone us-east-1c \
  --profile locosalsa12 --region us-east-1

# 3. 60초 이내 SSH 접속
ssh -i /tmp/hjcode-temp-key -o StrictHostKeyChecking=no ubuntu@<PUBLIC_IP>
```

---

## SES 이메일 설정

- 리전: us-east-1
- 발신: `prorsumhj@gmail.com` (인증 완료)
- 수신: `fast2furious@naver.com` (인증 완료)
- 샌드박스 모드: 발신/수신 모두 사전 인증 필요

```bash
# 이메일 발송
aws ses send-email \
  --profile locosalsa12 --region us-east-1 \
  --from prorsumhj@gmail.com \
  --destination "ToAddresses=fast2furious@naver.com" \
  --message '{"Subject":{"Data":"제목","Charset":"UTF-8"},"Body":{"Text":{"Data":"본문","Charset":"UTF-8"}}}'
```

---

## Terraform 백업

현재 인프라 전체를 Terraform 코드로 백업. 위치: `terraform-backup/`

```
terraform-backup/
├── main.tf             # provider (profile: locosalsa12)
├── variables.tf        # region, rds_password, allowed_ssh_cidr
├── vpc.tf              # VPC, 서브넷 6개, IGW, 라우팅
├── security_groups.tf  # SG 7개
├── iam.tf              # cloudwatchagent-role
├── ec2.tf              # EC2 5대
├── rds.tf              # MySQL RDS + subnet group
├── alb.tf              # ALB + target group + listener
└── outputs.tf
```

```bash
cd terraform-backup
cp terraform.tfvars.example terraform.tfvars
# rds_password 입력 후
terraform init && terraform plan && terraform apply
```

---

## 비용 현황 (2026년 4월 기준)

| 서비스 | 월 비용 | 비고 |
|--------|---------|------|
| ALB | $15.66 | 6개 AZ 상시 운영 중 — 절감 검토 필요 |
| RDS | $13.36 | hjcode-database |
| VPC | $6.98 | Elastic IP 등 |
| EC2 | $3.10 | EBS 스토리지 |
| **합계** | **$43.14** | 세금 포함 |
