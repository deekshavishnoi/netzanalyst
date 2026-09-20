# Azure and Foundry setup — Dee's checklist

Everything here needs your Azure login, so it is yours to do, not mine. Work
top to bottom: step 1 blocks everything else.

Verified against Microsoft Learn on **2026-09-20**. Foundry changes fast —
re-check anything that looks wrong rather than trusting this file.

---

## ⚠️ Read this before you activate anything

Two findings change the plan in the brief.

### 1. An Azure free trial cannot deploy any LLM at all

The **$200 credit and the model quota are separate controls.** Free Trial,
Lightweight Trial and Azure Pass subscriptions start with **0 tokens-per-minute
quota for every GPT model in every region**, deliberately, to stop abuse. Every
model shows 0 TPM and deployment fails with "Quota Not Met" no matter how much
credit is left.

**The fix:** upgrade the subscription to **Pay-As-You-Go**. This *keeps* your
remaining free credit — you are not throwing the $200 away, you are unlocking
the quota that lets you spend it. A card is required, but the credit is spent
first.

> Sources:
> [quota limits](https://learn.microsoft.com/en-us/azure/foundry/openai/quotas-limits),
> [0-quota explanation](https://learn.microsoft.com/en-gb/answers/questions/5907451/free-trials-get-200-but-have-a-0-quota-limit-on-ll)

### 2. `gpt-5.4-mini` is not an agent-supported model

The brief specifies `gpt-5.4-mini` for every agent. It **is** deployable as
Global Standard Azure OpenAI in East US 2, Sweden Central, South Central US and
Poland Central — but it is **not on the agent-supported list** for Foundry Agent
Service, which only runs models onboarded and validated for agent workflows.
Since the whole design runs agents on Agent Service, that matters.

**Use `gpt-4.1-mini`**, which is agent-supported, the cheapest of the three, and
has the widest region coverage. Microsoft describes the 4.1 family as
"cost-effective models for general-purpose agent workloads" — exactly this
workload. The Terraform default is now `gpt-4.1-mini`.

The ladder, cheapest first. Start at the bottom, climb only if the evals justify
it — which *is* the model comparison the brief asks for in section 8:

| Model | Agent-supported | Notes |
|---|---|---|
| **`gpt-4.1-mini`** | ✅ | Cheapest, widest regions. **Start here.** |
| `gpt-5-mini` | ✅ | Stronger reasoning, fewer regions, may need gpt-5 registration |
| `gpt-5` | ✅ | Most capable, most expensive |
| `gpt-5.4-mini` | ❌ | Deployable as Azure OpenAI, but not for Agent Service |

## Why your Germany West Central deployment failed

You tried `gpt-4.1-mini` in **Germany West Central** and it did not deploy.

**The region is not the problem.** Microsoft's agent model/region table lists
`gpt-4.1-mini` as available in `germanywestcentral` under Global Standard. So
moving to Sweden Central **will not fix this on its own.**

The near-certain cause is the **0 TPM quota** described above. Your subscription
came from the AI-102/103 certification course, which is typically an Azure Pass
or trial-type offer — and the documentation says the zero-quota rule applies to
"Free Trials, Lightweight trial, **and Azure Pass** offer types". Zero quota
looks exactly like this: the model appears in the catalog, but deployment fails.

### Confirm it in 30 seconds

After `az login`:

```bash
az cognitiveservices usage list --location germanywestcentral --output table
```

If the GPT rows show a limit of **0**, it is the quota, not the region. Check
Sweden Central the same way before assuming a move helps:

```bash
az cognitiveservices usage list --location swedencentral --output table
```

And check what offer your subscription actually is:

```bash
az account show --query "{name:name, id:id, state:state, tenant:tenantId}" --output table
```

If the limits are 0 in both regions, **step 2 (upgrade to Pay-As-You-Go) is the
fix**, and it is the only fix. Trying more regions will keep failing.

### Timing: do not activate the trial yet

The 30-day clock and the credit expiry both start the moment you activate, and
the credit does not survive the 30 days. Your calendar is tight — German B2
Mon–Thu until 29 Oct, and you fly on 23 Oct.

**Activate only when you are ready to use Azure daily.** Everything built so far
runs locally for free, and Weeks 1–2 can largely be finished before the clock
starts. Pick the start date so that day 30 lands before 23 Oct.

---

## The checklist

### 1. Fill in the trial dates ⬜

Put the real start and end dates into the brief (section 2) and tell me, so the
plan can be scheduled against them.

- Trial start: `________`
- Trial end (start + 30 days): `________`
- Hard deadline (earlier of trial end and 23 Oct): `________`

### 2. Upgrade the subscription to Pay-As-You-Go ⬜

Portal → **Subscriptions** → your subscription → **Upgrade**.

Without this, step 4 fails and Week 2 cannot start. Confirm afterwards that the
subscription no longer says "Free Trial".

### 3. Set budget alerts — do this the same day ⬜

Portal → **Cost Management + Billing** → **Budgets** → **Add**.

Scope to the subscription, monthly, amount **$200**, with alerts at:

- **$50** (25%) ⬜
- **$100** (50%) ⬜
- **$150** (75%) ⬜

Send them to an email you actually read. This is your safety net once real
resources exist.

### 4. Confirm which model you can actually deploy ⬜

Go to the [Foundry model catalog filtered to agent-supported models](https://ai.azure.com/catalog/models?capabilities=agentsv2)
and check, for **Sweden Central**:

- [ ] Is `gpt-4.1-mini` listed as agent-supported? (expected: yes — this is the default)
- [ ] Is `gpt-5-mini` listed as agent-supported? (expected: yes)
- [ ] Is `gpt-5.4-mini` listed as agent-supported? (expected: no — if it now is,
      tell me and we use it, matching the brief)
- [ ] Run the two `az cognitiveservices usage list` commands above and tell me
      whether the GPT limits are 0 or non-zero. That single answer settles
      whether the blocker is quota or region.

### 5. Confirm a hosted agent can be created ⬜

Still in the portal, create a throwaway **prompt agent** with the model from
step 4 and send it one message in the playground.

This proves in five minutes that the quota, the model and Agent Service all
work on your subscription, before any Terraform runs. Delete it afterwards.

- [ ] Prompt agent answers in the playground
- [ ] **Screenshot** the model deployments page → `docs/screenshots/`
      (documentation checklist item)

### 6. Log in locally ⬜

The Azure CLI is installed (2.90.0). Run:

```bash
az login
```

```bash
az account show --output table
```

Then tell me the subscription ID and I will wire it into the Terraform.

### 7. Install Docker ⬜ (optional, not blocking)

Only needed to test the `docker compose up` path and to build the MCP container
image for Azure. Everything currently runs on the Homebrew Postgres instead.

[Docker Desktop](https://www.docker.com/products/docker-desktop/) or
[OrbStack](https://orbstack.dev/). Needs an admin password, so it is yours to run.

---

## What I have already done for you

| Item | State |
|---|---|
| Azure CLI installed | ✅ 2.90.0 |
| Terraform installed | ⚠️ temp copy only, for validation — not on your PATH |
| Your public IP for the Postgres firewall | ✅ looked up — put it in your local `terraform.tfvars`, which is gitignored. Deliberately not committed: a home IP does not belong in a public portfolio repo. Get it again any time with `curl -s https://api.ipify.org` |
| Terraform model default corrected | ✅ now `gpt-4.1-mini`, with the full ladder and reasoning in `variables.tf` |
| Region chosen | ✅ `swedencentral` — carries every model in the ladder, plus Postgres and Container Apps |
| Budget guardrails in code | ✅ Log Analytics capped at 1 GB/day; Container App scales to zero; Postgres on the smallest burstable tier |

## What stays true from the brief

Checked while verifying the above, so Week 2 is not built on a wrong assumption:

- **Hosted agents are real and GA**, and explicitly support **Microsoft Agent
  Framework** — the brief's choice is sound.
- **Custom remote MCP servers are supported** by Agent Service, authenticated
  with the agent's managed identity, so our MCP server plugs in as designed.
- **A2A v1.0 is generally available** with a documented endpoint how-to, so the
  optional last layer is real rather than preview guesswork.

## Still open

- `infra/terraform/foundry.tf` is deliberately empty until step 4 is answered.
  Once you confirm the model, I write the Foundry account, project and
  deployment against the current API version.
- **Nothing has been applied. No Azure resource exists. Nothing is billing.**
