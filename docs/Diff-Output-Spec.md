# Difference in Docs: Diff Output Spec

**Spec version:** 1.0

## Purpose

Difference in Docs (DiD) produces a JSON document (the "diff") for every eICR it processes that has a prior version with the same `setId`. The diff describes every change detected between the current eICR and the previous eICR, and indicates which of those changes are actionable per the active DiD configuration.

APHL uses the diff to decide whether to send the new eICR to the receiving jurisdiction(s).

## File format

- Format: JSON
- Encoding: UTF-8
- One diff file per eICR comparison
- File name: `diff_v{previousVersion}_to_v{currentVersion}_{manifestIndex}.json`
- Storage location: beside the augmented eICR under its `DIDOutputV2/` path

## Top-level schema

| Field | Type | Required | Description |
| --- | --- | --- | --- |
| `specVersion` | string | Yes | Version of this output spec. |
| `generatedAt` | string | Yes | Timestamp (ISO 8601) of when the diff was produced. |
| `configurationId` | string | Yes | Identifier of the DiD configuration used to evaluate actionability. |
| `configurationVersion` | string | Yes | Version of the configuration used. |
| `configurationDisplayName` | string | Optional | Human-readable name of the configuration used. |
| `setId` | string | Yes | The shared eICR set ID for the two documents compared. |
| `currentDocument` | object | Yes | See [Document object](#document-object). The eICR currently being processed. |
| `previousDocument` | object | Yes | See [Document object](#document-object). The prior eICR being compared against. |
| `hasDetectedChanges` | boolean | Yes | `true` if any changes were detected before actionability evaluation. |
| `hasActionableChanges` | boolean | Yes | Flag used by APHL to decide whether to send the new eICR to the receiving jurisdiction(s). `true` if any entry in `changes` has `isActionable: true`. (Technically optional, but clearer for APHL to just look at one boolean value than check the list of changes) |
| `changes` | array of [Change](#change-object) | Yes | May be empty if no changes were detected. |

### Document object

| Field | Type | Required | Description |
| --- | --- | --- | --- |
| `documentId` | string | Yes | The eICR clinical document ID. |
| `versionNumber` | string | Yes | The eICR version number. |

### Change object

| Field | Type | Required | Description |
| --- | --- | --- | --- |
| `changeType` | enum | Yes | One of `added`, `updated`, `deleted`. |
| `xPath` | string | Yes | XPath to the changed node. See [XPath Document Id](#xpath-document-id) below. |
| `xPathDocumentId` | string | Yes | The `documentId` of the eICR that the `xPath` resolves against. Always equal to either the value of `currentDocument.documentId` or `previousDocument.documentId`. See [XPath Document Id](#xpath-document-id) below. |
| `isActionable` | boolean | Yes | Whether this change should contribute to APHL's decision to send the new eICR. |
| `actionabilityRuleId` | string or null | Yes | UUID of the rule or default behavior that determined `isActionable`. `null` when no rule applies. |
| `actionabilityRuleDisplayName` | string or null | Yes | Human-readable name of the rule or default behavior. `null` when no rule applies. |

When multiple applicable configuration rules match the same detected change,
the `changes` array contains one entry for each matching rule.

The reserved rule UUID for the default behavior that makes unmatched changes
actionable under an `IGNORE_LIST` configuration is
`b3bdf60f-e22a-4467-8e1d-c8d4df7c8df0` (display name:
`Default: actionable when no ignore rule matches`).

#### XPath Document Id

- For `added` and `updated` changes, `xPath` resolves against the current document. `xPathDocumentId` equals the value of `currentDocument.documentId`.
- For `deleted` changes, `xPath` resolves against the previous document (the node no longer exists in the current document). `xPathDocumentId` equals the value of `previousDocument.documentId`.
- Although `changeType` implies which document the `xPath` resolves against, including `xPathDocumentId` makes this explicit for downstream systems.

## Example

**Note**: the following mock data was generated based on the JSON schema, so the actual `xPath` values may not be realistic.

```json
{
  "outputSpecVersion": "1.0",
  "generatedAt": "2026-06-05T00:00:00Z",
  "configurationId": "44d9a0b0-3c0c-4f49-bd11-6f219c7cfa9b",
  "configurationVersion": "1",
  "configurationDisplayName": "did-default",
  "setId": "2.16.840.1.113883.19.5.99999.19",
  "currentDocument": {
    "documentId": "db734647-fc99-424c-a864-7e3cda82e704",
    "versionNumber": "3"
  },
  "previousDocument": {
    "documentId": "db734647-fc99-424c-a864-7e3cda82e703",
    "versionNumber": "2"
  },
  "hasDetectedChanges": true,
  "hasActionableChanges": true,
  "changes": [
    {
      "changeType": "updated",
      "xpath": "/ClinicalDocument/recordTarget/patientRole/patient/birthTime/@value",
      "xpathDocumentId": "db734647-fc99-424c-a864-7e3cda82e704",
      "isActionable": true,
      "actionabilityRuleId": "8b1f4a2e-3c5d-4e6f-9a7b-1c2d3e4f5a6b",
      "actionabilityRuleDisplayName": "Patient date of birth changed"
    },
    {
      "changeType": "added",
      "xpath": "/ClinicalDocument/component/structuredBody/component[3]/section/entry[2]",
      "xpathDocumentId": "db734647-fc99-424c-a864-7e3cda82e704",
      "isActionable": true,
      "actionabilityRuleId": "2d4e6f8a-1b3c-5d7e-9f0a-2b4c6d8e0f1a",
      "actionabilityRuleDisplayName": "Medication added"
    },
    {
      "changeType": "updated",
      "xpath": "/ClinicalDocument/component/structuredBody/component[4]/section/entry[3]",
      "xpathDocumentId": "db734647-fc99-424c-a864-7e3cda82e704",
      "isActionable": false,
      "actionabilityRuleId": null,
      "actionabilityRuleDisplayName": null
    },
    {
      "changeType": "deleted",
      "xpath": "/ClinicalDocument/component/structuredBody/component[5]/section/entry[1]",
      "xpathDocumentId": "db734647-fc99-424c-a864-7e3cda82e703",
      "isActionable": true,
      "actionabilityRuleId": "0e870a30-2745-4dbb-8e3e-2c6820441b27",
      "actionabilityRuleDisplayName": "Problem deleted"
    }
  ]
}
```

## Open questions

1. **Triggering and storage.** Should the JSON output be written to the same APHL bucket as the augmented eICR output? Should the presence of the JSON itself act as the trigger for downstream processing?
2. **No previous eICR.** What behavior should APHL expect if there is no previous eICR for DiD to diff against? Should a JSON output file still be created? Should the current eICR still be written to a DiD output bucket? Can DiD skip augmenting the current eICR since there is nothing to diff against?

## Post-MVP considerations

Currently out of scope for MVP.

- **Per-jurisdiction outputs.** If a patient living in CA gets tested for COVID in NY, then both CA and NY would receive the eCR. If CA and NY have different DiD configurations and a new eCR update comes in that is actionable for one jurisdiction but not the other, what will DiD and APHL need to change to accommodate that? Multiple augmented eICRs? Multiple diff output files? Update on the JSON output itself?
- **Coded vs. narrative changes.** Indicate whether the Change object refers to a change in a coded or narrative section. Some jurisdictions may only care about one or the other, so this could be helpful to add in the future.
