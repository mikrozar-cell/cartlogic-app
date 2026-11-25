# ApexCloud Enterprise Labs — Security Policy & Practices

**Vendor:** ApexCloud Enterprise Labs  
**Security Contact Email:** [info@cab2web.com](mailto:info@cab2web.com)  
**Applies To:** All ApexCloud Enterprise Labs Atlassian Cloud applications (**DocFlow Pro for Confluence**, **ApproveFlow for Confluence**, and **VaultFields & Smart DoD Checklists for Jira**)  
**Last Updated:** November 25, 2026

---

## 1. Serverless Architecture ("Runs on Atlassian" — Zero External Egress)

All ApexCloud Enterprise Labs apps are built **100% natively on Atlassian Forge**:
- **Zero External Servers:** Our applications do not host, transmit, proxy, or mirror any customer data on third-party servers.
- **Zero External Network Egress:** App manifests declare zero external fetch/egress endpoints; all execution occurs strictly inside Atlassian's isolated Forge runtime.
- **Data Residency:** Because all app state is stored exclusively inside Atlassian-managed **Forge Key-Value Storage (KVS)** and native Jira/Confluence entity properties, customer data automatically inherits the Atlassian site's configured data residency region and compliance posture.

---

## 2. Data Handling, Encryption & Access Control

- **Encryption in Transit & at Rest:** All internal API calls between the Forge runtime, Jira/Confluence REST APIs, and Forge Storage use TLS 1.2+ in transit and Atlassian-managed AES-256 encryption at rest.
- **Least-Privilege Scopes:** Every app requests only the minimum required OAuth 2.0 Forge scopes (e.g., `read:page:confluence`, `write:page:confluence`, `read:jira-work`, `write:jira-work`, `storage:app`).
- **Role-Based Access Control (RBAC):** Sensitive fields in VaultFields enforce server-side role verification inside Forge resolvers before returning field values to the client UI.
- **Strict Content Security Policy (CSP):** Custom UI bundles use external static stylesheets (`styles.css`) and local static resources (`resource:main-ui;icon.png`) with zero `unsafe-inline` styles or external scripts.
- **Data Retention & Deletion:** Uninstalling an app automatically revokes its Forge installation tokens, and customers can delete stored records at any time from the app UI or by contacting [info@cab2web.com](mailto:info@cab2web.com).

---

## 3. Vulnerability Management & Secure Development

- **Dependency Auditing:** All Node.js/Forge dependencies are audited via `npm audit` and `forge lint` prior to every production release.
- **Static & Automated Testing:** Core parsers, RBAC filters, and workflow gates are covered by automated unit tests before deployment to Forge `production`.
- **Patch & Remediation SLAs:**
  - **Critical (CVSS 9.0–10.0):** Patch deployed within **24 hours**
  - **High (CVSS 7.0–8.9):** Patch deployed within **72 hours**
  - **Medium (CVSS 4.0–6.9):** Patch deployed within **14 days**
  - **Low (CVSS 0.1–3.9):** Addressed in the next scheduled minor release

---

## 4. Security Incident Response & Responsible Disclosure

To report a security vulnerability or incident, email our monitored security team at **[info@cab2web.com](mailto:info@cab2web.com)** with `[SECURITY]` in the subject line.

- **Initial Acknowledgment:** Within **24 hours** (typically within 4 business hours, Mon–Fri 08:00–18:00 CET).
- **Investigation & Notification:** Confirmed security incidents affecting customer data are triaged immediately, patched via Forge production deployment, and communicated to affected customers and Atlassian Marketplace Security without undue delay.

---

*For privacy and GDPR data-processing details, see our separate [Privacy Policy](https://github.com/mikrozar-cell/cartlogic-app/blob/main/atlassian-privacy.md).*
