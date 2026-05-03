# CLAUDE 2 — EC2 모니터링 스택 설치 및 로컬 PC 연동

## 개요

`hjcode-server` (i-01202fdc8fb237804, Ubuntu 24.04, us-east-1c)에 Grafana / Alloy / Loki / Prometheus를 설치하고 로컬 PC와 연동하는 가이드.

---

## 설치된 버전 (2026-04-22 기준)

| 서비스 | 버전 | 포트 | 설치 방법 |
|--------|------|------|-----------|
| Grafana | v13.0.1 | 3000 | apt (grafana repo) |
| Alloy | v1.15.1 | 12345 | apt (grafana repo) |
| Loki | v3.7.1 | 3100 | GitHub binary |
| Prometheus | v3.11.2 | 9090 | GitHub binary |

---

## 설치 스크립트

### 사전 준비 (EC2 접속)

```bash
# 키 주입 후 접속
aws ec2-instance-connect send-ssh-public-key \
  --instance-id i-01202fdc8fb237804 \
  --instance-os-user ubuntu \
  --ssh-public-key file:///tmp/hjcode-temp-key.pub \
  --availability-zone us-east-1c \
  --profile locosalsa12 --region us-east-1

ssh -i /tmp/hjcode-temp-key -o StrictHostKeyChecking=no ubuntu@<PUBLIC_IP>
```

### 전체 설치 스크립트

```bash
sudo bash << 'EOF'

# apt 업데이트
apt-get update -q

# ── Grafana 설치 ──────────────────────────────────────────
wget -q -O - https://apt.grafana.com/gpg.key | gpg --dearmor \
  | tee /usr/share/keyrings/grafana.gpg > /dev/null
echo "deb [signed-by=/usr/share/keyrings/grafana.gpg] https://apt.grafana.com stable main" \
  | tee /etc/apt/sources.list.d/grafana.list
apt-get update -q && apt-get install -y grafana
systemctl enable grafana-server && systemctl start grafana-server

# ── Alloy 설치 (Grafana repo에 포함) ─────────────────────
apt-get install -y alloy
systemctl enable alloy && systemctl start alloy

# ── Loki 설치 ─────────────────────────────────────────────
LOKI_VER=$(curl -s https://api.github.com/repos/grafana/loki/releases/latest \
  | grep '"tag_name"' | cut -d'"' -f4)
wget -q "https://github.com/grafana/loki/releases/download/${LOKI_VER}/loki-linux-amd64.zip" \
  -O /tmp/loki.zip
apt-get install -y unzip && unzip -o /tmp/loki.zip -d /tmp/
mv /tmp/loki-linux-amd64 /usr/local/bin/loki && chmod +x /usr/local/bin/loki
mkdir -p /etc/loki /var/lib/loki

cat > /etc/loki/config.yaml << 'LOKIEOF'
auth_enabled: false
server:
  http_listen_port: 3100
common:
  path_prefix: /var/lib/loki
  storage:
    filesystem:
      chunks_directory: /var/lib/loki/chunks
      rules_directory: /var/lib/loki/rules
  replication_factor: 1
  ring:
    kvstore:
      store: inmemory
schema_config:
  configs:
    - from: 2020-10-24
      store: tsdb
      object_store: filesystem
      schema: v13
      index:
        prefix: index_
        period: 24h
LOKIEOF

cat > /etc/systemd/system/loki.service << 'SVCEOF'
[Unit]
Description=Loki log aggregation system
After=network.target
[Service]
ExecStart=/usr/local/bin/loki -config.file=/etc/loki/config.yaml
Restart=always
User=root
[Install]
WantedBy=multi-user.target
SVCEOF

systemctl daemon-reload
systemctl enable loki && systemctl start loki

# ── Prometheus 설치 ───────────────────────────────────────
PROM_VER=$(curl -s https://api.github.com/repos/prometheus/prometheus/releases/latest \
  | grep '"tag_name"' | cut -d'"' -f4 | sed 's/v//')
wget -q "https://github.com/prometheus/prometheus/releases/download/v${PROM_VER}/prometheus-${PROM_VER}.linux-amd64.tar.gz" \
  -O /tmp/prometheus.tar.gz
tar -xzf /tmp/prometheus.tar.gz -C /tmp/
mv /tmp/prometheus-${PROM_VER}.linux-amd64/prometheus /usr/local/bin/
mkdir -p /etc/prometheus /var/lib/prometheus

cat > /etc/prometheus/prometheus.yml << 'PROMEOF'
global:
  scrape_interval: 15s
scrape_configs:
  - job_name: 'prometheus'
    static_configs:
      - targets: ['localhost:9090']
PROMEOF

cat > /etc/systemd/system/prometheus.service << 'SVCEOF'
[Unit]
Description=Prometheus monitoring system
After=network.target
[Service]
ExecStart=/usr/local/bin/prometheus \
  --config.file=/etc/prometheus/prometheus.yml \
  --storage.tsdb.path=/var/lib/prometheus
Restart=always
User=root
[Install]
WantedBy=multi-user.target
SVCEOF

systemctl daemon-reload
systemctl enable prometheus && systemctl start prometheus

EOF
```

### 서비스 상태 확인

```bash
for svc in grafana-server alloy loki prometheus; do
  echo "$svc: $(systemctl is-active $svc)"
done
```

---

## 로컬 PC 연동

### 보안 그룹 포트 오픈 (AWS CLI)

```bash
SG_ID="sg-03bc9331f1438094f"   # hjcode-server SG
MY_IP="$(curl -s ifconfig.me)/32"

for PORT in 3000 9090 3100 12345; do
  aws ec2 authorize-security-group-ingress \
    --group-id $SG_ID \
    --protocol tcp --port $PORT --cidr $MY_IP \
    --profile locosalsa12 --region us-east-1
done
```

### 접속 URL (EC2 Public IP 기준)

| 서비스 | 접속 주소 | 기본 계정 |
|--------|-----------|-----------|
| Grafana | `http://<PUBLIC_IP>:3000` | admin / admin |
| Prometheus | `http://<PUBLIC_IP>:9090` | - |
| Loki | `http://<PUBLIC_IP>:3100` | - |
| Alloy | `http://<PUBLIC_IP>:12345` | - |

> EC2는 재시작 시 Public IP가 변경됨. 고정이 필요하면 Elastic IP 할당 필요.

### Grafana에서 Prometheus 데이터소스 연동

1. Grafana 접속 → Connections → Data sources → Add new
2. Prometheus 선택
3. URL: `http://localhost:9090`
4. Save & Test

### Grafana에서 Loki 데이터소스 연동

1. Data sources → Add new → Loki
2. URL: `http://localhost:3100`
3. Save & Test

---

## SSH 터널링 (포트를 열지 않고 로컬에서 접속)

보안 그룹 오픈 없이 SSH 터널로 안전하게 접속하는 방법.

```bash
# 임시 키 주입
aws ec2-instance-connect send-ssh-public-key \
  --instance-id i-01202fdc8fb237804 \
  --instance-os-user ubuntu \
  --ssh-public-key file:///tmp/hjcode-temp-key.pub \
  --availability-zone us-east-1c \
  --profile locosalsa12 --region us-east-1

# 터널 설정 (로컬 포트 → EC2 포트)
ssh -i /tmp/hjcode-temp-key -o StrictHostKeyChecking=no \
  -L 3000:localhost:3000 \
  -L 9090:localhost:9090 \
  -L 3100:localhost:3100 \
  -N ubuntu@<PUBLIC_IP> &

# 이후 로컬에서 접속
# http://localhost:3000  → Grafana
# http://localhost:9090  → Prometheus
# http://localhost:3100  → Loki
```

---

## 서비스 설정 파일 위치

| 서비스 | 설정 파일 | 데이터 경로 |
|--------|-----------|-------------|
| Grafana | `/etc/grafana/grafana.ini` | `/var/lib/grafana` |
| Alloy | `/etc/alloy/config.alloy` | - |
| Loki | `/etc/loki/config.yaml` | `/var/lib/loki` |
| Prometheus | `/etc/prometheus/prometheus.yml` | `/var/lib/prometheus` |
