resource "aws_db_subnet_group" "rds_subnet_group" {
  name       = "s3fm-db-subnet"
  subnet_ids = var.private_subnet_ids
}

resource "aws_security_group" "rds_sg" {
  name   = "s3fm-rds-sg"
  vpc_id = var.vpc_id

  ingress {
    from_port = 5432
    to_port   = 5432
    protocol  = "tcp"

    security_groups = [
      var.ec2_security_group_id
    ]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

resource "aws_db_instance" "postgres" {
  identifier = "s3fm-db"

  engine         = "postgres"
  engine_version = "16"

  instance_class    = var.instance_class
  allocated_storage = 20

  db_name  = var.db_name
  username = var.db_username
  password = var.db_password

  db_subnet_group_name = aws_db_subnet_group.rds_subnet_group.name

  vpc_security_group_ids = [
    aws_security_group.rds_sg.id
  ]

  publicly_accessible      = false
  storage_encrypted        = true
  backup_retention_period  = 7
  deletion_protection      = true
  skip_final_snapshot      = false
  final_snapshot_identifier = var.final_snapshot_identifier

  lifecycle {
    prevent_destroy = true
  }
}
