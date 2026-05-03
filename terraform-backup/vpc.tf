# VPC
resource "aws_vpc" "main" {
  cidr_block           = "172.31.0.0/16"
  enable_dns_support   = true
  enable_dns_hostnames = true

  tags = { Name = "hjcode-vpc" }
}

# Internet Gateway
resource "aws_internet_gateway" "main" {
  vpc_id = aws_vpc.main.id
  tags   = { Name = "hjcode-igw" }
}

# Subnets (6 AZ)
resource "aws_subnet" "us_east_1a" {
  vpc_id                  = aws_vpc.main.id
  cidr_block              = "172.31.80.0/20"
  availability_zone       = "us-east-1a"
  map_public_ip_on_launch = true
  tags = { Name = "hjcode-subnet-1a" }
}

resource "aws_subnet" "us_east_1b" {
  vpc_id                  = aws_vpc.main.id
  cidr_block              = "172.31.16.0/20"
  availability_zone       = "us-east-1b"
  map_public_ip_on_launch = true
  tags = { Name = "hjcode-subnet-1b" }
}

resource "aws_subnet" "us_east_1c" {
  vpc_id                  = aws_vpc.main.id
  cidr_block              = "172.31.32.0/20"
  availability_zone       = "us-east-1c"
  map_public_ip_on_launch = true
  tags = { Name = "hjcode-subnet-1c" }
}

resource "aws_subnet" "us_east_1d" {
  vpc_id                  = aws_vpc.main.id
  cidr_block              = "172.31.0.0/20"
  availability_zone       = "us-east-1d"
  map_public_ip_on_launch = true
  tags = { Name = "hjcode-subnet-1d" }
}

resource "aws_subnet" "us_east_1e" {
  vpc_id                  = aws_vpc.main.id
  cidr_block              = "172.31.48.0/20"
  availability_zone       = "us-east-1e"
  map_public_ip_on_launch = true
  tags = { Name = "hjcode-subnet-1e" }
}

resource "aws_subnet" "us_east_1f" {
  vpc_id                  = aws_vpc.main.id
  cidr_block              = "172.31.64.0/20"
  availability_zone       = "us-east-1f"
  map_public_ip_on_launch = true
  tags = { Name = "hjcode-subnet-1f" }
}

# Route Table
resource "aws_route_table" "main" {
  vpc_id = aws_vpc.main.id

  route {
    cidr_block = "0.0.0.0/0"
    gateway_id = aws_internet_gateway.main.id
  }

  tags = { Name = "hjcode-rt-main" }
}

# Route Table Associations
resource "aws_route_table_association" "a" {
  subnet_id      = aws_subnet.us_east_1a.id
  route_table_id = aws_route_table.main.id
}
resource "aws_route_table_association" "b" {
  subnet_id      = aws_subnet.us_east_1b.id
  route_table_id = aws_route_table.main.id
}
resource "aws_route_table_association" "c" {
  subnet_id      = aws_subnet.us_east_1c.id
  route_table_id = aws_route_table.main.id
}
resource "aws_route_table_association" "d" {
  subnet_id      = aws_subnet.us_east_1d.id
  route_table_id = aws_route_table.main.id
}
resource "aws_route_table_association" "e" {
  subnet_id      = aws_subnet.us_east_1e.id
  route_table_id = aws_route_table.main.id
}
resource "aws_route_table_association" "f" {
  subnet_id      = aws_subnet.us_east_1f.id
  route_table_id = aws_route_table.main.id
}
