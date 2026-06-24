# Difference in Docs: Storage Architecture

**Spec version:** 1.0

## Purpose

Difference in Docs requires persistence between Lambda executions to track previously seen eICR documents, identify their version numbers, and retrieve past files from S3.

This document defines the schema, partition/sort keys, attributes, and query patterns for the DynamoDB storage layer we intend to use for Difference in Docs.

## DynamoDB Table Design

For the purposes of Difference in Docs, we can utilize a single DynamoDB table: `did-eicr-record` (or environment-specific s like `did-eicr-record-dev`).

### Primary Key

DynamoDB supports either a single primary key (composing of just the Partition Key), or a composite primary key (composing of the Partition Key + the Sort Key). For this spec, we will use the composite primary key as follows:

* **Partition Key:** `setId` (string)
  * The unique identifier for a set of related clinical documents. All versions of an eICR share the same `setId`.
* **Sort Key:** `versionNumber` (number)
  * The version of the document. Storing this as a **Number** enables sorting and range queries (ex: retrieving versions lower than the current version number).
  
[More info on DynamoDB Primary Keys](https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/HowItWorks.CoreComponents.html).

### Table Schema

| Attribute | DynamoDB Type | Required | Description |
| --- | --- | --- | --- |
| `setId` | string (S) | Yes | **Partition Key**. The shared eICR set ID. |
| `versionNumber` | number (N) | Yes | **Sort Key**. The version of this specific eICR document. |
| `documentId` | string (S) | No | The clinical document ID unique to this specific version. |
| `s3Address` | string (S) | No | The S3 URI (ex: `s3://did-eicr-bucket/eICR.xml`) where the raw eICR is stored. |
| `s3AddressRR` | string (S) | No | The S3 URI (ex: `s3://did-eicr-bucket/RR.xml`) where the raw RR is stored. |
| `s3AddressDiffOutput` | string (S) | No | The S3 URI (ex: `s3://did-diff-bucket/DiffOutput.json`) where the diff output (if any) is stored. |
| `processedAt` | string (S) | No | Timestamp (ISO-8601) indicating when the document was processed by the Lambda. |
| `isActionable` | boolean (BOOL) | No | `true` if the diff between this document and its baseline predecessor was evaluated as containing actionable changes. For the initial version, this defaults to `true`. |
| `comparedToVersion` | number (N) | No | The version number of the document this version was compared against. Null or missing for the initial version of a set. |

Note that DynamoDB only enforces Primary Key attributes; other attributes are nullable.

[More info on DynamoDB AttributeValues](https://docs.aws.amazon.com/amazondynamodb/latest/APIReference/API_AttributeValue.html).

---

## Querying and Writing

When a new message arrives for a document `D`, of setId `SET_ID` and of version `VERSION_NUMBER`:

1. From the new message, get the S3 Address of the eICR document and the S3 Address of the RR Document. Fetch the document `D` using the S3 Address, and parse it to retrieve the `setId`, `SET_ID` and the `versionNumber`, `VERSION_NUMBER`.

2. Query the table using the `setId` Partition Key and the `versionNumber` Sort Key to find earlier records where `isActionable` is `true`:

  ```
  aws dynamodb query \
    --table-name did-eicr-record \
    --key-condition-expression "setId = :setId AND versionNumber < :versionNumber AND isActionable = true" \
    --expression-attribute-values '{":setId":{"S":"$SET_ID"}, ":versionNumber":{"N":$VERSION_NUMBER}}' \
    --no-scan-index-forward \ # forces descending order, so the highest version number is returned first
    --endpoint-url <DYNAMODB_ENDPOINT>
  ```

3. Filter the results to retrieve the the latest earlier actionable record.
    * This can be done from within the Lambda.
    * Let this baseline document be `B` (if it exists).

4. Execute the diff.
    * If a baseline `B` is found, fetch `B` from S3, run the diff, and determine if `D` has actionable changes.
       * At this point, the diff will be output to the S3 bucket for diff outputs (ex: `s3://did-diff-bucket`)
    * If a baseline `B` is NOT found (meaning this is the first version we have seen for this `setId`, `SET_ID` that has `isActionable = true`), do not perform a diff. `D` is treated as the new initial baseline.

5. Once processed, the Lambda performs a `PutItem` to persist the new document to the `did-eicr-record` table:
    * Set `setId` to `SET_ID`.
    * Set `versionNumber` to `VERSION_NUMBER`.
    * Set `documentId` to the document's `id` root attribute.
    * Set `s3Address` to the S3 Address received in message metadata.
    * Set `s3AddressRR` to the RR S3 Address received in message metadata.
    * Set `s3AddressDiffOutput` to the S3 Address of the diff output (if any)
    * Set `processedAt` to ISO-8601 timestamp of current time.
    * Set `isActionable` to `true` if actionable changes were found (or if it is the initial version), otherwise `false`.
    * Set `comparedToVersion` to the version of the baseline used (if any).

---

## Example Scenario

Assuming raw eICR documents are stored flatly in the bucket:

```
s3://did-eicr-bucket/
├── eicr_set_SET_ID_A_v1.xml
├── eicr_set_SET_ID_A_v2.xml
└── eicr_set_SET_ID_A_v3.xml
```

This step-by-step example demonstrates what happens when `eicr_set_SET_ID_A_v3.xml` is uploaded.

1. An upstream system uploads the raw eICR to `s3://did-eicr-bucket/eicr_set_SET_ID_A_v3.xml`.

2. S3 sends an event notification containing the bucket name and file key to the SQS queue.

3. The SQS queue triggers the Difference in Docs Lambda.

4. The Lambda downloads the file from `s3://did-eicr-bucket/eicr_set_SET_ID_A_v3.xml`.

5. The Lambda parses the XML contents to extract the key metadata attributes:
    * `setId`: `"SET_ID_A"`
    * `versionNumber`: `3`
    * `documentId`: `"DOC_ID_C"`

6. The Lambda queries the `did-eicr-record` DynamoDB table to look for the last actionable predecessor. The results from the lookup are:

  ```jsonc
  {
    "Items": [
      {
        "setId": {"S": "SET_ID_A"},
        "versionNumber": {"N": 1},
        "documentId": {"S": "DOC_ID_A"},
        "s3Address": {"S": "s3://did-eicr-bucket/eicr_set_SET_ID_A_v1.xml"},
        "s3AddressRR": {"S": "s3://did-eicr-bucket/rr_set_SET_ID_A_v1.xml"},
        "s3AddressDiffOutput": {"NULL": true},
        "processedAt": {"S": "2026-06-20T17:06:10Z"},
        "isActionable": {"BOOL": true},
        "comparedToVersion": {"NULL": true}
      }
    ]
  }
  ```

Note:
    * In this example, the fact that we got version 1 would signify that version 2 had no actionable changes.
    * Since this is the earliest eICR in the bucket, it has no `comparedToVersion` or `s3AddressDiffOutput`.

7. The Lambda downloads the baseline file from the retrieved `s3Address` (`s3://did-eicr-bucket/eicr_set_SET_ID_A_v1.xml`).

8. The Lambda compares version 1 and version 3, generating the diff.

9. The generated diff detects actionable changes (`isActionable = true`).

10. The Lambda creates the diff output and its S3 address for storage in the diff bucket (`s3://did-diff-bucket/diff_set_SET_ID_A_v1-v3.json`).

11. Finally, the Lambda saves the record for version 3 in DynamoDB using `PutItem`:

  ```jsonc
  {
    "setId": {"S": "SET_ID_A"},
    "versionNumber": {"N": 3},
    "documentId": {"S": "DOC_ID_C"},
    "s3Address": {"S": "s3://did-eicr-bucket/eicr_set_SET_ID_A_v3.xml"},
    "s3AddressRR": {"S": "s3://did-eicr-bucket/rr_set_SET_ID_A_v3.xml"},
    "s3AddressDiffOutput": {"S": "s3://did-diff-bucket/diff_set_SET_ID_A_v1-v3.json"},
    "processedAt": {"S": "2026-06-22T17:06:10Z"},
    "isActionable": {"BOOL": true},
    "comparedToVersion": {"N": "1"},
  }
  ```

---

## Corner Cases and Technical Concerns

### 1. Out-of-Order Document Delivery

From the original ticket:

> We only want to compare the current file being processed to the last file that was marked as having a meaningful change. (Is this true considering out of order documents?)

Since document order is not guaranteed, the Lambda may receive versions out of order (ex: version 1, then version 3, and finally version 2).

If version 3 is processed before version 2, its query for `versionNumber < 3` will only see version 1. It will compare version 3 to version 1. When version 2 later arrives, its query for `versionNumber < 2` will find version 1.

*Proposed MVP Behavior:* We accept the gap, but how we handle following versions may require further discussion. Some ideas:

#### Completely Ignore the late eICR version

1. We first check if a newer versionNumber exists in the DB. If so, we do not process this eICR.
2. Version 3's diff remains as compared to Version 1.

Pros: Simpler solution, simple to implement
Cons: Any changes in version 2 are lost

#### Process the late eICR version and diff it anyway

1. We process the late eICR as normal, performing the diff of Version 2 against Version 1 anyway.
2. Version 3's diff remains as compared to Version 1.

* Example 1: v3 comes in right after v1. There are actionable changes. We mark v3 as `isActionable = true`. v2 comes in and is diffed against v1. v4 comes in, and is diffed against v3. (v2 is essentially skipped).

* Example 2: v3 comes in right after v1. There are NO actionables changes. We mark v3 as `isActionable = false`. v2 comes in and is diffed against v1. There are actionable changes. We mark v2 as `isActionable = true`. v4 comes in, and is diffed against v2.

* Example 3: v3 comes in right after v1. There are NO actionables changes. We mark v3 as `isActionable = false`. v2 comes in and is diffed against v1. There are NO actionable changes. We mark v2 as `isActionable = false`. v4 comes in, and is diffed against v1.

Pros: Ensures every version is processed, database reflects incoming version actionability accurately.
Cons: Moderately more complex, compute potentially wasted on unused versions, S3 bucket storage space wasted on potentially unused diff outputs

### 2. Concurrent Executions for the Same Set ID
If messages for version 2 and version 3 of the same `setId` are processed concurrently by two different Lambda executions, they might read/write to the database simultaneously.

---

## Open Questions

1. **Retention Policy:** Do we need to retain the history of all versions for a `setId` indefinitely? Should we periodically prune records?

2. **Handling Duplicate Messages:** Edge case. If the same document version is delivered twice, should the Lambda skip processing and return the existing diff S3 URL, or re-run the diff?

3. **S3 Storage Patterns:** Can we designate the S3 filenaming conventions with APHL? Will there be another S3 Bucket for Augmented eICRs?

4. **DynamoDB Table Structure**. DynamoDB is schema-less, so we can write any objects we want to it, so long as they conform to the Partition and Sort Keys. However, should we have a "version number" for the shape of an Item in the DB? Can it be part of the Partition Key? Alternatively, could we store all data in a single Map (M) attribute?
