# Security Risk Exception Request

**Date:** 2026-09-09

## dibbs-dev-did/lambda:0.3.4 image

### HIGH: CVE-2026-14456

| Field | Details |
|---|---|
| **Package** | openssl-fips-provider-latest |
| **Installed Version** | 3.5.7-2.amzn2023.0.1 |
| **Fix Available** | Yes - 3.5.7-2.amzn2023.0.2 |
| **Title** | CVE-2026-14456: When an OpenSSL QUIC server (Listener SSL object) processes valid QUIC Initial packets for unknown destination connection IDs, it can allocate and queue new incoming channels without enforcing any limit |
| **Reference** | https://alas.aws.amazon.com/AL2023/ALAS2023-2026-2088.html |

#### Risk Acceptance Justification

> _Why is this an acceptable risk?_

**Justification:**

The package is inherited from our base image `public.ecr.aws/lambda/python:3.14` as an Amazon Linux dependency. It is not installed or used directly by the application. Additionally, this exploit necessitates running an OpenSSL QUIC Server. The Difference in Docs lambda does not run an OpenSSL QUIC Server, and only runs in the context of an AWS Lambda Runtime Environment.

**Mitigating Controls:**

Difference in Docs runs as an event-driven AWS Lambda function and receives requests as Lambda invocation events rather than direct network connections. The Lambda itself or the AWS Lambda Runtime Environment does not expose a QUIC server.

**Remediation Timeline:**

Remediation depends on AWS publishing an updated `public.ecr.aws/lambda/python:3.14` base image containing the fixed `openssl-fips-provider-latest` version. Once available, we will rebuild and rescan our image.

### HIGH: GHSA-9g5q-2w5x-hmxf

| Field | Details |
|---|---|
| **Package** | `chi/v5` |
| **Installed Version** | `5.2.4` |
| **Fix Available** | Yes — upgrade to 5.3.0 |
| **Title** | chi Middleware Vulnerable to Potential IP Spoofing via `X-Forwarded-For` Header in `Request.RemoteAddr` Resolution |
| **Reference** | https://github.com/advisories/GHSA-9g5q-2w5x-hmxf |

#### Risk Acceptance Justification

> _Why is this an acceptable risk?_

**Justification:** 

Vulnerable chi/v5 code is embedded in AWS's local-only Lambda RIE (AWS Lambda Runtime Interface Emulator). RIE is not executed in deployed Lambda, and our application does not use chi or the RealIP middleware.

**Mitigating Controls:** 

When deployed, the image runs only in an AWS Lambda environment, where `AWS_LAMBDA_RUNTIME_API` is set. RIE is bypassed when `AWS_LAMBDA_RUNTIME_API` is present. This can be confirmed by building the image, and inspecting the lambda entrypoint using `docker run --rm --entrypoint /bin/sh dibbs-dev-did/lambda:latest -c 'cat /lambda-entrypoint.sh'`:

```sh
if [ -z "${AWS_LAMBDA_RUNTIME_API}" ]; then
  exec /usr/local/bin/aws-lambda-rie $RUNTIME_ENTRYPOINT
else
  exec $RUNTIME_ENTRYPOINT
fi
```

Further image scans will alert us if the vulnerability remains present in future builds.

**Remediation Timeline:** 

Remediation depends on AWS publishing an updated `public.ecr.aws/lambda/python:3.14` base image containing the fixed RIE dependencies. Once available, we will rebuild and rescan our image.

---

### HIGH: GHSA-rjr7-jggh-pgcp

| Field | Details |
|---|---|
| **Package** | `chi/v5` |
| **Installed Version** | `5.2.4` |
| **Fix Available** | Yes — upgrade to 5.3.0 |
| **Title** | chi's RealIP Middleware allows IP spoofing via unvalidated X-Forwarded-For header |
| **Reference** | https://github.com/advisories/GHSA-rjr7-jggh-pgcp |

#### Risk Acceptance Justification

> _Why is this an acceptable risk?_

**Justification:** 

Vulnerable chi/v5 code is embedded in AWS's local-only Lambda RIE (AWS Lambda Runtime Interface Emulator). RIE is not executed in deployed Lambda, and our application does not use chi or the RealIP middleware.

**Mitigating Controls:** 

When deployed, the image runs only in an AWS Lambda environment, where `AWS_LAMBDA_RUNTIME_API` is set. RIE is bypassed when `AWS_LAMBDA_RUNTIME_API` is present. This can be confirmed by building the image, and inspecting the lambda entrypoint using `docker run --rm --entrypoint /bin/sh dibbs-dev-did/lambda:latest -c 'cat /lambda-entrypoint.sh'`:

```sh
if [ -z "${AWS_LAMBDA_RUNTIME_API}" ]; then
  exec /usr/local/bin/aws-lambda-rie $RUNTIME_ENTRYPOINT
else
  exec $RUNTIME_ENTRYPOINT
fi
```

Further image scans will alert us if the vulnerability remains present in future builds.

**Remediation Timeline:** 

Remediation depends on AWS publishing an updated `public.ecr.aws/lambda/python:3.14` base image containing the fixed RIE dependencies. Once available, we will rebuild and rescan our image.