# ApexCloud Enterprise Labs — Customer Support & SLA Policy

**Organization / Vendor:** ApexCloud Enterprise Labs  
**Supported Platform:** Atlassian Cloud (Confluence Cloud & Jira Cloud — Built on Atlassian Forge)  
**Supported Applications:**
- **DocFlow Pro** — Markdown Importer, Bulk Page Creator & Table Exporter for Confluence
- **ApproveFlow** — Version-Locked Page Approvals, Quorum Sign-Off & Compliance Audit Trail
- **VaultFields & Smart DoD Checklists** — Role-Based Encrypted Fields & Workflow Checklists for Jira

---

## 1. Support Channels & Contact Information

- **Primary Support Email:** [info@cab2web.com](mailto:info@cab2web.com)
- **Issue Tracker & Bug Reports:** [https://github.com/mikrozar-cell/cartlogic-app/issues](https://github.com/mikrozar-cell/cartlogic-app/issues)
- **Support Hours:** Monday – Friday, 08:00 – 18:00 CET (Central European Time), excluding public holidays.

---

## 2. Service Level Agreement (SLA) Response Targets

| Severity Level | Definition | Target Initial Response |
| :--- | :--- | :--- |
| **Level 1 — Critical (P1)** | Production application unavailable or blocking critical team workflows | **Within 4 business hours** |
| **Level 2 — High (P2)** | Major feature degraded with no immediate workaround | **Within 8 business hours** |
| **Level 3 — Medium (P3)** | Minor bug, formatting question, or configuration inquiry | **Within 24 business hours** |
| **Level 4 — Enhancement (P4)** | Feature request or general documentation question | **Within 48 business hours** |

---

## 3. Step-by-Step App Documentation, Testing Guides & Demo Videos

Full interactive documentation with screenshots and embedded demo videos is publicly available (no login required):
- **Full Documentation Hub:** [https://mikrozar-cell.github.io/b2b-ecommerce-saas-scrapers-n8n-clay/atlassian-docs.html](https://mikrozar-cell.github.io/b2b-ecommerce-saas-scrapers-n8n-clay/atlassian-docs.html)

### A. VaultFields & Smart DoD Checklists for Jira Cloud
- **Interactive Guide:** [atlassian-docs.html#vaultfields](https://mikrozar-cell.github.io/b2b-ecommerce-saas-scrapers-n8n-clay/atlassian-docs.html#vaultfields)
- **Walkthrough Demo Video (MP4):** [vaultfields_demo.mp4](https://mikrozar-cell.github.io/b2b-ecommerce-saas-scrapers-n8n-clay/atlassian/vaultfields_demo.mp4)
- **Prerequisites:** Jira Cloud project with the app installed (zero external server setup required; runs 100% on Atlassian Forge).
- **How to Access & Test (2 Entry Points):**
  1. **Jira Issue Panel:** Open any Jira issue → click **Apps** / **VaultFields & DoD Checklist** in the issue action bar.
  2. **Jira Project Page:** Open any Jira project → left sidebar (or **More**) → click **VaultFields RBAC & Checklist Templates**.
- **Key Workflows to Test:**
  1. **Role-Restricted Encrypted Vault Fields:** Enter a field name (e.g., `Client Margin`), value, category, and allowed role (`Administrators & SecOps`), then click **+ Save Encrypted Vault Field**. Switch the **Test RBAC View As** dropdown to verify role-based redaction/masking.
  2. **Smart Definition-of-Done (DoD) Checklists:** Select a preset template (e.g., `Production Release & Change Gate`) and click **Load Template**, or add custom mandatory/optional checklist items. Toggle checkboxes to see the live Workflow Gate status (`READY FOR DONE` / `BLOCKED`) and synced Jira Issue Property (`issue.properties['vaultfields_dod'].allMandatoryDone`).
  3. **Security & Checklist Audit Trail:** Inspect timestamped access and checklist events stored natively in Atlassian Forge KVS.

### B. DocFlow Pro: Markdown Importer & Table Exporter for Confluence Cloud
- **Interactive Guide:** [atlassian-docs.html#docflow](https://mikrozar-cell.github.io/b2b-ecommerce-saas-scrapers-n8n-clay/atlassian-docs.html#docflow)
- **Walkthrough Demo Video (MP4):** [docflow_demo.mp4](https://mikrozar-cell.github.io/b2b-ecommerce-saas-scrapers-n8n-clay/atlassian/docflow_demo.mp4)
- **How to Access & Test:**
  1. **Page Action:** Open any Confluence page → click **More Actions (`•••`)** in the top-right → **DocFlow — Markdown Import & Export**.
  2. **Space Bulk Hub:** Open any Confluence space → left sidebar **Apps** → **DocFlow Bulk Markdown Hub**.
  3. Paste or upload GitHub-Flavored Markdown (tables, code blocks, checklists) to import into native Confluence Storage XHTML, or export existing Confluence tables cleanly to RFC-4180 CSV/JSON.

### C. ApproveFlow: Version-Locked Page Approval & Audit for Confluence Cloud
- **Interactive Guide:** [atlassian-docs.html#approveflow](https://mikrozar-cell.github.io/b2b-ecommerce-saas-scrapers-n8n-clay/atlassian-docs.html#approveflow)
- **Walkthrough Demo Video (MP4):** [approveflow_demo.mp4](https://mikrozar-cell.github.io/b2b-ecommerce-saas-scrapers-n8n-clay/atlassian/approveflow_demo.mp4)
- **How to Access & Test:**
  1. **Page Byline:** Open any Confluence page → click **Page Approval & Sign-Off** directly below the page title.
  2. **Space Compliance Matrix:** Open any Confluence space → left sidebar **Apps** → **ApproveFlow Compliance Matrix**.
  3. Record a version-locked approval (bound to exact page version & SHA-256 content hash), edit the page to verify automatic `OUTDATED` invalidation, and export the SOC 2 / ISO 27001 CSV audit trail.

---

## 4. Architecture & Troubleshooting Note ("Runs on Atlassian")

All ApexCloud Enterprise Labs applications run **100% serverless inside the Atlassian Forge Cloud runtime** with **zero external network egress**. If you experience permission errors, verify in your Jira or Confluence Administration console that the latest app version is approved under **Connected Apps**.

