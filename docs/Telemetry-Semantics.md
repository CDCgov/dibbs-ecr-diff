# Telemetry semantics

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

## Processing-attempt and retry semantics

Each Lambda invocation must contain exactly one SQS record pointing to one
manifest. An invocation containing multiple records is rejected before any
manifest is loaded or processed. Each rejected record contributes one to
`ManifestsFailed`; document and change metrics remain zero.

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

See [Using Lambda with Amazon
SQS](https://docs.aws.amazon.com/lambda/latest/dg/with-sqs.html) for the AWS
delivery and batching semantics.

The `persistence_id_with_index` remains stable across retries of the same
unchanged manifest, so logs can be grouped or approximately deduplicated by
manifest entry. CloudWatch EMF metrics are additive and cannot use that field to
retract a duplicate. Adding it as a metric dimension would also create
unbounded cardinality.

Exact unique-document metrics would require durable deduplication at the chosen
document or manifest boundary, plus careful coordination between output writes,
completion state, and telemetry publication.

The current metrics are therefore appropriate for workload, failure, and change
pattern analysis. They must not be interpreted as exact epidemiological or
unique-document volume.

The aggregate EMF object is emitted for both successful and failed Lambda
invocations. A document is counted as processed only after its containing
completion-manifest write succeeds.

`DocumentsProcessed` and `DocumentsFailed` intentionally use different
boundaries. If A succeeds at the entry level and B fails, B increments
`DocumentsFailed`; A does not increment either document metric because its
manifest did not complete. This is mildly asymmetric but prevents A from being
counted once before the failure and again after a successful retry.

## Metric dimensions

All metrics use these dimensions:

- `service`: application name; defaults to `difference-in-docs`.
- `environment`: runtime environment; defaults to `prod`.

Some standalone metrics add one bounded dimension. Dimensions from a standalone
metric do not carry over to other metrics. The metrics namespace defaults to
`eICRDiff`.

## Aggregate metrics

These metrics have only `service` and `environment` dimensions.
All of them are present in the aggregate EMF object on both success and failure,
including when their value is zero.

| Metric | Unit | Meaning |
|---|---|---|
| `ManifestsProcessed` | Count | SQS records for which manifest processing returned successfully. |
| `ManifestsFailed` | Count | SQS records rejected by invocation validation or for which manifest processing raised an exception. |
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

## Section-change metric

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

## Encounter metric

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

## Structured log events

### `document_processed`

Emitted once per document only after every entry-level write and the
completion-manifest write succeed for the containing manifest. A completed
manifest can produce this event again if its SQS record is delivered again.

| Field | Meaning |
|---|---|
| `persistence_id_with_index` | Manifest persistence ID followed by the entry's zero-based index, separated by a colon. |
| `version_number` | Plain document version number. |
| `unique_condition_count` | Number of unique coded conditions extracted from the RR. |
| `changes_added` | Number of reported `ADDED` changes, whether actionable or non-actionable. |
| `changes_updated` | Number of reported `UPDATED` changes, whether actionable or non-actionable. |
| `changes_deleted` | Number of reported `DELETED` changes, whether actionable or non-actionable. |
| `changes_total` | Sum of the added, updated, and deleted changes. |

Condition codes themselves are never included in this correlated event.

### `xml_change`

Emitted once per actionable or non-actionable reported change after the
containing manifest completes. A completed manifest can produce the same event
again if its SQS record is delivered again. Actionability is not included in
this log event.

| Field | Meaning |
|---|---|
| `persistence_id_with_index` | Manifest persistence ID and zero-based entry index. |
| `version_number` | Document version number. |
| `change_type` | `ADDED`, `UPDATED`, or `DELETED`. |
| `change_path` | Structural XPath with numeric positional predicates removed. |

The serialized diff XPath remains unchanged. The clinical document ID and
`xpathDocumentId` are never logged. The logged path originates from the
structural XPath, which contains namespace-prefixed element steps and numeric
positions rather than attribute or value-bearing predicates; the numeric
positions are then removed for logging.

### `processing_failure`

Emitted at one of the bounded application-processing failure stages.

| Field | Meaning |
|---|---|
| `failure_stage` | Bounded stage where processing failed. |
| `error_type` | Exception class name only. |
| `persistence_id_with_index` | Included for entry-level failures after the manifest has loaded. |

Allowed failure stages are `manifest_load`, `document_load`, `diff`,
`augmentation`, `output_write`, and `completion_write`.

Failure logs do not include exception messages, original tracebacks, XML, S3
keys, Lambda events, raw set IDs, or clinical document IDs. The propagated
exception is sanitized so sensitive exception content is not logged
automatically.

### `documents_processed_by_condition`

Emitted once per condition-code and code-system pair represented by documents in
the completed manifest. These events are written when the handler exits.

| Field | Meaning |
|---|---|
| `condition_code` | Coded condition value extracted from the RR. |
| `condition_code_system` | OID identifying the coding system. |
| `documents_processed_count` | Number of documents in completed manifests containing that condition. |

Conditions are deduplicated within each RR by code and code system. Multiple
occurrences of the same condition in one RR contribute one processed document.
Condition counts buffered for a manifest are discarded if any entry or
the completion-manifest write fails.

These events deliberately contain no `persistence_id_with_index`, version
number, or other document-level identifier. However, batch-level condition
events remain temporally linkable within the shared Lambda log stream. Their
longer-term handling, including possible small-cell suppression or different
aggregation windows, remains subject to privacy guidance.

## Manifest-entry persistence identifiers

Raw set IDs and clinical document IDs are not logged.
`persistence_id_with_index` is constructed as
`<manifest-persistence-id>:<zero-based-entry-index>`. For example, entry zero in
manifest `2026/08/12/550e8400-e29b-41d4-a716-446655440000` is logged as
`2026/08/12/550e8400-e29b-41d4-a716-446655440000:0`.

The value:

- Remains stable across retries of the same unchanged manifest.
- Is different for each entry in a manifest.
- Correlates telemetry events for one manifest entry.
- Does not identify the same eCR when it arrives in a different manifest.
- Changes if the manifest receives a different persistence ID or its entries are
  reordered.
- Exposes the operational manifest persistence ID in application logs, but not
  the raw set ID or clinical document ID.

This field replaces the previous salted set-ID-and-version correlation key.
Values written before and after this telemetry schema change cannot be matched
to each other through the correlation field.

## Example Logs Insights queries

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

Approximate distinct completed manifest entries and repeated success events:

```text
fields persistence_id_with_index
| filter message = "document_processed"
| stats count(*) as processing_events,
        countDistinct(persistence_id_with_index) as approximate_manifest_entries
```

`countDistinct` is approximate. The same eCR arriving in a different manifest
has a different `persistence_id_with_index` and is counted as a different entry.

## Deferred telemetry decisions

- EHR vendor metrics require a canonical vendor allowlist, alias normalization,
  and an approved rule for selecting a vendor when an eICR contains multiple
  authoring devices.
- EHR version telemetry has not been enabled.
- The encounter taxonomy requires domain-owner approval.
- Condition-code aggregation and small-cell handling remain subject to privacy
  guidance.
- Exact unique-document metrics require durable deduplication and coordinated
  telemetry publication at the selected document or manifest boundary.
