# Difference in Docs: Configuration Spec

**Spec version:** 1.0

## Purpose

Difference in Docs (DiD) uses a configuration file to determine which changes detected between eICR versions are actionable.

A configuration defines a set of rules that match changes based on XPath expressions. When a change matches a rule, DiD and the configuration determine whether that change contributes to APHL's decision to send the new eICR to the receiving jurisdiction(s).

## File format

* Format: JSON
* Encoding: UTF-8
* Storage location and distribution: The default configuration is stored as a flat file in the code repository. Post-MVP, custom configurations may be enabled and stored using some persistence layer (ex: DynamoDB).

## Top-level schema

| Field                      | Type                           | Required | Description                                                                                      |
| -------------------------- | ------------------------------ | -------- | ------------------------------------------------------------------------------------------------ |
| `specVersion`              | string                         | Yes      | Version of this configuration spec.                                                              |
| `id`                       | string                         | Yes      | Stable identifier for the configuration. Remains unchanged across configuration revisions.       |
| `displayName`              | string                         | Optional | Human-readable name for the configuration.                                                       |
| `mode`                     | [ConfigMode](#configmode-enum) | Yes      | How to treat rule XPath matches.                                                                 |
| `createdAt`                | string ISO-8601 timestamp      | Yes      | A UTC ISO 8601 timestamp of when the configuration was created.                                  |
| `rules`                    | array of [Rule](#rule-object)  | Yes      | Ordered list of actionability rules.                                                             |

### Rule object

| Field         | Type                                     | Required | Description                                                                       |
| ------------- | ---------------------------------------- | -------- | --------------------------------------------------------------------------------- |
| `id`          | string                                   | Yes      | UUID identifying the rule. Must be unique within the configuration.               |
| `displayName` | string                                   | Optional | Human-readable rule name.                                                         |
| `changeTypes` | array of [ChangeType](#changetype-enum)  | Yes      | Change types this rule applies to.                                                |
| `xpaths`      | array of string                          | Yes      | One or more XPath expressions used to match changed nodes.                        |

### `ConfigMode` enum

| Value         | Description                                                                      |
| ------------- | -------------------------------------------------------------------------------- |
| `WATCH_LIST`  | Changes matching rule XPaths are actionable. All other changes are inactionable. |
| `IGNORE_LIST` | Changes matching rule XPaths are inactionable. All other changes are actionable. |

### `ChangeType` enum

| Value     | Description             |
|-----------|-------------------------|
| `ADDED`   | An element was added.   |
| `UPDATED` | An element was changed. |
| `DELETED` | An element was deleted. |

### Rule evaluation

Rules are evaluated in the order they appear in the `rules` array. For each detected change, DiD determines the rule associated with the change. Actionability is then determined by the configured `mode`.

The matching rule's `id` and `displayName` are included in the Diff Output document as `actionabilityRuleId` and `actionabilityRuleDisplayName`.

### XPath matching

* XPath expressions identify locations within an eICR that should be considered by a rule.
* A rule matches when the changed node corresponds to one of the rule's XPath expressions.
* Attribute matching is not enabled for the default config of the MVP and may be implemented in a future version of this specification.

## Example

```json
{
  "specVersion": "1.0",
  "id": "44d9a0b0-3c0c-4f49-bd11-6f219c7cfa9b",
  "displayName": "Differene in Docs Default Config",
  "mode": "IGNORE_LIST",
  "createdAt": "2026-06-12T19:56:17Z",
  "rules": [
    {
      "id": "e654b542-c0bd-4166-8320-4e0a7651d612",
      "displayName": "Ignore Document Properties",
      "xpaths": [
        "/ClinicalDocument/realmCode",
        "/ClinicalDocument/typeId",
        "/ClinicalDocument/code",
        "/ClinicalDocument/id",
        "/ClinicalDocument/templateId"
      ],
      "changeTypes": ["UPDATED", "ADDED"]
    },
    {
      "id": "d92c9890-4a85-4b21-a6dd-57864ae40ccc",
      "displayName": "Date of Diagnosis",
      "xpaths": [
        "//encounter[templateId/@root=2.16.840.1.113883.10.20.22.4.49]/effectiveTime/low"
      ],
      "changeTypes": ["ADDED"]
    },
    {
      "id": "1f989163-596d-4eae-b2f2-8b9f00ddb635",
      "displayName": "Diagnoses",
      "xpaths": [
        "//encounter[templateId/@root=2.16.840.1.113883.10.20.22.4.49]/effectiveTime/low",
        "//encounter[templateId/@root=2.16.840.1.113883.10.20.22.4.49]/entryRelationship/act[templateId/@root=2.16.840.1.113883.10.20.22.4.80]/entryRelationship/observation[templateId/@root=2.16.840.1.113883.10.20.22.4.4]/value"
      ],
      "changeTypes": ["UPDATED", "ADDED"]
    }
  ]
}
```

## Open questions

1. **Rule precedence.** Is first-match-wins sufficient, or should multiple matching rules be allowed?
2. **Configuration lifecycle.** How are configuration versions published, activated, and retired? Can multiple versions be active simultaneously?
3. **Supported modes.** Are we only implementing the "IGNORE_LIST" mode for the MVP? The schema for this configuration does *not* lock us into this however; we can adapt the config to work with a "WATCH_LIST" mode as well.

## Post-MVP considerations

Currently out of scope for MVP.

* **Per-jurisdiction configurations.** Different jurisdictions may require different actionability rules and default behaviors, which could be supported by custom configurations.
* **Rule metadata.** Additional fields may be useful for rules to inform the diff output.
* **Attribute matching.** Support matching on attributes with XPaths.
