# Application Load Balancer
resource "aws_lb" "hjcode_alb" {
  name               = "hjcode-alb"
  internal           = false
  load_balancer_type = "application"
  security_groups    = [aws_security_group.hjcode_alb.id]
  subnets = [
    aws_subnet.us_east_1a.id,
    aws_subnet.us_east_1b.id,
    aws_subnet.us_east_1c.id,
    aws_subnet.us_east_1d.id,
    aws_subnet.us_east_1e.id,
    aws_subnet.us_east_1f.id,
  ]

  tags = { Name = "hjcode-alb" }
}

# Target Group
resource "aws_lb_target_group" "hjcode_server" {
  name        = "hjcode-server-target-group"
  port        = 80
  protocol    = "HTTP"
  vpc_id      = aws_vpc.main.id
  target_type = "instance"

  health_check {
    enabled             = true
    path                = "/health"
    protocol            = "HTTP"
    port                = "traffic-port"
    interval            = 30
    timeout             = 5
    healthy_threshold   = 5
    unhealthy_threshold = 2
    matcher             = "200"
  }

  tags = { Name = "hjcode-server-target-group" }
}

# Target Group Attachment
resource "aws_lb_target_group_attachment" "hjcode_server" {
  target_group_arn = aws_lb_target_group.hjcode_server.arn
  target_id        = aws_instance.hjcode_server.id
  port             = 80
}

# Listener (HTTP:80 → forward to target group)
resource "aws_lb_listener" "http" {
  load_balancer_arn = aws_lb.hjcode_alb.arn
  port              = 80
  protocol          = "HTTP"

  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.hjcode_server.arn
  }
}
