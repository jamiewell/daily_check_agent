variable "region" {
  default = "us-east-1"
}

variable "rds_password" {
  description = "RDS master password"
  type        = string
  sensitive   = true
}

variable "allowed_ssh_cidr" {
  description = "CIDR block allowed for SSH access"
  default     = "58.151.93.2/32"
}
