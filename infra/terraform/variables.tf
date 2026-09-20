variable "project" {
  description = "Short name used as a prefix for every resource."
  type        = string
  default     = "netzanalyst"

  validation {
    condition     = can(regex("^[a-z][a-z0-9]{2,15}$", var.project))
    error_message = "project must be 3-16 lowercase alphanumeric characters, starting with a letter."
  }
}

variable "location" {
  description = <<-EOT
    Azure region. Keep everything in one region to avoid egress charges.

    Sweden Central carries every agent-supported model in the ladder below
    (gpt-4.1-mini, gpt-5-mini, gpt-5) plus Postgres Flexible Server and
    Container Apps, so the whole stack sits in one region and there is room to
    change model without moving anything else.

    Note: gpt-4.1-mini is ALSO available in Germany West Central. If a
    deployment fails there, the cause is almost certainly zero LLM quota on the
    subscription, not the region — see docs/azure-setup.md.
  EOT
  type        = string
  default     = "swedencentral"
}

variable "environment" {
  description = "Environment tag."
  type        = string
  default     = "dev"
}

variable "postgres_admin_username" {
  description = "Administrator login for the Postgres flexible server."
  type        = string
  default     = "netzadmin"
}

variable "postgres_sku_name" {
  description = <<-EOT
    Postgres Flexible Server SKU. B1ms is the smallest burstable tier and the
    cheapest option that runs this workload. Changing this is the single
    biggest lever on monthly cost.
  EOT
  type        = string
  default     = "B_Standard_B1ms"
}

variable "postgres_storage_mb" {
  description = "Postgres storage in MB. 32768 (32 GB) is the minimum."
  type        = number
  default     = 32768
}

variable "model_deployment_name" {
  description = "Name of the model deployment used by every agent."
  type        = string
  default     = "gpt-4.1-mini"
}

variable "model_name" {
  description = <<-EOT
    Foundry model to deploy.

    NOT gpt-5.4-mini, which the brief names. Verified 2026-09-20 against
    Microsoft Learn: gpt-5.4-mini deploys as Global Standard Azure OpenAI but is
    NOT on the agent-supported list for Foundry Agent Service, and this design
    runs agents on Agent Service.

    The ladder, cheapest first. Start at the bottom and only climb if the evals
    justify it, which is exactly the comparison the brief asks for:

      gpt-4.1-mini  agent-supported, cheapest, widest region coverage  <- default
      gpt-5-mini    agent-supported, stronger reasoning, fewer regions
      gpt-5         agent-supported, most capable, most expensive

    Re-check before applying; the list changes. The live check is the Foundry
    catalog filtered to agent-supported models:
      https://ai.azure.com/catalog/models?capabilities=agentsv2

    The gpt-5 family may need one-time registration on the subscription.
  EOT
  type        = string
  default     = "gpt-4.1-mini"

  validation {
    condition     = can(regex("^gpt-", var.model_name))
    error_message = "model_name must be a gpt-* deployment name."
  }
}

variable "model_capacity" {
  description = "Thousands of tokens per minute for the deployment. Keep low to cap spend."
  type        = number
  default     = 10
}

variable "my_ip_address" {
  description = <<-EOT
    Your public IP, used for the Postgres firewall rule so you can connect from
    your laptop. Find it with: curl -s https://api.ipify.org
    Leave empty to create no client firewall rule at all.
  EOT
  type        = string
  default     = ""
}

variable "tags" {
  description = "Tags applied to every resource."
  type        = map(string)
  default     = {}
}
