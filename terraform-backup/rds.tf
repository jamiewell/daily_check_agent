# RDS Subnet Group
resource "aws_db_subnet_group" "main" {
  name        = "hjcode-db-subnet-group"
  description = "hjcode database subnet group"
  subnet_ids = [
    aws_subnet.us_east_1a.id,
    aws_subnet.us_east_1b.id,
    aws_subnet.us_east_1c.id,
    aws_subnet.us_east_1d.id,
    aws_subnet.us_east_1e.id,
    aws_subnet.us_east_1f.id,
  ]
  tags = { Name = "hjcode-db-subnet-group" }
}

# RDS Instance (MySQL 8.0, db.t4g.micro)
resource "aws_db_instance" "hjcode_database" {
  identifier              = "hjcode-database"
  engine                  = "mysql"
  engine_version          = "8.0"
  instance_class          = "db.t4g.micro"
  allocated_storage       = 20
  max_allocated_storage   = 1000
  storage_type            = "gp2"
  storage_encrypted       = true
  db_name                 = "hjcode"
  username                = "admin"
  password                = var.rds_password
  publicly_accessible     = true
  multi_az                = false
  availability_zone       = "us-east-1c"
  db_subnet_group_name    = aws_db_subnet_group.main.name
  vpc_security_group_ids  = [aws_security_group.db.id]
  backup_retention_period = 1
  copy_tags_to_snapshot   = true
  deletion_protection     = false
  skip_final_snapshot     = true

  tags = { Name = "hjcode-database" }
}
