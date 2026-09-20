terraform {
  required_version = ">= 1.9.0"

  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = "~> 4.14"
    }
    # Foundry resources that azurerm does not cover yet are created with azapi.
    azapi = {
      source  = "Azure/azapi"
      version = "~> 2.2"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.6"
    }
  }
}

provider "azurerm" {
  features {
    key_vault {
      # Keep soft-deleted vaults recoverable: purging on destroy would block
      # re-creating a vault with the same name for 90 days.
      purge_soft_delete_on_destroy = false
    }
    resource_group {
      # Refuse to delete a resource group that still contains anything the
      # state does not know about.
      prevent_deletion_if_contains_resources = true
    }
  }
}

provider "azapi" {}
