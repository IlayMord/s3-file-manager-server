variable "region" {
  type    = string
  default = "us-east-1"
}

variable "vpc_cidr" {
  type    = string
  default = "10.0.0.0/16"
}

variable "subnet_cidr" {
  type    = string
  default = "10.0.1.0/24"
}

variable "ami_id" {
  type    = string
  default = "ami-0e001c9271cf7f3b9"
}

variable "instance_type" {
  type    = string
  default = "t2.micro"
}

variable "key_name" {
  type    = string
  default = "ilay-private-key"
}

variable "asg_desired_capacity" {
  type    = number
  default = 2
}

variable "asg_min_size" {
  type    = number
  default = 2
}

variable "asg_max_size" {
  type    = number
  default = 4
}

variable "asg_cpu_target_value" {
  type    = number
  default = 50
}

variable "asg_estimated_instance_warmup" {
  type    = number
  default = 180
}

variable "db_password" {
  type      = string
  sensitive = true
}

variable "private_subnet_1_cidr" {
  type    = string
  default = "10.0.2.0/24"
}

variable "private_subnet_2_cidr" {
  type    = string
  default = "10.0.3.0/24"
}
