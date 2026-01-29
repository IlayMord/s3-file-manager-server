module "vpc" {
  source = "./modules/vpc"

  vpc_cidr    = var.vpc_cidr
  subnet_cidr = var.subnet_cidr
}

module "nlb" {
  source    = "./modules/nlb"
  name      = "s3fm"
  subnet_id = module.vpc.subnet_id
  vpc_id    = module.vpc.vpc_id
}

module "asg" {
  source            = "./modules/asg"
  name              = "s3fm"
  subnet_id         = module.vpc.subnet_id
  security_group_id = module.vpc.security_group_id
  target_group_arn = module.nlb.target_group_arn
  ami_id            = var.ami_id
  instance_type     = var.instance_type
  key_name          = var.key_name
  desired_capacity  = var.asg_desired_capacity
  min_size          = var.asg_min_size
  max_size          = var.asg_max_size
}
