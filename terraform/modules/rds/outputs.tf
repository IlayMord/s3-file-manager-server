output "db_endpoint" {
  value = aws_db_instance.postgres.address
}

output "db_name" {
  value = aws_db_instance.postgres.db_name
}

output "db_username" {
  value = aws_db_instance.postgres.username
}

output "db_port" {
  value = aws_db_instance.postgres.port
}
