# ApexCloud Enterprise Labs — Privacy & Data Security Policy

**Effective Date:** November 11, 2026  
**Vendor:** ApexCloud Enterprise Labs  
**Applies To:** All Atlassian Forge Cloud applications published by ApexCloud Enterprise Labs, including:
1. **DocFlow Pro — Markdown & Table Hub for Confluence**
2. **ApproveFlow — Page Approval & Compliance for Confluence**
3. **VaultFields & Smart DoD Checklists for Jira**

---

## 1. Zero External Data Egress ("Runs on Atlassian")

All applications covered by this policy are architected and executed **100% natively within the Atlassian Forge serverless platform**:
- **No External Servers:** We do not operate any external backend servers, third-party databases, or external API proxies for these applications.
- **No External Network Calls:** Our application manifests (`manifest.yml`) declare zero external egress permissions. Customer content, Confluence pages, Jira issues, and vault fields never leave the Atlassian Cloud boundary.
- **No Third-Party Analytics or Telemetry:** We do not embed third-party tracking pixels, cookies, or external analytics scripts.

---

## 2. Data Storage, Encryption & Residency

- All application configuration, compliance approval records, role-restricted vault values, and checklist items are stored exclusively within **Atlassian Forge Encrypted Storage (`@forge/api` storage)** and native **Jira / Confluence Entity Properties**.
- Data residency, encryption at rest, and encryption in transit (TLS 1.3) are managed directly by Atlassian Cloud infrastructure in accordance with your organization's Atlassian Data Residency configuration.

---

## 3. Personal Data Processing (GDPR & CCPA Compliance)

- Our applications do **not** copy, export, or store personal data on any vendor-owned systems.
- Within your Atlassian Cloud instance, the applications only reference standard Atlassian user identifiers (`accountId` and display name provided by the Atlassian runtime) to attribute page approvals, checklist completions, and security audit trail entries.

---

## 4. Data Retention & Deletion

- Customers retain full ownership and control over all data stored inside their Atlassian Cloud tenant.
- Administrators and authorized users can modify or clear stored records directly from the application interface.
- Uninstalling the application or deleting the host Atlassian site removes application access in accordance with Atlassian Forge platform lifecycle policies.

---

## 5. Contact Us

For privacy, GDPR, SOC 2, or security inquiries, please contact our Data Protection & Support team at:  
**Email:** [mikrozar@gmail.com](mailto:mikrozar@gmail.com)  
**Support Portal:** [https://github.com/mikrozar-cell/cartlogic-app/blob/main/atlassian-support.md](https://github.com/mikrozar-cell/cartlogic-app/blob/main/atlassian-support.md)
