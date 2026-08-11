# DIBBs Difference in Docs

**General disclaimer** This repository was created for use by CDC programs to collaborate on public health related projects in support of the [CDC mission](https://www.cdc.gov/about/cdc/#cdc_about_cio_mission-our-mission).  GitHub is not hosted by the CDC, but is a third party website used by CDC and its partners to share information and collaborate on software. CDC use of GitHub does not imply an endorsement of any one particular service, product, or enterprise. 

## Related documents

* [Open Practices](open_practices.md)
* [Rules of Behavior](rules_of_behavior.md)
* [Thanks and Acknowledgements](thanks.md)
* [Disclaimer](DISCLAIMER.md)
* [Contribution Notice](CONTRIBUTING.md)
* [Code of Conduct](code-of-conduct.md)

## Overview

DIBBs Difference in Docs (DiD) is a project aimed at helping Public Health Authorities (PHAs) better leverage eCR by reducing the frequency of updates to electronic Initial Case Reports (eICRs). This will allow them to identify updates that are meaningful to their public health activities. 

## Getting Started

### Prerequisites

To start developing locally, you need the following tools installed:

* [just](https://just.systems/man/en/) `>=1.46.x` for running project commands
* [uv](https://docs.astral.sh/uv/getting-started/installation/) `>=0.10.x` for Python version, package, and project management
* [Docker](https://www.docker.com/) `>=28.3.x` for running containers

### Setup

View all available commands

```bash
just
```

Download Python dependencies and sync all packages:

```bash
just sync
```

To access the CLI, run:

```bash
just diff
```

### Local AWS pipeline

The committed `.env.local` contains a local-only `LOG_HASH_SALT` for Docker
Compose. Never use this value outside local development. Generate a new salt
with:

```bash
openssl rand -hex 32
```

Do not commit a generated non-local value or replace the committed local-only
value with it.

Start the local S3, SQS, EventBridge, DynamoDB, Lambda, and uploader services:

```bash
docker compose --env-file .env.local up --build --watch
```

View local AWS resources at `http://localhost:8080`.

Open `http://localhost:8081` and upload an eICR and RR. The uploader:

1. Stores the documents in local S3, and generates a manifest which is also stored in local S3.
2. Triggers an S3 notification to EventBridge -> SQS.
3. `sqs-poller.py` checks SQS, and invokes the lambda on new messages.

Stop the services with `docker compose down`.

## Telemetry semantics

The Difference in Docs Lambda emits structured logs and CloudWatch metrics
through AWS Lambda Powertools. Metrics use CloudWatch Embedded Metric Format
(EMF) and are written to standard output with the Lambda logs.

Telemetry is designed to support operational monitoring and aggregate analysis
without logging raw clinical documents or direct document identifiers.

The Lambda produces two kinds of metric output:

- One aggregate EMF object for every Lambda batch attempt. It includes all
  aggregate metric names even when their values are zero.
- Standalone `SectionChanges` and `EncountersProcessed` EMF objects only when a
  completed manifest contributed values for those dimensions.

### Processing-attempt and retry semantics

Failure counters describe failed processing attempts. Document, change, section,
encounter, and condition success counts describe contributions from manifests
that reached the completion-manifest boundary during a processing attempt. None
of these values are guaranteed counts of unique business events.

For each manifest, document results and condition counts are buffered locally.
They are merged into the Lambda batch statistics, and document/change logs are
emitted, only after the completion-manifest write succeeds. If an entry or the
completion write fails, the buffered success telemetry for that manifest is
discarded.

For example, assume the Lambda batch contains one SQS record for a manifest with
documents A, B, and C, and document B fails during entry processing:

```text
First attempt:
  A succeeds and is written
  B fails
  C is not attempted

Retry:
  A succeeds again
  B succeeds
  C succeeds
```

The first attempt emits a `processing_failure` log and an aggregate EMF object
that includes:

```text
ManifestsProcessed = 0
ManifestsFailed = 1
DocumentsProcessed = 0
DocumentsFailed = 1
ChangesAdded = 0
ChangesUpdated = 0
ChangesDeleted = 0
ChangesTotal = 0
BatchDurationMs = elapsed batch time
```

A contributes zero to the success counters and condition totals. The failed
attempt emits no `document_processed` or `xml_change` events and no standalone
section or encounter EMF objects. If the retry completes the manifest, A, B, and
C are included once in that retry's success telemetry.

A manifest attempt can fail after all its entries process successfully. After
processing the entries, the Lambda writes a `DIDComplete` manifest. If that
final write fails, the attempt increments `ManifestsFailed`, but not
`DocumentsFailed`, because no individual entry failed. Entry outputs may already
exist, but their buffered success telemetry is discarded until a retry reaches
the completion-manifest boundary.

This boundary removes the largest predictable source of duplicate success
telemetry, but it does not provide strict idempotency. AWS documents that Lambda
SQS event-source mappings process records at least once and that duplicate
processing can occur. A completed manifest can therefore still be counted again
when:

- Its SQS record is delivered again, including after an otherwise successful
  processing attempt.
- The same manifest is submitted in another SQS record.
- One Lambda batch contains multiple manifests, an earlier manifest completes,
  and a later manifest fails. Without partial SQS batch responses, the earlier
  record may be retried.

See [Using Lambda with Amazon
SQS](https://docs.aws.amazon.com/lambda/latest/dg/with-sqs.html) for the AWS
delivery and batching semantics.

The `document_correlation_key` remains stable across retries, so logs can be
grouped or approximately deduplicated by document version. CloudWatch EMF
metrics are additive and cannot use that key to retract a duplicate. Adding the
key as a metric dimension would also create unbounded cardinality.

The per-manifest telemetry boundary composes cleanly with partial SQS batch
responses if they are added later. Partial responses could isolate failures
between SQS records, but they would not make repeated delivery of the same
manifest idempotent. Exact unique-document metrics would require durable
deduplication at the chosen document or manifest boundary, plus careful
coordination between output writes, completion state, and telemetry publication.

The current metrics are therefore appropriate for workload, failure, and change
pattern analysis. They must not be interpreted as exact epidemiological or
unique-document volume.

The aggregate EMF object is emitted for both successful and failed Lambda batch
attempts. When processing fails partway through a batch, its success values
include only manifests that completed before the failure. A document is counted
as processed only after its containing completion-manifest write succeeds.

`DocumentsProcessed` and `DocumentsFailed` intentionally use different
boundaries. If A succeeds at the entry level and B fails, B increments
`DocumentsFailed`; A does not increment either document metric because its
manifest did not complete. This is mildly asymmetric but prevents A from being
counted once before the failure and again after a successful retry.

### Metric dimensions

All metrics use these dimensions:

- `service`: application name; defaults to `difference-in-docs`.
- `environment`: runtime environment; defaults to `prod`.

Some standalone metrics add one bounded dimension. Dimensions from a standalone
metric do not carry over to other metrics. The metrics namespace defaults to
`eICRDiff`.

### Aggregate metrics

These metrics have only `service` and `environment` dimensions.
All of them are present in the aggregate EMF object on both success and failure,
including when their value is zero.

| Metric | Unit | Meaning |
|---|---|---|
| `ManifestsProcessed` | Count | SQS records for which manifest processing returned successfully. |
| `ManifestsFailed` | Count | SQS records for which manifest processing raised an exception. |
| `DocumentsProcessed` | Count | Document entries merged into the batch statistics after their completion-manifest write succeeded. |
| `DocumentsFailed` | Count | Manifest-entry processing attempts that failed. Manifest-loading and completion-manifest failures do not increment this metric. |
| `ChangesAdded` | Count | Reported `ADDED` changes from documents in completed manifests. |
| `ChangesUpdated` | Count | Reported `UPDATED` changes from documents in completed manifests. |
| `ChangesDeleted` | Count | Reported `DELETED` changes from documents in completed manifests. |
| `ChangesTotal` | Count | Sum of added, updated, and deleted reported changes from completed manifests. |
| `BatchDurationMs` | Milliseconds | Elapsed time from batch-statistics initialization until final telemetry recording begins, on success or failure. Telemetry emission and flushing overhead is excluded. |

Change metrics count every change included in the diff output, including both
actionable and non-actionable changes. They do not count differences that the
diff engine does not report. When multiple applicable rules produce multiple
change records for one detected difference, each reported record contributes to
the metrics. A first-version or zero-change eICR in a completed manifest
increments `DocumentsProcessed` but contributes zero changes.

Average changes per processed document can be calculated over the same period,
for example `SUM(ChangesAdded) / SUM(DocumentsProcessed)`. The result describes
completed-manifest processing attempts and can still include repeated delivery
of a fully completed manifest.

### Section-change metric

`SectionChanges` counts actionable and non-actionable reported changes from
completed manifests that are associated with the nearest enclosing CDA section,
when that section carries a valid LOINC code. An invalid nearer section does not
fall back to a more distant enclosing section.

Its dimensions are `service`, `environment`, and `section_loinc_code`.

Changes are not deduplicated. If one document contains five reported changes in
the same section, that section receives a count of five. Changes outside a coded
section do not emit a `SectionChanges` metric. The section LOINC code is internal
telemetry metadata and is excluded from the serialized diff output.

No `SectionChanges` EMF object is emitted when no completed manifest contributed
a change with a valid section LOINC code.

### Encounter metric

`EncountersProcessed` counts documents in completed manifests by normalized
encounter type.

Its dimensions are `service`, `environment`, and `encounter_type`.
No `EncountersProcessed` EMF object is emitted when the Lambda batch contains no
completed document entries.

The encounter code is extracted from the original eICR header before
augmentation at:

```text
ClinicalDocument/componentOf/encompassingEncounter/code
```

Only bounded normalized values become metric dimensions:

| Source code | Metric value |
|---|---|
| `AMB` | `ambulatory` |
| `EMER` | `emergency` |
| `IMP`, `ACUTE`, `NONAC` | `inpatient` |
| `OBSENC` | `observation` |
| `PRENC` | `preadmission` |
| `SS` | `short_stay` |
| `HH` | `home_health` |
| `FLD` | `field` |
| `VR` | `virtual` |
| `PHC2237` | `external_historical` |
| Missing or incomplete code | `unknown` |
| Present but unsupported code and code-system combination | `other` |

The mapping is based on the [HL7 ActEncounterCode value
set](https://terminology.hl7.org/7.0.0/ValueSet-v3-ActEncounterCode.html), but
the reporting taxonomy is provisional. Domain owners must confirm whether
categories such as `observation` and `short_stay` should remain separate or roll
into a broader category such as `inpatient`. Changes to this mapping affect
metric continuity and should be documented with an effective date.

### Structured log events

#### `document_processed`

Emitted once per document only after every entry-level write and the
completion-manifest write succeed for the containing manifest. A completed
manifest can produce this event again if its SQS record is delivered again.

| Field | Meaning |
|---|---|
| `document_correlation_key` | Deterministic pseudonymous key for one set ID and version-number combination. |
| `version_number` | Plain document version number. |
| `unique_condition_count` | Number of unique coded conditions extracted from the RR. |

Condition codes themselves are never included in this correlated event.

#### `xml_change`

Emitted once per actionable or non-actionable reported change after the
containing manifest completes. A completed manifest can produce the same event
again if its SQS record is delivered again. Actionability is not included in
this log event.

| Field | Meaning |
|---|---|
| `document_correlation_key` | Pseudonymous document key. |
| `version_number` | Document version number. |
| `change_type` | `ADDED`, `UPDATED`, or `DELETED`. |
| `change_path` | Structural XPath with numeric positional predicates removed. |

The serialized diff XPath remains unchanged. The clinical document ID and
`xpathDocumentId` are never logged. The logged path originates from the
structural XPath, which contains namespace-prefixed element steps and numeric
positions rather than attribute or value-bearing predicates; the numeric
positions are then removed for logging.

#### `processing_failure`

Emitted at one of the bounded application-processing failure stages.

| Field | Meaning |
|---|---|
| `failure_stage` | Bounded stage where processing failed. |
| `error_type` | Exception class name only. |
| `document_correlation_key` | Included only when it was safely available before the failure. |

Allowed failure stages are `telemetry_config`, `manifest_load`, `document_load`,
`diff`, `augmentation`, `output_write`, and `completion_write`.

Failure logs do not include exception messages, original tracebacks, XML, S3
keys, Lambda events, raw set IDs, or clinical document IDs. The propagated
exception is sanitized so sensitive exception content is not logged
automatically.

#### `documents_processed_by_condition`

Emitted once per condition-code and code-system pair represented by documents in
completed manifests in the Lambda batch. These events are written when the
handler exits, including when a later manifest in the same Lambda batch fails.

| Field | Meaning |
|---|---|
| `condition_code` | Coded condition value extracted from the RR. |
| `condition_code_system` | OID identifying the coding system. |
| `documents_processed_count` | Number of documents in completed manifests containing that condition. |

Conditions are deduplicated within each RR by code and code system. Multiple
occurrences of the same condition in one RR contribute one processed document.
Condition counts buffered for a manifest are discarded if any entry or
the completion-manifest write fails.

These events deliberately contain no document correlation key, version number,
or other document-level identifier. However, batch-level condition events remain
temporally linkable within the shared Lambda log stream. Their longer-term
handling, including possible small-cell suppression or different aggregation
windows, remains subject to privacy guidance.

### Document correlation keys

Direct document identifiers are not logged. `document_correlation_key` is
generated using HMAC-SHA256 over the set ID and version number with
`LOG_HASH_SALT`, then truncated to 32 hexadecimal characters.

The key:

- Is deterministic for the same set ID, version number, and salt.
- Remains stable across retries while the salt is unchanged.
- Is different for different document versions.
- Does not expose the salt or raw set ID.
- Is used only to correlate telemetry events for the same document version.

`LOG_HASH_SALT` is required and must contain at least 32 bytes. A missing or
undersized salt causes processing to fail before document reads or writes.
Changing the salt breaks correlation continuity. Local generation instructions
are documented above.

### Example Logs Insights queries

Most common reported change locations:

```text
fields change_path, change_type
| filter message = "xml_change"
| stats count(*) as changes by change_path, change_type
| sort changes desc
| limit 25
```

Failures by bounded stage and exception type:

```text
fields failure_stage, error_type
| filter message = "processing_failure"
| stats count(*) as failures by failure_stage, error_type
| sort failures desc
```

Documents processed by condition:

```text
fields condition_code_system, condition_code, documents_processed_count
| filter message = "documents_processed_by_condition"
| stats sum(documents_processed_count) as documents_processed
  by condition_code_system, condition_code
| sort documents_processed desc
```

Approximate distinct completed document versions and repeated success events:

```text
fields document_correlation_key
| filter message = "document_processed"
| stats count(*) as processing_events,
        countDistinct(document_correlation_key) as approximate_document_versions
```

`countDistinct` is approximate, and a changed `LOG_HASH_SALT` prevents keys from
matching across the change.

### Deferred telemetry decisions

- EHR vendor metrics require a canonical vendor allowlist, alias normalization,
  and an approved rule for selecting a vendor when an eICR contains multiple
  authoring devices.
- EHR version telemetry has not been enabled.
- The encounter taxonomy requires domain-owner approval.
- Condition-code aggregation and small-cell handling remain subject to privacy
  guidance.
- Exact unique-document metrics require durable deduplication and coordinated
  telemetry publication at the selected document or manifest boundary.

## Development

### Type checking / Linting / Formatting

Check types:

```bash
just ty
```

Run linter:

```bash
just check
```

Apply formatting:
```bash
just format
```

### Running tests

All unit tests can be run with pytest:

```bash
just test
```

Unit tests for a specific package can be ran by passing a path to pytest:

```bash
just test packages/cli
```

### Adding dependencies

Additional dependencies can be added to the root workspace with `uv`:

```bash
uv add httpx

# adding a dev dependency
uv add --dev pytest
```

Dependencies can be added to workspace packages by specifying the package using `--package <name>`:

```bash
uv add --package did_lambda aws-lambda-powertools
```

## Architecture

### Structurizr

The Difference in Docs project uses [Structurizr](https://docs.structurizr.com/) to visualize the software architecture using the [C4 Model](https://c4model.com/).

To run Structurizr locally, you'll first need to have [Docker](https://www.docker.com/) installed and then run:

```bash
just arch view
```

View it in your browser at http://localhost:7268.

## Repository Structure

This project is a [uv workspace](https://docs.astral.sh/uv/concepts/projects/workspaces/) consisting of multiple Python packages.

```
├── packages
│   ├── cli                   # Command-line interface package
│   │   ├── pyproject.toml
│   │   └── src/
│   ├── core                  # Core Difference in Docs logic and shared modules
│   │   ├── pyproject.toml
│   │   └── src/
│   └── did_lambda                # AWS Lambda package
│       ├── pyproject.toml
│       └── src/
├── pyproject.toml            # Workspace config (dependencies, linter rules, metadata)
└── uv.lock                   # Lockfile for all workspace dependencies
```

## Public Domain Standard Notice
This repository constitutes a work of the United States Government and is not
subject to domestic copyright protection under 17 USC § 105. This repository is in
the public domain within the United States, and copyright and related rights in
the work worldwide are waived through the [CC0 1.0 Universal public domain dedication](https://creativecommons.org/publicdomain/zero/1.0/).
All contributions to this repository will be released under the CC0 dedication. By
submitting a pull request you are agreeing to comply with this waiver of
copyright interest.

## License Standard Notice
The repository utilizes code licensed under the terms of the Apache Software
License and therefore is licensed under ASL v2 or later.

This source code in this repository is free: you can redistribute it and/or modify it under
the terms of the Apache Software License version 2, or (at your option) any
later version.

This source code in this repository is distributed in the hope that it will be useful, but WITHOUT ANY
WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS FOR A
PARTICULAR PURPOSE. See the Apache Software License for more details.

You should have received a copy of the Apache Software License along with this
program. If not, see http://www.apache.org/licenses/LICENSE-2.0.html

The source code forked from other open source projects will inherit its license.

## Privacy Standard Notice
This repository contains only non-sensitive, publicly available data and
information. All material and community participation is covered by the
[Disclaimer](DISCLAIMER.md)
and [Code of Conduct](code-of-conduct.md).
For more information about CDC's privacy policy, please visit [http://www.cdc.gov/other/privacy.html](https://www.cdc.gov/other/privacy.html).

## Contributing Standard Notice
Anyone is encouraged to contribute to the repository by [forking](https://help.github.com/articles/fork-a-repo)
and submitting a pull request. (If you are new to GitHub, you might start with a
[basic tutorial](https://help.github.com/articles/set-up-git).) By contributing
to this project, you grant a world-wide, royalty-free, perpetual, irrevocable,
non-exclusive, transferable license to all users under the terms of the
[Apache Software License v2](http://www.apache.org/licenses/LICENSE-2.0.html) or
later.

All comments, messages, pull requests, and other submissions received through
CDC including this GitHub page may be subject to applicable federal law, including but not limited to the Federal Records Act, and may be archived. Learn more at [http://www.cdc.gov/other/privacy.html](http://www.cdc.gov/other/privacy.html).

## Records Management Standard Notice
This repository is not a source of government records, but is a copy to increase
collaboration and collaborative potential. All government records will be
published through the [CDC web site](http://www.cdc.gov).

## Additional Standard Notices
Please refer to [CDC's Template Repository](https://github.com/CDCgov/template) for more information about [contributing to this repository](https://github.com/CDCgov/template/blob/main/CONTRIBUTING.md), [public domain notices and disclaimers](https://github.com/CDCgov/template/blob/main/DISCLAIMER.md), and [code of conduct](https://github.com/CDCgov/template/blob/main/code-of-conduct.md).
