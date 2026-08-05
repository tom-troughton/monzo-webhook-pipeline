terraform {
  required_version = ">= 1.9"

  backend "azurerm" {
    resource_group_name  = "rg-monzode-tfstate"
    storage_account_name = "stmonzodetfstate130dc0"
    container_name       = "tfstate"
    key                  = "monzode.tfstate"
    use_azuread_auth     = true
  }

  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = "~> 4.0"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.6"
    }
    azuread = {
      source  = "hashicorp/azuread"
      version = "~> 3.0"
    }
  }
}

provider "azurerm" {
  features {}
}

provider "azuread" {}
