# hjcode-alb-security-group (ALB용: HTTP 80 전체 허용)
resource "aws_security_group" "hjcode_alb" {
  name        = "hjcode-alb-security-group"
  description = "hjcode-alb-security-group"
  vpc_id      = aws_vpc.main.id

  ingress {
    from_port   = 80
    to_port     = 80
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }
  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
  tags = { Name = "hjcode-alb-security-group" }
}

# hjcode-server (launch-wizard-3: HTTP 80 + SSH 22)
resource "aws_security_group" "hjcode_server" {
  name        = "hjcode-server-sg"
  description = "hjcode-server security group"
  vpc_id      = aws_vpc.main.id

  ingress {
    from_port   = 22
    to_port     = 22
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }
  ingress {
    from_port   = 80
    to_port     = 80
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }
  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
  tags = { Name = "hjcode-server-sg" }
}

# K6-server (launch-wizard-2: SSH 22 + 5665)
resource "aws_security_group" "k6_server" {
  name        = "k6-server-sg"
  description = "k6-server security group"
  vpc_id      = aws_vpc.main.id

  ingress {
    from_port   = 22
    to_port     = 22
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }
  ingress {
    from_port   = 5665
    to_port     = 5665
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }
  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
  tags = { Name = "k6-server-sg" }
}

# Kafka broker (launch-wizard-4: SSH 22 + 9092/9093)
resource "aws_security_group" "kafka_broker" {
  name        = "kafka-broker-sg"
  description = "kafka broker security group"
  vpc_id      = aws_vpc.main.id

  ingress {
    from_port   = 22
    to_port     = 22
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }
  ingress {
    from_port       = 9092
    to_port         = 9092
    protocol        = "tcp"
    security_groups = [aws_security_group.kafka_broker_01.id]
    description     = "kafka"
  }
  ingress {
    from_port       = 9093
    to_port         = 9093
    protocol        = "tcp"
    security_groups = [aws_security_group.kafka_broker_01.id]
    description     = "kafka"
  }
  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
  tags = { Name = "kafka-broker-sg" }
}

# Kafka broker 01 (launch-wizard-5: SSH 22 + 9092/9093)
resource "aws_security_group" "kafka_broker_01" {
  name        = "kafka-broker-01-sg"
  description = "kafka broker 01 security group"
  vpc_id      = aws_vpc.main.id

  ingress {
    from_port   = 22
    to_port     = 22
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }
  ingress {
    from_port       = 9092
    to_port         = 9092
    protocol        = "tcp"
    security_groups = [aws_security_group.kafka_broker.id]
    description     = "kafka"
  }
  ingress {
    from_port       = 9093
    to_port         = 9093
    protocol        = "tcp"
    security_groups = [aws_security_group.kafka_broker.id]
    description     = "kafka"
  }
  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
  tags = { Name = "kafka-broker-01-sg" }
}

# kafka-server (kafka-server-security-group: TCP 0-65535 + SSH 22)
resource "aws_security_group" "kafka_server" {
  name        = "kafka-server-security-group"
  description = "kafka-server-security-group"
  vpc_id      = aws_vpc.main.id

  ingress {
    from_port   = 0
    to_port     = 65535
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }
  ingress {
    from_port   = 22
    to_port     = 22
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }
  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
  tags = { Name = "kafka-server-security-group" }
}

# DB security group (MySQL 3306)
resource "aws_security_group" "db" {
  name        = "db"
  description = "db"
  vpc_id      = aws_vpc.main.id

  ingress {
    from_port   = 3306
    to_port     = 3306
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }
  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
  tags = { Name = "db-sg" }
}
