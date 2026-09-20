# Hosting for the TypeScript MCP server.
#
# Container Apps rather than Azure Functions: the server is a long-lived HTTP
# service with a Postgres connection pool, min_replicas = 0 means it still
# scales to zero, and the same container image runs locally under Docker.

resource "azurerm_container_registry" "main" {
  name                = "cr${var.project}${random_string.suffix.result}"
  resource_group_name = azurerm_resource_group.main.name
  location            = azurerm_resource_group.main.location
  sku                 = "Basic"
  # No admin user: the Container App pulls with its managed identity.
  admin_enabled = false
  tags          = local.common_tags
}

resource "azurerm_user_assigned_identity" "mcp" {
  name                = "id-mcp-${local.name}"
  resource_group_name = azurerm_resource_group.main.name
  location            = azurerm_resource_group.main.location
  tags                = local.common_tags
}

resource "azurerm_role_assignment" "mcp_acr_pull" {
  scope                = azurerm_container_registry.main.id
  role_definition_name = "AcrPull"
  principal_id         = azurerm_user_assigned_identity.mcp.principal_id
}

resource "azurerm_role_assignment" "mcp_kv_secrets" {
  scope                = azurerm_key_vault.main.id
  role_definition_name = "Key Vault Secrets User"
  principal_id         = azurerm_user_assigned_identity.mcp.principal_id
}

resource "azurerm_container_app_environment" "main" {
  name                       = "cae-${local.name}"
  resource_group_name        = azurerm_resource_group.main.name
  location                   = azurerm_resource_group.main.location
  log_analytics_workspace_id = azurerm_log_analytics_workspace.main.id
  tags                       = local.common_tags
}

resource "azurerm_container_app" "mcp" {
  name                         = "ca-mcp-${local.name}"
  resource_group_name          = azurerm_resource_group.main.name
  container_app_environment_id = azurerm_container_app_environment.main.id
  revision_mode                = "Single"
  tags                         = local.common_tags

  identity {
    type         = "UserAssigned"
    identity_ids = [azurerm_user_assigned_identity.mcp.id]
  }

  registry {
    server   = azurerm_container_registry.main.login_server
    identity = azurerm_user_assigned_identity.mcp.id
  }

  secret {
    name                = "database-url-readonly"
    key_vault_secret_id = azurerm_key_vault_secret.mcp_database_url.id
    identity            = azurerm_user_assigned_identity.mcp.id
  }

  ingress {
    external_enabled = true
    target_port      = 3000
    transport        = "auto"

    traffic_weight {
      latest_revision = true
      percentage      = 100
    }
  }

  template {
    # Scale to zero: nothing is billed while no question is being asked.
    min_replicas = 0
    max_replicas = 2

    container {
      name = "mcp-server"
      # Placeholder until the image is built and pushed to the registry.
      # Swap for "${azurerm_container_registry.main.login_server}/netzanalyst-mcp:<tag>".
      image  = "mcr.microsoft.com/k8se/quickstart:latest"
      cpu    = 0.25
      memory = "0.5Gi"

      env {
        name        = "DATABASE_URL_READONLY"
        secret_name = "database-url-readonly"
      }
      env {
        name  = "MCP_PORT"
        value = "3000"
      }
      env {
        name  = "MCP_MAX_ROWS"
        value = "1000"
      }
      env {
        name  = "MCP_QUERY_TIMEOUT_MS"
        value = "10000"
      }
      env {
        name  = "APPLICATIONINSIGHTS_CONNECTION_STRING"
        value = azurerm_application_insights.main.connection_string
      }

      liveness_probe {
        transport = "HTTP"
        port      = 3000
        path      = "/health"
      }
      readiness_probe {
        transport = "HTTP"
        port      = 3000
        path      = "/health"
      }
    }
  }

  lifecycle {
    # The image tag changes on every deploy, outside Terraform.
    ignore_changes = [template[0].container[0].image]
  }
}

# The read-only connection string. The read-only role itself is created by the
# schema migration, not by Terraform.
resource "azurerm_key_vault_secret" "mcp_database_url" {
  name = "mcp-database-url-readonly"
  value = format(
    "postgresql://%s:%s@%s:5432/%s?sslmode=require",
    "netzanalyst_ro",
    random_password.postgres_readonly.result,
    azurerm_postgresql_flexible_server.main.fqdn,
    azurerm_postgresql_flexible_server_database.main.name,
  )
  key_vault_id = azurerm_key_vault.main.id

  depends_on = [azurerm_role_assignment.kv_admin]
}

resource "random_password" "postgres_readonly" {
  length           = 32
  special          = true
  override_special = "!#%*_-+="
  min_lower        = 2
  min_upper        = 2
  min_numeric      = 2
  min_special      = 2
}

resource "azurerm_key_vault_secret" "postgres_readonly_password" {
  name         = "postgres-readonly-password"
  value        = random_password.postgres_readonly.result
  key_vault_id = azurerm_key_vault.main.id

  depends_on = [azurerm_role_assignment.kv_admin]
}
