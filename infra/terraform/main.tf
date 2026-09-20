# netzanalyst Azure infrastructure.
#
# NOTHING HERE HAS BEEN APPLIED. Run `terraform plan` and read it before any
# apply — several resources bill by the hour.
#
# Cost shape (rough, Sweden Central, subject to change — verify in the pricing
# calculator before applying):
#   Postgres B1ms + 32 GB     the largest fixed line item; stop it when idle
#   Container App             scales to zero, so ~free when not in use
#   Key Vault                 negligible
#   Log Analytics + App Insights   pay per GB ingested; capped below
#   Foundry model deployment  pay per token
#
# Deliberately NOT here: Azure AI Search (charges per hour and is not needed).

locals {
  name = "${var.project}-${var.environment}"

  common_tags = merge(
    {
      project     = var.project
      environment = var.environment
      managed_by  = "terraform"
    },
    var.tags,
  )
}

resource "random_string" "suffix" {
  length  = 6
  special = false
  upper   = false
}

resource "azurerm_resource_group" "main" {
  name     = "rg-${local.name}"
  location = var.location
  tags     = local.common_tags
}

# ---------------------------------------------------------------------------
# Observability
# ---------------------------------------------------------------------------

resource "azurerm_log_analytics_workspace" "main" {
  name                = "log-${local.name}"
  resource_group_name = azurerm_resource_group.main.name
  location            = azurerm_resource_group.main.location
  sku                 = "PerGB2018"
  retention_in_days   = 30
  # Hard stop on ingestion cost: this is a portfolio project, not production.
  daily_quota_gb = 1
  tags           = local.common_tags
}

resource "azurerm_application_insights" "main" {
  name                = "appi-${local.name}"
  resource_group_name = azurerm_resource_group.main.name
  location            = azurerm_resource_group.main.location
  workspace_id        = azurerm_log_analytics_workspace.main.id
  application_type    = "web"
  tags                = local.common_tags
}

# ---------------------------------------------------------------------------
# Secrets
# ---------------------------------------------------------------------------

data "azurerm_client_config" "current" {}

resource "azurerm_key_vault" "main" {
  name                = "kv-${var.project}-${random_string.suffix.result}"
  resource_group_name = azurerm_resource_group.main.name
  location            = azurerm_resource_group.main.location
  tenant_id           = data.azurerm_client_config.current.tenant_id
  sku_name            = "standard"

  # RBAC rather than access policies: managed identities get roles, and no
  # secret ever has to be handed to an application as an environment variable.
  rbac_authorization_enabled = true
  purge_protection_enabled   = false
  soft_delete_retention_days = 7

  tags = local.common_tags
}

resource "azurerm_role_assignment" "kv_admin" {
  scope                = azurerm_key_vault.main.id
  role_definition_name = "Key Vault Secrets Officer"
  principal_id         = data.azurerm_client_config.current.object_id
}

resource "random_password" "postgres_admin" {
  length  = 32
  special = true
  # Characters Postgres connection strings and shells both tolerate.
  override_special = "!#%*_-+="
  min_lower        = 2
  min_upper        = 2
  min_numeric      = 2
  min_special      = 2
}

resource "azurerm_key_vault_secret" "postgres_admin_password" {
  name         = "postgres-admin-password"
  value        = random_password.postgres_admin.result
  key_vault_id = azurerm_key_vault.main.id

  depends_on = [azurerm_role_assignment.kv_admin]
}

# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------

resource "azurerm_postgresql_flexible_server" "main" {
  name                = "psql-${var.project}-${random_string.suffix.result}"
  resource_group_name = azurerm_resource_group.main.name
  location            = azurerm_resource_group.main.location

  version                = "16"
  sku_name               = var.postgres_sku_name
  storage_mb             = var.postgres_storage_mb
  administrator_login    = var.postgres_admin_username
  administrator_password = random_password.postgres_admin.result

  # Cost control: no standby, minimum backup retention. This is reproducible
  # public data — it can always be re-ingested from SMARD.
  backup_retention_days        = 7
  geo_redundant_backup_enabled = false
  zone                         = "1"

  # Public access plus a firewall. A private endpoint would need a VNet and a
  # NAT gateway, which costs more than the rest of this project combined.
  public_network_access_enabled = true

  tags = local.common_tags

  lifecycle {
    # Changing the zone forces a replacement of the whole server.
    ignore_changes = [zone]
  }
}

resource "azurerm_postgresql_flexible_server_database" "main" {
  name      = "netzanalyst"
  server_id = azurerm_postgresql_flexible_server.main.id
  charset   = "UTF8"
  collation = "en_US.utf8"

  lifecycle {
    prevent_destroy = false
  }
}

# Allows other Azure services (the Container App) to reach the server.
# 0.0.0.0 is Azure's documented sentinel for "Azure services", not "the world".
resource "azurerm_postgresql_flexible_server_firewall_rule" "azure_services" {
  name             = "allow-azure-services"
  server_id        = azurerm_postgresql_flexible_server.main.id
  start_ip_address = "0.0.0.0"
  end_ip_address   = "0.0.0.0"
}

resource "azurerm_postgresql_flexible_server_firewall_rule" "client" {
  count = var.my_ip_address == "" ? 0 : 1

  name             = "allow-my-laptop"
  server_id        = azurerm_postgresql_flexible_server.main.id
  start_ip_address = var.my_ip_address
  end_ip_address   = var.my_ip_address
}
