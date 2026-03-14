variable "vpc_id" {
  type = string
}

variable "private_subnet_ids" {
  type = list(string)
}

variable "ec2_security_group_id" {
  type = string
}

variable "db_password" {
  type      = string
  sensitive = true
}

variable "db_name" {
  type    = string
  default = "s3_file_manager"
}

variable "db_username" {
  type    = string
  default = "s3fm"
}

variable "instance_class" {
  type    = string
  default = "db.t3.micro"
}

variable "final_snapshot_identifier" {
  type    = string
  default = "s3fm-db-final-snapshot"
}
