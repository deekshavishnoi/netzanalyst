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
  description = "Azure region. Keep everything in one region to avoid egress charges."
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
  default     = "gpt-5.4-mini"
}

variable "model_name" {
  description = <<-EOT
    Foundry model to deploy. Taken from the project brief and NOT yet verified
    against what the Azure trial can actually deploy — confirm availability in
    the target region before the first apply.
  EOT
  type        = string
  default     = "gpt-5.4-mini"
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
