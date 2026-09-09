# Risk Exception Requests

When a new tag for the `dibbs-dev-did/lambda` container image is pushed to APHL’s Amazon Elastic Container Registry (ECR), APHL automatically scans the image for vulnerabilities. DevSecOps sends the scan results by email.

Although every new tag is scanned, risk exception requests are only necessary when:

1. An image is promoted to APHL’s production environment
2. The image scan identifies reportable vulnerabilities or vulnerabilities that cannot be remediated before the image is promoted to production.

Use the following template for new risk exception documents:

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