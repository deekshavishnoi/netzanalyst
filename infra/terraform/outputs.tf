output "resource_group_name" {
  description = "Resource group holding everything Terraform created."
  value       = azurerm_resource_group.main.name
}

output "postgres_fqdn" {
  description = "Hostname of the Postgres flexible server."
  value       = azurerm_postgresql_flexible_server.main.fqdn
}

output "postgres_admin_username" {
  description = "Postgres administrator login. The password is in Key Vault."
  value       = var.postgres_admin_username
}

output "key_vault_name" {
  description = "Key Vault holding the database passwords."
  value       = azurerm_key_vault.main.name
}

output "container_registry_login_server" {
  description = "Registry to push the MCP server image to."
  value       = azurerm_container_registry.main.login_server
}

output "mcp_server_url" {
  description = "Public URL of the MCP server. MCP is at /mcp, health at /health."
  value       = "https://${azurerm_container_app.mcp.ingress[0].fqdn}"
}

output "application_insights_connection_string" {
  description = "Application Insights connection string for tracing."
  value       = azurerm_application_insights.main.connection_string
  sensitive   = true
}

output "next_steps" {
  description = "What to do after a successful apply."
  value       = <<-EOT
    1. Build and push the MCP image:
         az acr login --name ${azurerm_container_registry.main.name}
         docker build -t ${azurerm_container_registry.main.login_server}/netzanalyst-mcp:v1 ./services/mcp-server
         docker push ${azurerm_container_registry.main.login_server}/netzanalyst-mcp:v1
         az containerapp update -n ${azurerm_container_app.mcp.name} \
           -g ${azurerm_resource_group.main.name} \
           --image ${azurerm_container_registry.main.login_server}/netzanalyst-mcp:v1
    2. Apply the schema and create the read-only role against ${azurerm_postgresql_flexible_server.main.fqdn}.
    3. Load the data with python -m netzanalyst.ingest.
    4. STOP THE POSTGRES SERVER when you are not using it:
         az postgres flexible-server stop -n ${azurerm_postgresql_flexible_server.main.name} -g ${azurerm_resource_group.main.name}
  EOT
}
