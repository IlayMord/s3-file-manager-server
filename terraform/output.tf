output "nlb_dns_name" {
  value = module.nlb.nlb_dns_name
}

output "rds_endpoint" {
  value = module.rds.db_endpoint
}

output "rds_port" {
  value = module.rds.db_port
}

output "rds_db_name" {
  value = module.rds.db_name
}
