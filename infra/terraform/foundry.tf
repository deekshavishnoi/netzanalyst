# Microsoft Foundry account, project and model deployment.
#
# DELIBERATELY NOT WRITTEN YET.
#
# The brief's rule: "Foundry features change quickly, and several used here are
# in preview. Check the current Microsoft Learn docs before writing code against
# Foundry Agent Service, hosted agents, toolboxes or A2A."
#
# Writing azapi resources against a remembered preview API version is exactly
# how you get a plan that fails at apply time, or worse, one that succeeds and
# creates something that bills. So this file stays empty until the current API
# surface has been checked against Microsoft Learn.
#
# What goes here, once verified:
#
#   1. azurerm_ai_foundry (or azapi Microsoft.CognitiveServices/accounts with
#      kind = "AIServices") — the Foundry account.
#   2. azurerm_ai_foundry_project — the project the agents live in.
#   3. The model deployment for var.model_name / var.model_deployment_name,
#      with capacity pinned to var.model_capacity so spend is bounded.
#   4. A role assignment giving the agents' managed identity
#      "Azure AI Developer" on the project.
#
# Before writing any of it, confirm on the trial subscription:
#   - that var.model_name is actually deployable in var.location
#   - the current API version for each resource type
#   - whether azurerm covers these yet, or azapi is still required
#
# Agent definitions themselves are NOT Terraform's job — they are created by the
# Python deploy script in agents/deploy/ using the Foundry SDK, as the brief
# specifies.
