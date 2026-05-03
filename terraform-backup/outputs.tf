output "vpc_id" {
  value = aws_vpc.main.id
}

output "hjcode_server_id" {
  value = aws_instance.hjcode_server.id
}

output "hjcode_server_public_ip" {
  value = aws_instance.hjcode_server.public_ip
}

output "alb_dns_name" {
  value = aws_lb.hjcode_alb.dns_name
}

output "rds_endpoint" {
  value = aws_db_instance.hjcode_database.endpoint
}
