# Difference in Docs: Augmentation

## Purpose

Difference in Docs (DiD) compares versions of an electronic Initial Case
Report (eICR), decides which detected changes are actionable, and returns new "augmented" versions of the
documents that describe how DiD processed the current report.

Augmentation serves two related purposes:

1. **Document provenance.** It identifies the eICR and Reportability Response
   (RR) as outputs produced by DiD while preserving a link to every input in the
   augmentation chain.
2. **Diff communication.** It places coded markers in the eICR so a receiver can
   distinguish additions, updates, and selected significant changes
   without parsing the separate JSON diff output.

This document describes the current implementation of DiD eICR augmentation and the
reasoning behind it.

## Mental model

An augmented document is a new CDA document derived from an input document. DiD
does not modify the identity of the source document in storage. Instead, it creates a new
output documents and records the source identity in a `relatedDocument` element.

For each eICR/RR pair, DiD creates one augmentation run. The run captures:

- one timestamp used by both output documents;
- the original eICR's `setId`, used to derive both output set IDs; and
- the current eICR's `versionNumber`, used by both output documents

Sharing these values keeps the augmented eICR and RR visibly associated with the
same processing operation and the same clinical-case version.

## When augmentation runs

In the Lambda pipeline, DiD augments the current eICR and its refined RR after
loading the documents and, when a prior actionable eICR exists, generates a
diff. The pair is augmented even when there is no prior version to compare or
the diff contains no actionable changes.

An RR identified as a remainder or unrefined RR is copied to output without
augmentation. In that branch, DiD does not produce an augmented eICR.

The CLI follows the same eICR augmentation path, but currently uses a placeholder
jurisdiction identifier and does not augment an RR.

## Two layers of augmentation

DiD adds augmentation at two possible layers:

1. **Document-level augmentation** describes the transformation of the document
   as a whole. It gives the output a new identity, records when and by which tool
   it was produced, and preserves its relationship to the input document. This
   layer is applied to both the eICR and RR.
2. **Diff-result augmentation** describes the outcome of comparing eICR
   versions. It adds coded markers for actionable additions, updates, and
   selected domain-specific changes, or adds a header marker when no changes or
   no actionable changes were found. This layer is applied only to the eICR.

The layers are complementary. Document-level augmentation answers “which tool
transformed this document and when?”, while diff-result augmentation answers
“what kind of relevant change occurred here?”.

DiD represents both layers with CDA `author` elements. CDA permits multiple
authors at the document, section, and clinical-statement levels, so DiD can add
machine-readable metadata without overwriting the clinical authorship already
in the eCR. Using standard CDA structures also keeps the output consumable by
systems that validate or process CDA and do not understand a DiD-specific XML
extension.

### 1. Document-level augmentation

Document-level augmentation is always applied when the augmentation path runs.
It makes the output a distinct, attributable document and preserves its
lineage. It is applied to both the eICR and RR.

For each document, DiD:

1. Captures the input `id`,  `setId`, `versionNumber`, and all
   existing `relatedDocument[@typeCode='XFRM']` elements.
2. Adds the appropriate Data Augmentation Header template ID.
3. Replaces the document `id` with a deterministic DiD identifier.
4. Replaces `effectiveTime` with the augmentation timestamp.
5. Replaces or adds `setId` with a deterministic DiD set identifier.
6. Replaces or adds `versionNumber` with the current eICR's version.
7. Adds an augmentation `author` identifying DiD as the tool.
8. Restores the prior lineage and adds a new `relatedDocument` for the input
   that was just augmented.

```xml
<author>
  <time value="20260325120000+0000"/>
  <assignedAuthor>
    <id nullFlavor="NA"/>
    <addr nullFlavor="NA"/>
    <telecom nullFlavor="NA"/>
    <assignedAuthoringDevice>
      <softwareName code="document-differencing"
                    codeSystem="2.16.840.1.113883.10.20.15.2.7.1"
                    codeSystemName="eCRDataAugmentation"
                    displayName="Difference in Docs"/>
    </assignedAuthoringDevice>
  </assignedAuthor>
</author>
```

The `id`, `addr`, and `telecom` elements are present because they are required
by the CDA author structure. `nullFlavor="NA"` makes clear that those human
author attributes do not apply to an automated tool.

### 2. Diff-result augmentation

After document-level augmentation, DiD uses the diff output to add coded author
elements to the eICR. The RR does not receive diff-result markers.

Each marker uses the Difference in Docs Change Augmentation template:

| Field | Value |
| --- | --- |
| Template root | `2.16.840.1.113883.10.20.15.2.4.10` |
| Template extension | `2025-11-01` |
| Code system | `2.16.840.1.113883.10.20.15.2.7.1` |
| Code system name | `eCRDataAugmentation` |
| Tool code | `document-differencing` |
| Tool display name | `Difference in Docs` |

For example:

```xml
<author>
  <templateId root="2.16.840.1.113883.10.20.15.2.4.10"
              extension="2025-11-01"/>
  <functionCode code="did-update-detected"
                codeSystem="2.16.840.1.113883.10.20.15.2.7.1"
                codeSystemName="eCRDataAugmentation"/>
  <time value="20260325120000+0000"/>
  <assignedAuthor>
    <id nullFlavor="NA"/>
    <addr nullFlavor="NA"/>
    <telecom nullFlavor="NA"/>
    <assignedAuthoringDevice>
      <softwareName code="document-differencing"
                    codeSystem="2.16.840.1.113883.10.20.15.2.7.1"
                    codeSystemName="eCRDataAugmentation"
                    displayName="Difference in Docs"/>
    </assignedAuthoringDevice>
  </assignedAuthor>
</author>
```

## Function-code selection

Only actionable changes are candidates for individual diff marker augmentation.

| Situation | Function code | Placement |
| --- | --- | --- |
| No diff is available, or the diff reports zero changes | `did-no-change` | eICR header |
| Changes exist, but none is actionable | `did-no-actionable-change` | eICR header |
| Actionable addition | configured code, otherwise `did-add-detected` | nearest allowed location |
| Actionable update | configured code, otherwise `did-update-detected` | nearest allowed location |
| Deletion | no marker | the deleted node is absent from the current eICR |

A rule's `augmentationFunctionCode` takes precedence over the default based on
change type. This supports domain-specific codes such as
`did-patient-deceased`, `did-patient-birthTime`, `did-patient-name`, and
`did-encounter-closeTime`. Configured values are expected to come from the Data
Augmentation Tool Operation value set.

The distinction between “no change” and “no actionable change” matters:

- `did-no-change` means DiD has no reported changes to mark. In the current
  implementation, this also covers the first-version case where no comparison
  was performed because no baseline existed.
- `did-no-actionable-change` means differences were reported, but the active
  configuration classified all of them as non-actionable.

## Choosing where to put a diff marker

Not every CDA node can legally contain an `author`. The diff engine therefore
keeps an in-memory reference to the changed node as an augmentation anchor, and
the augmentation code searches for a valid container.

Allowed containers are a CDA `section` or one of these clinical statements:

- `act`
- `encounter`
- `observation`
- `observationMedia`
- `organizer`
- `procedure`
- `regionOfInterest`
- `substanceAdministration`
- `supply`

For a normal entry-level rule (`isHeaderLevel: false`), the search order is:

1. the changed node itself;
2. its descendants in document order; and
3. its ancestors, from nearest to farthest, excluding `ClinicalDocument`.

Checking descendants before ancestors is important for wrapper nodes such as
`entry`: it places the marker on the contained clinical statement rather than
on a broader section whenever possible.

For a header-level rule (`isHeaderLevel: true`), DiD checks only the changed node
and its ancestors, and permits `ClinicalDocument` as a container. This allows a
change under `recordTarget`, which cannot itself contain an author, to be marked
at the document header. The flag permits header placement; it does not force the
root when a nearer allowed clinical statement or section exists.

If no valid container is found, DiD skips the marker. Authors are inserted in
the schema-defined child order for the selected CDA element.

When multiple reported changes resolve to the same container and function code,
DiD emits only one direct-child marker for that combination. The duplicate check
also verifies that the existing author identifies Difference in Docs, so an
author from another tool is not accidentally treated as DiD's marker.

## Preserving lineage with `relatedDocument`

Replacing a document ID must not sever the connection to the source. DiD adds a
`relatedDocument typeCode="XFRM"` whose `parentDocument` identifies the input
that was just augmented.

If an input has already been augmented by another tool, DiD preserves all of
its existing `XFRM` related-document blocks verbatim and appends a new sibling
for the immediate input. The result is a chronological sibling chain:

```text
relatedDocument -> original document
relatedDocument -> first augmented document
relatedDocument -> next augmented document
...
```

The immediate input's `id` is always recorded. Its `setId` and `versionNumber`
are recorded when they existed on that input; missing values are not invented
inside the lineage block. For the first augmentation, the source authority is
set to `original-document`. For an already-augmented input, its authority is
retained, with documented fallbacks when an authority is missing.

This sibling shape avoids combining identifiers from different transformations
inside one `parentDocument` and preserves the order and identity of each step in
the transformation chain.

## Relationship to the JSON diff output

XML augmentation and the JSON diff output are complementary:

- The augmented XML keeps provenance and high-value change signals attached to
  a valid CDA document.
- The JSON diff contains the detailed list of detected changes, XPaths,
  actionability decisions, and configuration metadata.

Consumers should use the JSON output when they need a complete accounting of
the comparison. The XML markers are intentionally selective: non-actionable
individual changes, deletions, and changes without a valid author container are
not represented as individual augmentation authors.

## Current limitations and edge cases

- **Deleted nodes cannot receive markers.** They are absent from the current
  eICR. The deletion remains available in the JSON diff output.
- **Some actionable changes may be unplaceable.** If neither the anchor nor an
  eligible descendant or ancestor can contain an author, the marker is skipped.
- **No summary is added when actionable changes exist but none can be marked.**
  For example, an all-deletion actionable diff does not receive
  `did-no-actionable-change`, because the changes are actionable; it also has no
  entry marker, because the changed nodes no longer exist.
- **A missing diff and a zero-change diff share `did-no-change`.** This includes
  a first eICR version for which no comparison was performed.

## Implementation map

The main implementation lives in
`packages/core/src/core/augment.py`:

- `create_augmentation_run` captures pair-wide metadata.
- `augment_eicr_in_place` applies document and diff-result augmentation to an
  eICR.
- `augment_rr_in_place` applies document augmentation to an RR.
- `_process_diff_output_changes` filters and places diff-result markers.
- `_find_best_author_allowed_element` implements container selection.
- `_create_diff_author_element` builds the change-author XML shape.

The Lambda integration is in
`packages/did_lambda/src/did_lambda/lambda_function.py`, and the CLI integration
is in `packages/cli/src/cli/main.py`. Unit coverage for the augmentation
contract is in `packages/core/test/unit/test_augment.py`.
