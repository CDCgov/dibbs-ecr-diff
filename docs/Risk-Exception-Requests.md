# Risk Exception Requests

When a new tag for the `dibbs-dev-did/lambda` container image is pushed to APHL’s Amazon Elastic Container Registry (ECR), APHL automatically scans the image for vulnerabilities. DevSecOps sends the scan results by email.

Although every new tag is scanned, risk exception requests are only necessary when:

1. An image is promoted to APHL’s production environment
2. The image scan identifies reportable `CRITICAL`/`HIGH` vulnerabilities or `CRITICAL`/`HIGH` vulnerabilities that cannot be remediated before the image is promoted to production.

## Generating the template

You can generate a pre-filled risk exception document by running the **Generate Risk Exception Document** GitHub Actions workflow. The workflow builds the lambda image at a chosen ref, scans it with Trivy, and produces a `risk-exception.md` pre-filled with the CVE details. You will still need to complete the justification, mitigating controls, and remediation timeline for each finding.

To run it:

1. Go to **Actions → Generate Risk Exception Document** and click **Run workflow**.
2. Optionally enter a branch, tag, or full commit SHA in the **ref** field. Leave it blank to use the ref selected in "Use workflow from".
3. Once the run completes, download the `risk-exception-did-lambda` artifact from the run summary. It contains the generated `risk-exception.md`.

The workflow scans for `CRITICAL` and `HIGH` severities. If no vulnerabilities are found at those severities, no document is produced.

> **Note:** This workflow runs its own Trivy scan, which may not exactly match the scan results APHL DevSecOps sends. Always cross-check the generated document against the vulnerabilities in APHL's email and add any that are missing.

## Manual template

To write the document by hand, use the following template:

```
# Security Risk Exception Request

**Date:** YYYY-MM-DD

## dibbs-dev-did/lambda:<image_tag> image 

### <SEVERITY>: CVE-XXX-XXXXX

| Field | Details |
|---|---|
| **Package** | <package_name> |
| **Installed Version** | <version_number> |
| **Fix Available** | <yes_or_no> |
| **Title** | <vulnerability_title> |
| **Reference** | <nvd_URL> |

#### Risk Acceptance Justification

> _Why is this an acceptable risk?_

**Justification:** 

**Mitigating Controls:** 

**Remediation Timeline:** 
```