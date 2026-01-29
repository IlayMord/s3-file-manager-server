resource "aws_launch_template" "this" {
  name_prefix   = "${var.name}-lt-"
  image_id      = var.ami_id
  instance_type = var.instance_type
  
  key_name = var.key_name

  vpc_security_group_ids = [var.security_group_id]

  user_data = base64encode(<<-EOF
#!/bin/bash
set -e

apt update -y
apt install -y docker.io docker-compose git

systemctl start docker
systemctl enable docker

cd /home/ubuntu

if [ ! -d "s3-file-manager-server" ]; then
    git clone https://github.com/IlayMord/s3-file-manager-server.git
fi

cd s3-file-manager-server/docker
docker-compose up -d
EOF
  )

  tag_specifications {
    resource_type = "instance"
    tags = {
      Name = "${var.name}-asg-instance"
    }
  }
}

resource "aws_autoscaling_group" "this" {
  name                      = "${var.name}-asg"
  desired_capacity          = var.desired_capacity
  max_size                  = var.max_size
  min_size                  = var.min_size
  vpc_zone_identifier       = [var.subnet_id]
  target_group_arns         = [var.target_group_arn]
  health_check_type         = "EC2"

  launch_template {
    id      = aws_launch_template.this.id
    version = "$Latest"
  }

  tag {
    key                 = "Name"
    value               = "${var.name}-asg-instance"
    propagate_at_launch = true
  }
}
