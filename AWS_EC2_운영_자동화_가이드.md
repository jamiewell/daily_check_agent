# AWS EC2 운영 자동화 가이드 (계정: 503561457955)

## 사전 준비

### 1. AWS CLI 프로필 확인
```bash
aws sts get-caller-identity --profile locosalsa12
```
```json
{
    "UserId": "503561457955",
    "Account": "503561457955",
    "Arn": "arn:aws:iam::503561457955:root"
}
```

### 2. SES 이메일 인증 (최초 1회)
```bash
# 발신자 인증
aws ses verify-email-identity \
  --email-address prorsumhj@gmail.com \
  --profile locosalsa12 \
  --region us-east-1

# 수신자 인증
aws ses verify-email-identity \
  --email-address fast2furious@naver.com \
  --profile locosalsa12 \
  --region us-east-1
```
> 각 이메일로 AWS 인증 메일 수신 → 링크 클릭 필요

### 3. IAM 역할에 SSM 정책 추가 (SSH 키 없는 서버 접속용)
```bash
aws iam attach-role-policy \
  --role-name cloudwatchagent-role \
  --policy-arn arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore \
  --profile locosalsa12
```

---

## EC2 인스턴스 기동

### 인스턴스 찾기 (리전 전체 검색)
```bash
for region in us-east-1 us-east-2 us-west-1 us-west-2 eu-west-1 eu-central-1 ap-northeast-1 ap-northeast-2 ap-southeast-1 ap-southeast-2; do
  result=$(aws ec2 describe-instances \
    --profile locosalsa12 \
    --region $region \
    --filters "Name=tag:Name,Values=hjcode-server" \
    --query 'Reservations[*].Instances[*].[InstanceId,State.Name,InstanceType]' \
    --output text 2>&1)
  if [ -n "$result" ]; then echo "[$region] $result"; fi
done
```
> 결과: `us-east-1` 리전에 `i-01202fdc8fb237804` (t3.small) 확인

### 인스턴스 시작
```bash
aws ec2 start-instances \
  --instance-ids i-01202fdc8fb237804 \
  --profile locosalsa12 \
  --region us-east-1
```

### running 상태 대기
```bash
aws ec2 wait instance-running \
  --instance-ids i-01202fdc8fb237804 \
  --profile locosalsa12 \
  --region us-east-1
```

---

## 헬스체크

### 인스턴스 상세 정보 조회
```bash
aws ec2 describe-instances \
  --instance-ids i-01202fdc8fb237804 \
  --profile locosalsa12 \
  --region us-east-1 \
  --query 'Reservations[0].Instances[0].{InstanceId:InstanceId,State:State.Name,Type:InstanceType,PublicIP:PublicIpAddress,PrivateIP:PrivateIpAddress,AZ:Placement.AvailabilityZone,LaunchTime:LaunchTime}' \
  --output table
```

### 시스템/인스턴스 상태 체크
```bash
aws ec2 describe-instance-status \
  --instance-ids i-01202fdc8fb237804 \
  --profile locosalsa12 \
  --region us-east-1 \
  --output table
```

**정상 상태 기준:**

| 항목 | 정상값 |
|------|--------|
| Instance State | running (code: 16) |
| Instance Status | ok |
| System Status | ok |
| EBS Status | ok |
| Reachability | passed |

---

## 헬스체크 결과 이메일 발송 (AWS SES)

```bash
aws ses send-email \
  --profile locosalsa12 \
  --region us-east-1 \
  --from prorsumhj@gmail.com \
  --destination "ToAddresses=fast2furious@naver.com" \
  --message '{
    "Subject": {
      "Data": "[AWS] hjcode-server EC2 기동 및 헬스체크 결과",
      "Charset": "UTF-8"
    },
    "Body": {
      "Text": {
        "Data": "헬스체크 결과 본문 내용",
        "Charset": "UTF-8"
      }
    }
  }'
```

> **주의:** SES 샌드박스 환경에서는 발신자/수신자 모두 사전 인증 필요

---

## EC2 인스턴스 중지

```bash
aws ec2 stop-instances \
  --instance-ids i-01202fdc8fb237804 \
  --profile locosalsa12 \
  --region us-east-1
```

### 중지 완료 대기 (필요시)
```bash
aws ec2 wait instance-stopped \
  --instance-ids i-01202fdc8fb237804 \
  --profile locosalsa12 \
  --region us-east-1
```

---

## SSH 접속 방법 (키 없는 서버 - EC2 Instance Connect)

이 서버는 SSH 키페어가 없으므로 EC2 Instance Connect로 임시 키 주입 방식 사용.

```bash
# 1. 임시 SSH 키 생성
ssh-keygen -t rsa -b 2048 -f /tmp/hjcode-temp-key -N ""

# 2. 임시 공개키 주입 (유효시간: 60초)
aws ec2-instance-connect send-ssh-public-key \
  --instance-id i-01202fdc8fb237804 \
  --instance-os-user ubuntu \
  --ssh-public-key file:///tmp/hjcode-temp-key.pub \
  --availability-zone us-east-1c \
  --profile locosalsa12 \
  --region us-east-1

# 3. 60초 이내 SSH 접속
ssh -i /tmp/hjcode-temp-key \
  -o StrictHostKeyChecking=no \
  ubuntu@54.145.191.25
```

---

## 모니터링 스택 설치 (Grafana / Alloy / Loki / Prometheus)

```bash
ssh -i /tmp/hjcode-temp-key -o StrictHostKeyChecking=no ubuntu@54.145.191.25 'sudo bash -s' << 'EOF'

# apt 업데이트
apt-get update -q

# Grafana 설치
wget -q -O - https://apt.grafana.com/gpg.key | gpg --dearmor | tee /usr/share/keyrings/grafana.gpg > /dev/null
echo "deb [signed-by=/usr/share/keyrings/grafana.gpg] https://apt.grafana.com stable main" | tee /etc/apt/sources.list.d/grafana.list
apt-get update -q && apt-get install -y grafana
systemctl enable grafana-server && systemctl start grafana-server

# Alloy 설치 (Grafana repo에 포함)
apt-get install -y alloy
systemctl enable alloy && systemctl start alloy

# Loki 설치 (GitHub 최신 stable)
LOKI_VER=$(curl -s https://api.github.com/repos/grafana/loki/releases/latest | grep '"tag_name"' | cut -d'"' -f4)
wget -q "https://github.com/grafana/loki/releases/download/${LOKI_VER}/loki-linux-amd64.zip" -O /tmp/loki.zip
unzip -o /tmp/loki.zip -d /tmp/ && mv /tmp/loki-linux-amd64 /usr/local/bin/loki && chmod +x /usr/local/bin/loki
systemctl enable loki && systemctl start loki

# Prometheus 설치 (GitHub 최신 stable)
PROM_VER=$(curl -s https://api.github.com/repos/prometheus/prometheus/releases/latest | grep '"tag_name"' | cut -d'"' -f4 | sed 's/v//')
wget -q "https://github.com/prometheus/prometheus/releases/download/v${PROM_VER}/prometheus-${PROM_VER}.linux-amd64.tar.gz" -O /tmp/prometheus.tar.gz
tar -xzf /tmp/prometheus.tar.gz -C /tmp/
mv /tmp/prometheus-${PROM_VER}.linux-amd64/prometheus /usr/local/bin/
systemctl enable prometheus && systemctl start prometheus

EOF
```

**설치된 버전 (2026-04-22 기준):**

| 서비스 | 버전 | 포트 |
|--------|------|------|
| Grafana | v13.0.1 | 3000 |
| Alloy | v1.15.1 | - |
| Loki | v3.7.1 | 3100 |
| Prometheus | v3.11.2 | 9090 |

---

## 인스턴스 정보 요약

| 항목 | 값 |
|------|-----|
| Instance ID | `i-01202fdc8fb237804` |
| Name | `hjcode-server` |
| OS | Ubuntu 24.04 LTS |
| Type | t3.small |
| Region | us-east-1 |
| AZ | us-east-1c |
| Public IP | 54.145.191.25 (기동 시마다 변경) |
| Private IP | 172.31.39.130 |
| IAM Role | cloudwatchagent-role |
| AWS Profile | locosalsa12 |
