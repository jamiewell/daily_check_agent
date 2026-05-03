# Ubuntu 24.04 LTS AMI (x86_64) - ami-04b4f1a9cf54c11d0
# Ubuntu 24.04 LTS AMI (ARM64)   - ami-0a7a4e87939439934

# hjcode-server (t3.small, Ubuntu 24.04 x86, us-east-1c)
resource "aws_instance" "hjcode_server" {
  ami                    = "ami-04b4f1a9cf54c11d0"
  instance_type          = "t3.small"
  subnet_id              = aws_subnet.us_east_1c.id
  vpc_security_group_ids = [aws_security_group.hjcode_server.id]
  iam_instance_profile   = aws_iam_instance_profile.cloudwatchagent_profile.name

  root_block_device {
    volume_type = "gp3"
    volume_size = 8
  }

  tags = { Name = "hjcode-server" }
}

# trfc-optr-kafka-broker (t3.small, Ubuntu 24.04 x86, us-east-1c)
resource "aws_instance" "kafka_broker" {
  ami                    = "ami-04b4f1a9cf54c11d0"
  instance_type          = "t3.small"
  subnet_id              = aws_subnet.us_east_1c.id
  vpc_security_group_ids = [aws_security_group.kafka_broker.id]

  root_block_device {
    volume_type = "gp3"
    volume_size = 8
  }

  tags = { Name = "trfc-optr-kafka-broker" }
}

# trfc-optr-kafka-broker-01 (t4g.small, Ubuntu 24.04 ARM64, us-east-1c)
resource "aws_instance" "kafka_broker_01" {
  ami                    = "ami-0a7a4e87939439934"
  instance_type          = "t4g.small"
  subnet_id              = aws_subnet.us_east_1c.id
  vpc_security_group_ids = [aws_security_group.kafka_broker_01.id]

  root_block_device {
    volume_type = "gp3"
    volume_size = 8
  }

  tags = { Name = "trfc-optr-kafka-broker-01" }
}

# K6-server (t3a.small, Ubuntu 24.04 x86, us-east-1a)
resource "aws_instance" "k6_server" {
  ami                    = "ami-04b4f1a9cf54c11d0"
  instance_type          = "t3a.small"
  subnet_id              = aws_subnet.us_east_1a.id
  vpc_security_group_ids = [aws_security_group.k6_server.id]

  root_block_device {
    volume_type = "gp3"
    volume_size = 8
  }

  tags = { Name = "K6-server" }
}

# kafka-server (t2.medium, ami-0360c520857e3138f, us-east-1b)
resource "aws_instance" "kafka_server" {
  ami                    = "ami-0360c520857e3138f"
  instance_type          = "t2.medium"
  subnet_id              = aws_subnet.us_east_1b.id
  vpc_security_group_ids = [aws_security_group.kafka_server.id]

  root_block_device {
    volume_type = "gp3"
    volume_size = 8
  }

  tags = { Name = "kafka-server" }
}
