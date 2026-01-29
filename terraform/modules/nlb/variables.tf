variable "name" {
  type = string
}

variable "subnet_id" {
  type = string
}

variable "vpc_id" {
  type = string
}

variable "target_port" {
  type    = number
  default = 80
}
