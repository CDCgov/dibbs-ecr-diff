# 2. Section-scoped, template-aware comparison

Date: 2026-10-27

Measured against `dibbs-ecr-diff` @ `0cca149`, `dibbs-ecr-refiner` `main` @ `8cb55264` and
`dibbs-star-wars-ecr-data` @ `c62ee32`.

## Status

Proposed. Revised 2026-11-18 for APHL's review: each `[!NOTE]` callout answers one of APHL's
questions (Q1-Q19, plus two on Input), and the callouts fold into the text when the ADR is
accepted. Our own questions to APHL are numbered DQ1-DQ8 so the two sets don't collide.

## Context and Problem Statement

DiD compares two versions of an eICR (same `setId`) and stamps the newer one with authors
that tell a public health agency (PHA) what changed. Today that is one whole-document diff:

- every element gets a stable key from a twelve-rank fallback ladder
  (`core/cda/stable_key.py:48-62`), and unmatched elements are ADDED or DELETED
- `_prune_to_outermost` (`diff_collector.py`) reduces each added or deleted subtree to its top
  node
- an XPath watch list (`configurations/aphl_baseline.json`) makes any change under
  `//hl7:entry` actionable, plus patient deceased, birth time, name and encounter end time
- `augment.py` places one author per (element, function code). Body codes are taken from the
  change type; the four header rules carry configured codes (`did-patient-*`,
  `did-encounter-closeTime`).

APHL's evaluation found this doesn't tell PHAs what changed.

### What production shows (silent evaluation)

The figures come from the CloudWatch Logs Insights export (q01 change paths, q04 change-count
distribution, q07 changes by version). They were reproduced on 2026-10-26, and the raw logs
and metrics agree to 0.05%.

1. **The document body fails to pair.** `/ClinicalDocument/component` is reported ADDED
   14,981,552 and DELETED 14,981,501 times, against at most 16.7M comparisons at version ≥2:
   a failure rate of at least 89.7%.
   - Some streams carry a constant `version_number` (310), so the denominator includes some
     non-comparisons, which only strengthens the bound.
   - The diff never descends past an unmatched node (`diff_collector.py:182-186`), so nothing
     inside a collapsed body is reported.
   - Probed mechanism: the body's key is its sections' `<id>`s. It falls back to their
     `templateId`s only while there are at most 12 distinct (`@root`, `@extension`) pairs
     (`core/cda/root_extensions.py:10`). Sections usually assert two each, so that's about
     six sections; the Mon Mothma chain (a hand-built three-version case, below) crosses 12 at six. Past that, **one**
     changed section `<id>` collapses the body.
   - The same cap applies to the section-id key, so a body with more than 12 distinct section
     ids has no key and doesn't collapse (probed: collapse at 12, none at 13). So 89.7% also
     implies most production bodies carry 1-12 section ids.
   - Bodies without section ids don't collapse, and neither does a gained or lost section with
     stable ids. So 89.7% means at least one section `<id>` changed, not that ids are
     regenerated wholesale.
2. **Identity is diffed as content.** In entries that do pair, the sender's `<id>` is reported
   deleted and re-added: 168.8M symmetric `…/id` changes.
   - [stated] q04's mean is 31.7 against a median of 6.0 and a p95 of 18.0. [computed] So the
     top 5% of documents hold at least 46% of all changes. [inferred] The churn is real but
     describes a minority of documents, possibly senders that keep section ids and regenerate
     entry ids.
   - Earlier augmentation authors add ±30.0M changes, and renumbered narrative pointers about
     40M `…/reference` updates.
3. **Narrative is a large share.** `…/tr` is ADDED 89.4M and DELETED 60.1M times, and `…/td`
   is UPDATED 72.2M times. Most of this says little about clinical change.
4. **12.1% of changes have no coded section.** They're in the header or uncoded content.

Points 1 and 2 are arithmetic signatures, not observed documents (DQ5).

### What controlled input shows (gap analysis)

APHL's gap analysis (deck of 22 October 2026, linked from #147) ran synthetic pairs with known
changes. [computed] None of its six DiD outputs (54 changes) reports
`/ClinicalDocument/component`, and every entry `<id>` stays stable. So it exercises neither
production point. DiD placed 31 flags against 38 expected (slide 3):

| scenario                     | placed / expected |
| ---------------------------- | ----------------- |
| nested and complex (v1 → v4) | 15 / 23           |
| multi-code update            | 6 / 6             |
| codes updated one at a time  | 4 / 3             |
| stable key changes           | 6 / 6             |

For multi-code and stable key, APHL's notes say the count is right "but code most likely
incorrect": that's gap 5 and #147.

| gap | what happens                        | cause today                                                 |
| --- | ----------------------------------- | ----------------------------------------------------------- |
| 1   | new section's statements unflagged  | pruning keeps one added node                                |
| 2   | nested new statements unflagged     | same                                                        |
| 3   | a section's own change unflagged    | rules match entries, never the section                      |
| 4   | two authors on one statement        | a changed `@code` splits into DELETED + ADDED (`CODE_RANK`) |
| 5   | existing statement flagged as added | the function code comes from the child's change type        |
| 6   | removals unflagged                  | `augment.py` drops DELETED; pending APHL and the IG         |

[#147](https://github.com/CDCgov/dibbs-ecr-diff/issues/147) is the same problem from the
classification side. A corrected code, or an `<id>` gaining `@extension`, reads as a deletion
and an addition. The root cause is shared: DiD uses identity either as the pairing key or as
content.

### What a realistic chain shows

`change_path` carries no `templateId` and no values. So production can't see corrected codes,
trigger codes or #147, and APHL's fixtures test placement, not a case unfolding.

The Mon Mothma chain (`dibbs-star-wars-ecr-data` `tests/assets/mon-mothma-covid-*`) is one
hand-built case in three versions: COVID suspected, then a SARS-CoV-2 test ordered, then the
result Detected and the diagnosis confirmed. Its ids are stable, so today's matcher is at its
best, and [computed] every new statement is found. The output still doesn't tell the story:

- there are 11 actionable changes, each an XPath with no values. The three that together say
  "confirmed" sit in three sections:
  - a new result
  - a new diagnosis inside the existing problem concern
  - Results going from `nullFlavor="NI"` to populated, which isn't actionable (gap 3)
- two of v3's 8 actionable changes alter no code: a `@displayName` and the trigger's
  `sdtc:valueSetVersion`. Either one alone makes a version actionable (probed)
- v3's HPI states the outcome in prose, and it isn't actionable

Even when pairing works, nothing says what changed.

### What is now available

The 2025 Rhapsody DiD compared section by section. `dibbs-ecr` (Refiner ADR 0017, Proposed)
would provide the section catalog, the version map, RR parsing and the augmentation writer.
**This ADR depends on 0017.** If 0017 changes, the tickets marked `dibbs-ecr` land in DiD
behind the same interface.

**The question: how should DiD decide what changed between two eICR versions, so that it
fixes what APHL flagged and stays explainable?**

## Decision Drivers

- Fix gaps 1-5, #147, and the production signatures. The one exception is a statement whose
  `<id>` and identity fields both changed and that step 4 can't match: it's reported as
  unmatched (step 5), not as new, and the pilot measures how often.
- Deterministic and explainable: every finding says why it paired and what changed. There's
  no weighted scoring and no learned model, and the Lambda has little memory.
- A missed pairing fails safe, to an unmatched or added finding, never to a silent drop.
- It works on refined and unrefined documents.
- Specification lives in `dibbs-ecr`, and DiD's own choices stay in DiD.
- The improvement is measurable with the silent evaluation's queries.
- `setId` continuity: inputs sharing a `setId` reach every PHA under one output `setId`.

## Considered Options

### A. Unit of comparison

- **A1. Whole document (today).** A body or section that fails to pair takes everything beneath
  it.
- **A2. Section-scoped (RECOMMENDED).** Sections pair first, and entries pair only inside their
  section, so a failure stays in one section. This matches how PHAs read and how the Refiner
  configures.
- **A3. Entry-global.** This loses section context, and near-identical entries in different
  sections would compete.

### B. Pairing entries

- **B1. Stable-key ladder (today).** Each sibling list goes through twelve ranked keys (each
  used only where it's unique on both sides), then subset, bucket and soft-context fallbacks,
  and finally document order. Then the matcher recurses. It's careful but generic: the same
  keys apply to an `<id>`, a `<td>` and a lab result, and nothing records how anything paired.
  [computed, Mon Mothma v2, regenerating entry ids only; it has no section ids, so the body
  can't collapse]
  - With one statement per template, entries still pair across regenerated ids. But every
    `<id>` is reported deleted and re-added, and that alone makes the version actionable.
  - A corrected `<code>` splits into ADDED + DELETED `<code>` under its paired statement
    (gap 4).
  - With several statements of one template (three problem concerns), regenerated ids split
    every entry into added + deleted.
- **B2. One clinical key** (`code` + `effectiveTime` everywhere). This fixes regenerated ids,
  but regresses a corrected code with a stable `<id>`, because the key is what changed. It's
  also the wrong key for some templates: on a Problem Observation, `code` is the problem _type_
  and `value` is the diagnosis (CONF:1198-9045, CONF:1198-9058).
- **B3. A cascade (RECOMMENDED).** Pair on a shared `<id>`, then the template's identity fields,
  then a singleton, then a single similar leftover; otherwise the statement is unmatched. The
  id-only case and the corrected-code case need opposite keys, and the cascade serves both.
  Identity fields are per template, which is what separates step 2 from B2.

### C. How actionability is configured

- **C1. XPath rules (today).** These can't express "a section's own change" or "the result was
  finalised", and `//hl7:entry/descendant-or-self::*` flattens all salience.
- **C2. A named-element catalog (RECOMMENDED).** Code defines the units, pairing keys and kinds
  of change, and configuration picks from them. XPath becomes an implementation detail.

### D. Flag placement

- **D1. Outermost changed node + change type (today).** This causes gaps 1, 2, 4 and 5.
- **D2. Placement from findings (RECOMMENDED).** Authors go only on a section or a clinical
  statement, one per statement per pass. The function code comes from the statement that
  carries it.

### E. Where the template knowledge is decided

- **E1. A template-model ADR first.** That would design the model before its purpose is
  stated, which is how Refiner ADR 0010 came to defer it.
- **E2. Here, built in `dibbs-ecr` (RECOMMENDED).** This ADR states the knowledge the fixes need,
  and it lands in `dibbs-ecr` under 0017's admission rule, so each piece traces to a gap. The
  cost is that DiD's needs shape the model first.

### F. Sequencing

- **F1. Rewrite only.** PHAs see no fix until it lands.
- **F2. Placement fixes first, on today's matcher.** Gaps 1, 2, 4 and 5 are fixable in
  `augment.py`. But this only reaches senders with stable ids. A collapsed body is actionable
  whatever it holds, and as an added wrapper it would flag every statement. So a collapsed
  document keeps today's single `did-add-detected` on the first section.
- **F3. Classify, then judge, then project (RECOMMENDED).** Most of what APHL flagged is
  classification, not projection: production points 1 and 2, #147, and the root of gap 4. Only gaps 5
  and 6, panels and the `did-*` codes are purely about how findings are written. F2 would fix
  the tag on a classification that is still wrong.

  - **classify:** findings, piloted silently
  - **judge:** which findings matter
  - **project:** findings written into the document

  Entry authors become a per-deployment setting in Phase 0, with today's placement writing
  them until projection replaces it. The header flags and the IG's document-level augmentation
  (new `id`, `setId`, `relatedDocument` and header author) stay. The setting's default is
  pending (APHL Q19, under Placement).

  **Interim (Phase 1a):** sections can pair first while today's matcher runs inside each
  section pair. That changes the verdict (whether a version is actionable), the header summary author (a version that was
  actionable only because its body collapsed gains `did-no-actionable-change`,
  `augment.py:759-766`) and telemetry. Where entry authors are on, today's placement runs over
  the section-scoped changes, so a body that would have collapsed gets per-entry flags. The
  verdict also decides delivery and the next baseline, so Phase 1a runs in shadow first, and
  going live is decided from that run.

  - [computed] It reproduces today's output, change for change, on all 21 consecutive fixture
    pairs: e2e, package-1 original and refined, nested, codeupdate, stable-key, multicode and
    Mon Mothma.
  - On Mon Mothma v1 → v2 cut to 8 sections, with section ids injected and one regenerated, it
    finds the two new entries, where today's matcher reports a collapsed body.
  - Id churn, gap 4 and pruning remain until the cascade replaces the matcher.

## Decision Outcome

Proposed: **A2 + B3 + C2 + D2 + E2 + F3**, with section units shipped over today's matcher
first.

- **Units:** sections, two header pseudo-sections, and entries. Each `<entry>` is compared as
  one pattern.
- **Pairing:** entries pair by a five-step cascade inside their section, and each finding says
  how it paired.
- **Non-clinical:** ids, augmentation authors and upstream tools' additions are never reported
  as change.
- **Narrative:** read only in narrative-only sections, and only when it gains content.
- **Placement:** an author goes on the section or statement that changed. Findings are
  written into the document last, as `<author>`s and a narrative footnote together; entry
  authors are a deployment setting.
- **`setId`:** a stream keeps one output `setId`, from a seed without jurisdiction.
- **Template knowledge** comes in three layers, built in `dibbs-ecr`: **layer 1**, each
  template's structure (generated from the specification); **layer 2**, what each CDA
  attribute means generically, such as "`id` is never clinical"; and **layer 3**, what a
  template's fields mean (curated, CONF-cited), such as its identity fields.

The work ships in phases (tickets in the Appendix):

| phase                | what ships                                                                                     | done when                                                                                                              |
| -------------------- | ---------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------- |
| 0: ground and guard  | test harness, `setId` seed, entry authors as a setting, shadow comparison                      | the harness and `setId` test run; the seed is fixed or its cutover planned; entry authors switch; the shadow path logs |
| 1a: sections first   | section units over today's matcher                                                             | no body collapse in the shadow run; diff output unchanged where the body already paired; go-live decided from that run |
| 1: classify          | findings, layers 1-3, the pairing cascade, a silent pilot                                      | fixture findings pass; the pilot's unmatched rate is understood                                                        |
| spike: actionability | whether the verdict separates meaningful versions from noise                                   | keep, redefine or drop the verdict, recorded in `docs/algorithms/ecr-diff.md`                                          |
| 2: judge             | the baseline configuration on the catalog                                                      | it covers the MVP scope document                                                                                       |
| 3: project           | authors and footnote written from findings; DiD's codes proposed to the IG; the ladder retired | PHAs and APHL have reviewed the output; nothing writes from the old pipeline                                           |

### Units

- **Sections** pair on a shared section `<id>`, then their **base template root**, then LOINC,
  each unique on both sides. A section with no `<id>`, or whose `<id>` differs between
  versions, goes on to the next key; sections get no "sender keeps ids" guard, since senders
  change section ids (silent evaluation).

  - **Added** means the section's key is on one side only. Among sections, only an added one
    is an added wrapper (Placement); an ambiguous one never is.
  - **Ambiguous** means its key is on both sides but not unique, or it has no key. Ambiguous
    sections that share a key pool their entries, which pair in that pool. A keyless section
    stands alone. An ambiguous section is never flagged for being ambiguous; its unpaired
    entries follow step 5, and telemetry counts it. A generic fallback, as the Refiner's
    `generic_matching` is for sections without match rules (`section/__init__.py:30-50`), is
    designed from the pilot (Phase 1).
  - The base root is the top of the "Conforms to" chain, so Encounters `2.22.1` pairs with
    `2.22`. An unrecognised root, such as a vendor's local OID, is its own base root: it
    means nothing to the catalog but is stable within one sender's stream.
  - A templated section's LOINC is fixed by its template (CONF:1198-15467), so a LOINC change
    is a finding, not a pairing failure. APHL's stable-key fixture changes exactly that,
    46240-8 → 46240-7.
  - Nested sections pair within their parent's pair. A section with no `templateId` pairs on
    LOINC alone.
  - Each document uses the `dibbs-ecr` catalog for its detected version. The base root
    ignores extensions and LOINC is the fallback, so [inferred] a 1.1 → 3.1.1 pair still lines
    up; confirm against the 1.1 catalog (APHL Q15).
  - **Until layer 1 lands (Phase 1a)**, the middle step uses the set of co-asserted
    `templateId` roots, since v0.1's section catalog holds one `templateId` per section and
    no "Conforms to" chain (Refiner `specification/catalog.py`). Sections that don't pair
    uniquely fall back to today's matcher among themselves, which keeps today's output for
    documents with duplicate sections.

- **Header pseudo-sections:** `patient` (`recordTarget/patientRole`) and `encounter`
  (`componentOf/encompassingEncounter`). The rest of the header is compared but isn't
  actionable under the baseline, as today.
- **Entries:** an `<entry>` and everything in it is one unit, so a panel is one unit. (The
  Refiner prunes results because its output is condition-specific; DiD only asks whether the
  entry is the same.) Nested clinical statements pair within their parent pair (gap 2), so
  placement can name the one that changed.
- **Qualifiers:** _qualifier_ is a role a template plays under a parent, marked in layer 3. A
  qualifier pairs as a field of its parent, so its change is a finding on the parent (`4.419`
  F → C is `result_corrected` on the result). The finding records the qualifier as where
  the change is, so placement puts the author on the qualifier, not the parent. Statements
  nested in a qualifier, such as Specimen Observation `4.417` in a specimen procedure, pair
  within it as any nested statement does. For its author: a qualifier that's new gets
  `did-add-detected`, as does everything in it (it's an added wrapper); one that changed gets
  `did-update-detected`. The qualifiers are:

  - Laboratory Observation Result Status `4.419` (CONF:4411-445), under a result
  - Laboratory Result Status `4.418` (CONF:4527-443) and Specimen Collection Procedure
    `4.415` (CONF:4527-450), under a result organizer
  - an untemplated statement under a result organizer that isn't an `<observation>` or
    `<organizer>` (Epic sends specimen `<procedure>`s untemplated)

  For untemplated statements, deciding by statement kind is what the Refiner's shared-context
  guard does, after name-based versions failed (`entry_match_rules.py:702-725`, Refiner
  #1522, #1763).

> [!NOTE]
> **APHL Q1: what is a qualifier?** `4.418`, `4.419` and `4.415` can all carry an author,
> so is the qualifier rule DiD's choice? Does a `4.418` change resolve past an authorable
> observation to the organizer?
>
> Yes, it's DiD's choice, and it governs how a qualifier pairs, not who gets the author. A qualifier is compared as a
> field of its parent, so `4.419` F → C is one `result_corrected` finding on the result,
> and the footnote describes it that way. The `<author>` goes on the qualifier itself, per
> APHL's nearest-statement rule. And yes to the last question: `4.418` and `4.419` are
> qualifiers by template, not by element kind. The element-kind rule covers only
> untemplated statements, such as Epic's specimen procedures.

> [!NOTE]
> **APHL Q3: does an ambiguous section flag everything inside it as added?**
>
> No, from Phase 1 on. Only a section whose key is on one side alone is an added wrapper.
> An ambiguous section's entries pair in a pool with other sections of its key, or within
> the section if it has none. (In Phase 1a, today's matcher runs among those sections.) A
> vendor's local OID is now a key in its own right, which [inferred] covers most sections
> outside the IG; the pilot shows how many are left.

> [!NOTE]
> **APHL Q3, follow-up: are ambiguous instances still flagged as added?**
>
> The section is never flagged for being ambiguous. An entry inside it that still doesn't
> pair follows the step 5 rule (Q6, Q12, under Pairing). The pilot counts how often
> sections are ambiguous, and a generic fallback is designed from what it finds.

> [!NOTE]
> **APHL Q4 and Q5: a section with no `<id>`, or with ids that don't match.**
>
> Both go on to the base root, then LOINC, so `nullFlavor="NI"` sections pair as usual.
> [computed] Mon Mothma v1's two (29549-3 and Results 30954-2) have no `<id>` and no
> entries but keep their `templateId`s and LOINC, so [inferred] they pair on root. Going from `nullFlavor`
> to populated is gap 3: the section gets `did-update-detected` and its new entries
> `did-add-detected` (Narrative).

### Template knowledge (built in `dibbs-ecr`)

1. **Structure, per template (generated).** This covers root, extension, kind, child slots with
   cardinality and CONF, parent context, and the template it constrains. Each part comes from
   the source that carries it:

   - SHALL and SHOULD slots come from the vendored eICR 3.1.1 Schematron: 826 rules, 151
     templates.
   - What a template constrains (its base root) comes from the IG's "Conforms to" statements
     and co-asserted `templateId`s. [computed] 3.1.1's Volume 2 has 26 such statements naming
     23 parent templates, among them Result Observation, Problem Observation, Planned
     Observation and Pregnancy Observation; 1.1's has 9. A template no statement names a parent
     for is its own base. The Schematron carries none of this, so the chain is extracted from
     Volume 2 and checked against the co-asserted roots in its examples.
   - Older roots are carried, and are usually the base. Supplemental Pregnancy `22.4.293`
     "Conforms to" Pregnancy Observation `15.3.8` `[eicr-3.1.1 line 12023]`, and its example
     asserts both (line 12094). So a 1.1 statement carrying only `15.3.8` pairs with a 3.1.1
     one carrying both. The Refiner links these two by hand today
     (`entry_match_rules.py:1019-1020`); the catalog links them by construction.
   - _Clinical statement_ comes from the CDA R2 XSD element type. _Wrapper_ and _qualifier_ are
     roles under a parent, marked in layer 3.
   - MAY slots belong to layer 1 but can't be generated from a Schematron (the IG has 363), so
     they're curated by hand, with layer 3, until the Trifolia export replaces them (DQ6).
     They include `4.419` (CONF:4411-445) and `4.418` (CONF:4527-443).
   - v0.1 generates 3.1.1. eICR 1.1 uses the same C-CDA roots for its clinical statements
     (Result Observation `22.4.2` and Problem Observation `22.4.4`, under the same
     CONF:1198-\* constraints), so pairing by base root and the layer 3 rows apply to 1.1
     as-is. What 1.1 lacks until its (already vendored) Schematron is generated is layer 1:
     slots, cardinality and the nested-template skeleton step 4 compares. The generator and
     its pinned sources move with the output, as `template_oids.py` does.

2. **Generic CDA meaning, per attribute (written once).**

   - **Non-clinical:** DiD runs after other augmenting tools `[aug-v5-v1 Table 1]`, so it
     reports what the sender changed, not what a tool added. This covers:
     - `id`
     - narrative `reference/@value`
     - augmentation authors, recognised by the `eCRDataAugmentation` code system
       (`2.16.840.1.113883.10.20.15.2.7.1`) on `functionCode` or `softwareName`. Text-to-code
       writes no `templateId` on its authors (CONF:5573-29), so this can't key on templates.
     - text-to-code's `<translation>`s. It marks only the entry, with an author, not the
       translation (`dibbs-text-to-code` `eicr_augmenter.py:334-365`). So a `<translation>` on
       a statement carrying a text-to-code author in the newer version is non-clinical,
       whether text-to-code ran on one version or both. The cost: a translation the sender
       added there is hidden too.
     - the Refiner's and DiD's own provenance `<footnote>`s, removed before the narrative is
       compared
     - `sdtc:valueSetVersion` on its own. It records which RCTC release matched
       `[eicr-3.1.1 line 8947]`, so it moves on an unchanged code: 20200429 → 20250216 on the
       Mon Mothma chain, which today alone makes the version actionable (probed).
   - **Clinical:** `moodCode`, `statusCode`, `negationInd`, `effectiveTime`, `nullFlavor`; on a
     code, `@displayName`, `originalText` and `sdtc:valueSet`; and a statement's
     participations (`performer`, `participant`, a clinician `author`).
     - `@displayName` is here by DiD policy, not CDA meaning: it "carries no computable
       semantics" `[cda-book line 2806]`. APHL expects a corrected display name to be an
       update (slide 19). The cost: a sender refreshing display strings looks like it updated
       statements, as Mon Mothma's "Difficulty Breathing" → "… (finding)" does today (probed).
     - Gaining `sdtc:valueSet` marks a trigger, which is a `populated` finding.

   A non-clinical change is never reported as clinical. That removes the 168.8M id changes and
   30M author changes. This split isn't the RIM's (Appendix). Most mood changes
   (planned → performed) also change the template, so they appear as a removal and an
   addition, not as a mood change on one pair.

3. **Template meaning (curated, CONF-cited).** Identity fields, meaningful fields, trigger-code
   templates, and status models.

   - The canonical status case is `4.419`: F → C is `completed` → `completed` generically, yet
     it's the most important change. Its only context is the trigger-code result, where it's
     optional `[eicr-3.1.1 Table 152]`. So the finalised → corrected kind exists only on
     trigger-coded results that carry it, and other results fall back to layer 2.
   - `4.418` sits on the Trigger Code Result Organizer and covers the whole battery (MAY 0..1,
     CONF:4527-443).
   - **On every trigger-code template, `negationInd="true"` means entered in error, not
     absence:** "A negationInd of true is not making a statement that the patient does not
     have the condition, rather that this trigger code data was entered in error"
     `[eicr-3.1.1 line 12982]` (SHALL 1..1, CONF:4482-296; the same rule at lines 8949, 9905,
     10625, 11256, 11371, 11653, 12951, 13382, 13699, 13991 and 14908). So on these templates
     `negated` refines to `trigger_retracted`: the reason the case was reported was withdrawn.
     A base Problem Observation keeps the generic reading `[eicr-3.1.1 line 12632]`, and eICR
     1.1 fixes it to `false` (CONF:3284-296).
   - **A problem's status:** a Problem Observation's `statusCode` is fixed to `completed`
     (CONF:1198-19112), and `effectiveTime/high` is what marks it resolved, even with
     `nullFlavor="UNK"` `[eicr-3.1.1 line 12645]`. The concern's `statusCode` "is the definitive indication of the
     status of the concern" `[eicr-3.1.1 line 12456]`. Gaining `high` refines to
     `problem_resolved`, and a concern's status change to `concern_status_changed`.

   Identity fields say where a template's clinical concept lives:

   | template            | identity fields                                  | basis                                                                                                                                                |
   | ------------------- | ------------------------------------------------ | ---------------------------------------------------------------------------------------------------------------------------------------------------- |
   | Result Observation  | `code` (with translations), then `effectiveTime` | LOINC test (CONF:1198-7133); specimen time (CONF:1198-7140), though senders vary in what it holds. `value` is the result: meaningful, never identity |
   | Problem Observation | `value`, then `effectiveTime/low`                | `code` is the problem type (CONF:1198-9045); the diagnosis is `value` (CONF:1198-9058); onset SHALL (CONF:1198-15603)                                |
   | Problem Concern Act | a Problem Observation matching on identity       | `code` SHALL be `CONC` (CONF:1198-19184), so concerns look alike; each holds 1..\* Problem Observations (CONF:1198-9034)                             |
   | Encounter Diagnosis | a Problem Observation matching on identity       | `code` SHALL be `29308-4` (CONF:1198-19183) and it has no `id`; it holds 1..\* Problem Observations (CONF:1198-14892, 14898)                         |

   - Identity fields are ordered. The first is the key; each later one only breaks a tie
     among candidates equal on the ones before. So a result whose `effectiveTime` moves
     between preliminary and final (report time, where a sender puts it there) still pairs on
     its `code`.
   - Fields compare one at a time, never pooled. A coded field matches on any shared
     (`@codeSystem`, `@code`) across the code and the sender's `translation`s, so a correction
     that only adds a translation still pairs, and so does a sender swapping which code is
     primary.
   - Translations an augmenting tool added never count for identity. On a statement carrying
     a text-to-code author in either version, identity uses `@code` alone: text-to-code
     appends a LOINC `<translation>` and never changes `@code` (`dibbs-text-to-code`
     `eicr_augmenter.py:334-365`). Two local assays it maps to one LOINC then still pair on
     their own codes.

   - A culture battery's results share a LOINC and a time and differ only by organism in
     `value`, so they're equal on identity. Step 2's uniqueness rule sends them on rather than
     pairing in document order.
   - A concern or encounter diagnosis pairs when any one of its Problem Observations matches
     one in the other version's on identity, under the usual uniqueness rule. That's a set
     overlap of nested statements, not pooled fields, so a concern that gains a diagnosis (Mon
     Mothma v3) still pairs.
   - [computed] Three concerns with regenerated ids split on today's matcher. Without these
     rows, steps 2-4 would have nothing to tell the acts apart, and step 4's generic fields
     are the act's own. That matters most for Encounter Diagnosis: it has no `id`, and it is
     one of the two containers of a trigger diagnosis `[eicr-3.1.1 line 12938]`.
   - The Refiner's `entry_match_rules.py` answers "does this match a condition", not "is this
     the same statement". So it seeds meaningful fields and trigger marking, and cross-checks
     identity fields without being their source.
   - An uncurated template falls back to layers 1-2: it skips step 2, and step 4 uses the
     generic fields. That's correct, just less specific.

**Change kinds** (such as `identity_only`, `populated`, `blanked`, `value_changed`,
`status_changed` and `negated`) are derived from layers 2-3, and belong in `dibbs-ecr`. A
generic kind can be refined by a template kind (`status_changed` → `result_corrected`,
`negated` → `trigger_retracted`). A
finding carries both, so a consumer that knows only generic kinds still works. Adding a kind
is a minor release. Whether a kind _matters_ is DiD policy.

> [!NOTE]
> **APHL Q7: must all identity fields match, or any one?** Two cases: `effectiveTime`
> carrying report time, and text-to-code changing which code is primary.
>
> Neither all nor any: they're ordered, and later fields break ties. A moved
> `effectiveTime` still pairs on `code` at step 2. A swapped primary code pairs too, since
> codes match across `@code` and the sender's translations. Today's text-to-code doesn't
> swap (it only appends a translation), so that case comes from senders.

> [!NOTE]
> **APHL Q8: could two assays pair on a shared translation?**
>
> No. Translations from augmenting tools don't count for identity, so on a text-to-code
> statement only `@code` does. Where a sender's own translation is shared, both assays
> become candidates for each other; that's a tie, which falls through rather than
> mispairing. (Today's text-to-code adds LOINC translations, not SNOMED, so the realistic
> case is two local assays mapped to one LOINC; the rule covers either.)

> [!NOTE]
> **APHL Q13: what fills the Schematron's gap, and how is the base root derived in the
> meantime?**
>
> The "Conforms to" chain comes from Volume 2 (26 statements in 3.1.1), checked against
> the co-asserted roots in its examples; MAY slots are curated by hand until the
> Trifolia export (DQ6) arrives. Phase 1a needs no base root: sections pair on their set of
> co-asserted roots and entries run on today's matcher. We'd gladly take APHL's
> extraction of the chain and diff it against ours.

> [!NOTE]
> **APHL Q14: does the catalog carry older roots, as Pregnancy Observation asserts?**
>
> Yes, and the older root is usually the base: `22.4.293` conforms to `15.3.8`, so
> statements pair across releases on `15.3.8`. The Refiner hand-codes that link today.

> [!NOTE]
> **APHL Q15: 1.1 documents, and the effort to generate their catalog.**
>
> A 1.1 result still has identity fields: 1.1 uses C-CDA's `22.4.2`, so its layer 3 row
> applies and step 2 runs. The ADR's "fall back to element kind" wording was wrong and is
> fixed. What waits on the 1.1 catalog is layer 1 (step 4's skeleton, MAY slots). [inferred]
> That's the 3.1.1 generator pointed at a smaller Schematron ([computed] 358 rules,
> against 3.1.1's 826), so small, and it's planned alongside 3.1.1 given APHL's 10-15%
> figure (Phase 1 ticket). Confirm once the 3.1.1 generator exists.

### Pairing

All pairing happens inside one section pair, grouped by template. Nested statements pair
inside their parent's pair.

**Which template:** the **base template root**.

- A statement asserts stacking `templateId`s `[cda-book line 3978]`. A trigger-coded result
  carries three `[eicr-3.1.1 Figure 117]`, and a result can gain the trigger template between
  versions.
- Extensions are ignored. The IG contradicts itself on them: CONF:4527-444 cites `4.418` as
  `2018-06-11`, while CONF:3378-373 requires `2018-09-01`.
- A trigger-code `templateId` is a field, so gaining one is a finding.
- An unrecognised root, such as a vendor's local OID, is its own base root (as for sections,
  Units). A statement with no `templateId` at all falls back to its element kind and its slot:
  its parent pair and its relationship to it (`typeCode`).

The Refiner matches on the base root in production too.

**The cascade:**

1. **Shared `<id>`.** Any shared (`@root`, `@extension`) matches, since `id` is 1..\*
   (CONF:1198-7137). Root alone and root + `@extension` stay distinct identifiers, as CDA's
   instance identifiers are, so an `<id>` that gains `@extension` doesn't match here.
   - `nullFlavor` ids never match, and an `<id>` repeated among siblings disables this step for
     them.
   - A statement also pairs when a statement nested in it keeps its `<id>` uniquely
     (`nested_id`): a panel is the same panel if its result is the same result. APHL's
     stable-key panels pair this way.
2. **Identity fields** (layer 3): the first equal, with exactly one candidate on each side;
   where several share it, the next field breaks the tie. Remaining ties fall through.
3. **Singleton:** the only unpaired statement of its template in its scope, on each side. The
   scope is the section for an entry, and the parent pair for a nested statement.
   - It pairs even when the `<id>` and the identity fields both changed, which is the likely
     production form of #147. The finding records which identity fields changed.
   - **It's not applied in a scope where anything paired at step 1.** That sender keeps ids,
     so a newcomer is new. If `P1` pairs by `<id>`, `P2` is removed and `P3` is new, `P3` is
     reported added, not as an update of `P2`. It fails towards added.
4. **Similar leftover**, an 80/20 stop-gap over what steps 1-3 left. A pair needs:

   - the same template and nested-template skeleton
   - at most two differing meaningful fields (layer 3, or the generic `code`, `value`,
     `statusCode` and `effectiveTime`)
   - each to be the other's only such candidate, so ties refuse

   This catches, for example, a corrected code whose `effectiveTime` also moved. The finding
   names the differing fields, and the step 3 guard applies. [inferred] It catches most such
   cases, not all; the limit is set from pilot data.

5. **Unmatched:** what's left. DiD says what it knows, and no more:

   | leftover in the newer version                                                                    | reported as                                                                                                                                                                                                             |
   | ------------------------------------------------------------------------------------------------ | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
   | an unmatched statement of the same template is left in the older version, so it may be an update | `did-unmatched-detected` on the statement (proposed); the footnote names both. Until the code is accepted, `did-update-detected` on the section. The older one gets no `<author>`: removals aren't flagged (gap 6, DQ8) |
   | nothing left it could be                                                                         | `did-add-detected`: it's new                                                                                                                                                                                            |
   | step 3's guard applies (the sender keeps ids)                                                    | `did-add-detected`, as step 3 says                                                                                                                                                                                      |

   The version is still actionable: something changed, and DiD fails towards delivery. An
   unmatched statement is never reported as new when it may not be, except under a sender
   that keeps ids (step 3's guard). The pilot measures how often each case happens.

Meaningful fields help pair only at step 4: on leftovers, capped, and reported as the change.
Pairing on the field being detected would otherwise hide it.

**Inside a pair, DiD compares fields, not children.** A changed `@code` is one
`value_changed`, not DELETED + ADDED (gap 4, #147).

The order is chosen for correctness. `<id>` is the spec's identity `[cda-book line 5678]`, and
each later step compensates for senders that regenerate it. `paired_by` in telemetry shows
which step fires.

> [!NOTE]
> **APHL Q6 and Q12: does an unpaired statement look exactly like a new one? Can something
> be ambiguous and actionable?**
>
> Where an unpaired statement could be an update of one that's gone, it no longer gets
> `did-add-detected`. Proposed: `did-unmatched-detected` on the statement (DQ7). Until the
> IG accepts it, `did-update-detected` goes on the section, and the footnote (Phase 3)
> names both candidates. The removed one gets no `<author>`, since removals aren't flagged
> (gap 6, DQ8). A statement is flagged added only when nothing could have been its
> counterpart, or when the sender keeps ids (step 3's guard). The version is still
> actionable, so nothing is withheld.

> [!NOTE]
> **APHL Q9: element kind and slot, and local OIDs.**
>
> Kind and slot are the element name, the parent pair and the `typeCode`. APHL is
> right that two untemplated observations under one organizer look alike, so steps 2-3
> have nothing to go on. They pair by their own `<id>` or `nested_id` (step 1), by step 4,
> or not at all; the pilot counts how often. On local OIDs: yes, one is now a pairing key.

> [!NOTE]
> **APHL Q10: could a second key break a tie?** Two organizers equal on code and time, their
> ids regenerated, their results' ids kept.
>
> Yes, in two ways. The example pairs at step 1 already: `nested_id` pairs a statement whose
> nested statement keeps its `<id>`, so each organizer pairs through `res-A` or `res-B`. And
> at step 2, later identity fields now break ties among candidates equal on the first.

### Findings

Each finding carries:

- its section or pseudo-section
- its unit and template
- its kind, generic and refined
- `paired_by` (`id` / `nested_id` / `identity` / `singleton` / `similar` / `unmatched`), with
  the changed fields for `singleton` and `similar`, and the possible counterparts for
  `unmatched`
- before and after values, with display names
- `related`, empty for now

`related` reserves room for cross-entry links, such as the Mon Mothma order (v2), result and
confirmed diagnosis (v3), which are one story across three sections. Order → result is the
first link to build, after Phase 3. From Phase 3, the footnote's removal rows put a removed
order beside the new result.

> [!NOTE]
> **APHL Q11: linking an order to its later result.** Planned Observation `4.44` and Result
> Observation `4.2` don't pair, so the result looks new and the order's removal isn't flagged.
>
> Linking them through `related` comes after Phase 3, not in these phases. From Phase 3, the
> footnote lists the removed order beside the new result, so a reader sees both. APHL's point
> that this is one of the commoner reasons for a second eICR is a reason to rank it first
> among the cross-entry links.

`identity_only` findings are recorded but never flagged; otherwise every id-regenerating
sender would be actionable (DQ1). An empty list means nothing new.

### Narrative

- **Sections with entries:** the narrative isn't compared. A section's own `code`, `title`,
  `nullFlavor` or participations still flag it (slide 11). In gap 3, Results goes from
  `nullFlavor` to populated, and the section is flagged along with its entries.
- **Narrative-only sections** (no `<entry>` in _either_ version) get a section author for two
  findings:

  - `section_populated`: it was `nullFlavor` and now has content
  - `narrative_expanded`: after removing `ID`s, `reference/@value`, footnotes and whitespace,
    it has more rows, items or paragraphs, or else longer text (an 80/20 test)

  A new one gets `did-add-detected`, and the two findings get `did-update-detected`. Any other
  narrative difference isn't reported, so a removal never leaks in as an update. A section
  that loses all its entries isn't narrative-only.

Reading narrative _content_ is a separate spike: Epic, Cerner and Meditech each lay it out
differently.

### Placement

Placement projects the findings after all of them are collected, so a pass never reads its own
authors back. It comes last (F3): `<author>`s and a narrative footnote, together. Header flags
sit on `ClinicalDocument` and stay on throughout.

The `<author>` rules:

- **Who carries one:** a section or one of the nine clinical statements. With
  `ClinicalDocument`, those are CDA R2's 11 author-capable types.
- **Changes** walk up to the nearest author-capable statement, qualifiers included, which
  gets `did-update-detected`. This is APHL's rule (gap deck 2, 28). A qualifier's change is a
  finding on its parent that records the qualifier, so the author lands on the qualifier.
- **Entry authors are a deployment setting.** Authors inside `<structuredBody>` can be turned
  off for a jurisdiction that asked for none yet; header flags and the footnote are written
  either way. This follows `docs/AUGMENTATION-CONTRACT.md` §6.1 (both channels, emission per
  deployment).
- **Added wrappers** are read through one level. The wrapper and everything beneath it get
  `did-add-detected` (gaps 1, 2). The body is never an added wrapper, and nor is an
  ambiguous section (Units).
- **One author per statement per pass**, with the code from that statement (gaps 4, 5).
- **Header pseudo-sections** flag `ClinicalDocument` with today's codes (`augment.py:810-812`).
- **Removals** aren't flagged (gap 6).

The `did-*` codes are outside the bound value set `[aug-v5-v2 CONF:5573-43]`. It's DYNAMIC, so
they're proposed to the IG (DQ7).

**Panels.** Authorship conducts down the tree `[cda-book lines 3771-3775]`, so an author on an
organizer claims every result changed. Few receivers follow that inheritance
`[cda-book line 3779]`, which is why gap 2 wants each new result flagged explicitly. The
author goes where the change is:

| what changed                                | author on                                                                            |
| ------------------------------------------- | ------------------------------------------------------------------------------------ |
| new panel                                   | the organizer, and each result in it                                                 |
| the panel's own code                        | the organizer                                                                        |
| a panel or result status (`4.418`, `4.419`) | that status observation: `did-add-detected` if new, `did-update-detected` if changed |
| a new specimen procedure (`4.415`)          | the procedure, and everything in it                                                  |
| one result's value or code                  | that observation                                                                     |
| a new result in an existing panel           | that observation                                                                     |

This is APHL's rule (slide 28). Whether PHAs also want the organizer marked is open
(DQ3).

> [!NOTE]
> **APHL Q2: a new specimen procedure.** In the v4 scenario, should a new `4.415` get
> `did-add-detected` on the procedure and the observation inside it, or a finding on the
> organizer?
>
> On the procedure and everything inside it, as APHL's rule says. [computed] Today's DiD
> already flags the procedure in nested v3 → v4, but misses the Specimen Observation `4.417`
> inside it (gap 2).
> The ADR's earlier panels table would have moved the flag up to the organizer, a regression;
> it no longer does.

**Narrative provenance.** The jurisdictions using the Refiner read a section's `<text>`, and
asked that the Refiner add nothing to `<structuredBody>` yet. APHL's guidance, conformance
statements and jurisdiction training are built on entry `<author>`s, and in CDA provenance is
carried by author participations, not narrative. So the footnote is written alongside the
authors, never instead of them: one `<footnote>` per changed section, with a plain-language table:
what changed, before and after, and how it paired. It can list removals, which an `<author>`
can't.

Where an `<author>` marks the exact statement, the footnote gives the context: the path from
the entry down through its nesting to where the change is, then before and after. A `4.419`
F → C reads as "SARS-CoV-2 RNA result › result status: final → corrected". A new specimen in
nested v4 reads as "HIV 1 and 2 Ab panel › specimen collection (added) › volume of blood: 5 mL",
with the collection's date and site.

- The mechanism is the Refiner's (`narrative/footnote.py:73-160`), shared through
  `dibbs-ecr`.
- The PHA response to the wording shapes the codes DiD proposes.
- The eICR stylesheets have no `footnote` template, so [inferred] it renders inline at the
  end of `<text>`. APHL's Standards team is updating the stylesheet to highlight tool changes,
  DiD's included, and can confirm how a footnote renders.

> [!IMPORTANT]
> **APHL Q19, pending: entry authors and the footnote.** APHL asks where "PHAs don't want the
> author flags" came from, since it justified footnote-first projection and leaving entry
> authors off for three phases. APHL's position: the footnote should complement the flags,
> not replace or defer them.
>
> - **Where it came from:** the jurisdictions using the Refiner asked it to add nothing to
>   `<structuredBody>` _yet_. Earlier drafts generalised that to all PHAs and to "don't want";
>   both overreached, and the text above no longer says so.
> - **Proposed:** entry authors become a per-deployment setting in Phase 0, rather than being
>   turned off, following `docs/AUGMENTATION-CONTRACT.md` §6.1. Header flags and the footnote
>   are written either way. Projection (Phase 3) replaces today's placement; it doesn't turn
>   authors back on.
> - **Pending:** the default, and which jurisdictions start with entry authors off. That's for
>   product and engagement management to decide with the jurisdictions concerned.
> - **Accepted:** APHL's Standards team confirms the stylesheet rendering, and reviews the
>   footnote's wording and a rendered example before it goes into the IG guidance.

### `setId` continuity

`setId` tells DiD and the PHA that two documents are one stream, and the verdict rests on it.
DiD keeps the IG pattern (its own `setId`, stamped from v1 on). The seed becomes
`uuid5(DIFF_DETERMINISTIC_NS, "eicr-setid:{root}")`. The RR's `setId`, which seeds from the
eICR's, changes the same way.

Today's seed (`core/augment.py:99-111`) prefixes the jurisdiction list, which the Lambda joins
(`lambda_function.py:182`). So the `setId` shifts when that list changes. DiD doesn't know
which jurisdictions turned it on for a stream, and two jurisdictions with the same
configuration receiving one `setId` is how originals already work.

Jurisdiction- and condition-specific DiD configuration would reopen this. Streams that differ
only in `@extension` are already merged before DiD sees them: the Refiner and the manifest keep
the root only. So adding `@extension` to DiD's seed couldn't separate them, and it's left to
DID-028 in the DiD issue log. The new seed is a one-time `setId` change for any stream already in flight, so it ships before anyone relies on
DiD's output, or with a cutover plan.

The derivation:

- is a pure function of the stream's identity, never of per-version content
- is frozen as wire protocol once shipped
- is tested so every version of a stream maps to one output `setId`
- is logged as both input and output `setId` (Measurement)

These are unchanged here:

- the Lambda finds its baseline by the input `setId` (`lambda_function.py:179-183`)
- the Refiner's output `setId` seeds on jurisdiction and scope
  (`dibbs-ecr-refiner` `services/ecr/augment.py:187-193`), so a scope change starts a new
  stream
- a stream whose v1 never went through DiD reaches the PHA at v2 with a new `setId`

### Computation

```python
@dataclass
class SectionComparison:
    section_key: str  # section <id>, else base template root (unrecognised roots included), else LOINC
    old_section: _Element | None  # None: section is new
    new_section: _Element | None  # None: section was removed
    old_entries: tuple[_Element, ...]  # originals, never shrink
    new_entries: tuple[_Element, ...]
    pairs: list[tuple[_Element, _Element, PairedBy]]
    unpaired_old: list[_Element]
    unpaired_new: list[_Element]
```

Pairing only moves references between pools. At every level, each original ends in exactly one
of `pairs` or `unpaired_*` (asserted), and each unpaired original records why: `unmatched`
(a possible counterpart was left) or `no_counterpart`. XPaths are rendered only for output. Memory is bounded by one document pair,
and both today's diff and this one hold two parsed trees, so [inferred] memory use is about
the same. It hasn't been measured.

### Baseline configuration

There's one configuration for every jurisdiction. Its source is **APHL's MVP scope
document**, the requirements `aphl_baseline.json` translates into XPath. `aphl_baseline.json`
is the floor: nothing it catches today stops being caught unless the scope document says so.
Today's baseline, plus the gaps filled, covers:

- any clinical statement change, including nested statements, new sections, and status and
  code changes
- a section's own change, and a narrative-only section populated or expanded
- patient deceased, birth time and name, and encounter end time

**A rule names what to watch, not where it sits.** It picks from catalog names: unit, base
template, change kind and trigger marking, with section as an optional filter. So "any
trigger-coded result, wherever it appears" is one rule, and today's
`//hl7:entry/descendant-or-self::*` is one rule too ("any entry change").

**How what's actionable changes.** Today the configuration is a JSON file bundled in `core`
and named in code (`configurations/__init__.py:8-13`, `lambda_function.py:68-70`), so even
an XPath edit ships as a DiD release; persistence is post-MVP (`Configuration-Spec.md`).
Under the catalog:

| the change                                                                     | path                                                  |
| ------------------------------------------------------------------------------ | ----------------------------------------------------- |
| a different choice among names the catalog has                                 | a configuration edit, shipped as today                |
| something the catalog doesn't name (a template's meaningful field, a new kind) | a `dibbs-ecr` minor release, then DiD takes it        |
| needed before the catalog can name it                                          | an XPath rule, matched against the findings' elements |

The XPath rule form stays as that escape hatch, so no change takes longer than it does today.
`Configuration-Spec.md` moves to catalog names.

> [!NOTE]
> **APHL Q16: can one rule span every section, such as "any trigger-coded result wherever it
> appears"?**
>
> Yes. Rules name a unit, template, change kind or trigger marking; a section is an optional
> filter, not the way rules are organised. Nothing is repeated per section.

> [!NOTE]
> **APHL Q17: can the catalog work start from the MVP scope document?**
>
> Yes, and it should: `aphl_baseline.json` is a translation of it. The scope document is the
> source, and `aphl_baseline.json` the floor, so nothing caught today is lost by accident.
> We'll check the catalog against it when it arrives.

> [!NOTE]
> **APHL Q18: if the catalog doesn't name something, what's the path, and the turnaround?**
>
> A choice among existing names is a configuration edit. A new name is a `dibbs-ecr` minor
> release that DiD then takes. Until that lands, an XPath rule covers it, so no change waits
> longer than today. Today's XPath edit is already a DiD release, since the configuration is
> bundled in the code.

### Input

- **Refined documents.** Two documents of one `setId` are enough, as today. A refined section compares
  equal only if both the sender's content and the Refiner configuration are unchanged.
  - The Refiner seeds `setId` on jurisdiction and scope only (see `setId` continuity). So a
    configuration change keeps the stream and changes what it retains, and a newly retained
    entry gets `did-add-detected` with no sender change.
  - Whether it should is the Lambda's baseline question ("previous" vs "last delivered"; Out
    of scope).
  - DiD logs a `config_version` mismatch between the two versions' footnotes
    (`narrative/footnote.py:148`).
- **Earlier DiD authors.** An input may already have been through DiD once, so it carries
  DiD's authors: a reprocessed document, or a test built from DiD's output. The multicode
  fixture is the latter: APHL shared only its augmented files, and its v1 carries DiD's
  `did-no-change` header author. They are non-clinical and kept, because authors accumulate
  `[aug-v5-v2 §1.1]`. "One author per statement" is per pass. A Refiner author is logged, so a
  refiner-driven difference can be told apart, but it isn't used in comparison.

> [!NOTE]
> **APHL, Input: are document version comparisons, and the `setId` requirement, changing?**
>
> No. DiD still compares two documents of one `setId`, and the Lambda still finds the
> baseline by the input `setId` (`lambda_function.py:179-183`). What changes is the seed of
> DiD's _output_ `setId` (`setId` continuity), not what DiD needs as input.

> [!NOTE]
> **APHL, Input: is an "earlier pass" a prior document in the encounter, or a prior tracked
> change in the same document?**
>
> Neither: it's a run of DiD over the same document before. The multicode fixture's v1 is
> DiD output, so it already carries DiD's header author. The wording above now says so.

### What `dibbs-ecr` provides, and what DiD keeps

| from `dibbs-ecr`                                   | in DiD                                   |
| -------------------------------------------------- | ---------------------------------------- |
| section catalog and version detection (v0.1)       | pairing cascade and ambiguity handling   |
| RR reportable conditions by jurisdiction (v0.1)    | what is actionable (baseline config)     |
| augmentation writer behind `AugmentingTool` (v0.1) | function-code choice, placement          |
| template records, layers 1-3                       | DiD's `setId` and id derivation          |
| change-kind vocabulary, generic and refined        | narrative normalisation and section rule |
| the 11 author-capable types                        | findings model and output                |

### Measurement

The rewrite logs:

- **per finding:** base root, `paired_by`, kind, and step 4's differing fields
- **per unpaired original:** why it didn't pair, and its base root
- **per document:** input and output `setId`, `encounter_type` (captured but unlogged today,
  `did_lambda/telemetry.py:34`), the RR's reportable conditions, and the verdict (no change,
  no actionable change, or actionable), with its deciding rule and the version compared
  against

Today's telemetry records none of these per document: `encounter_type` and conditions exist
only as aggregate metrics (`telemetry.py:246-273`). With them, #147 is visible in production, failures
group by condition, and `paired_by` shows which step does the work.

### Testing

- **Expectations:** findings (unit, kind, `paired_by`) are asserted from the start; authors are
  expected-to-fail until projection. A docker-free harness below the Lambda compares an
  explicit pair against its expectation file.
- **`did-test-package-1` first.** It's two three-version chains, original and refined. The
  tester's 8 marked changes per chain are ground truth. The refined files lose the comments,
  so their labels are mapped from the originals. Unmarked differences measure incidental
  churn. It's mostly additions, so it doesn't exercise #147.
- **The Mon Mothma chain:**

  - a statement added inside a concern
  - a section populated from `nullFlavor`
  - a narrative-only section stating the outcome
  - attribute-only changes

  Its known data defects are listed with the fixture, so they aren't read as test intent:

  - the flu variant reuses v3's `ClinicalDocument/id`
  - a `potalCode`
  - a 2020 encounter date
  - a trailing space in `"94310-0 "`

- **The gap documents and #147's three files** become acceptance fixtures, with function codes
  checked as well as counts. Each changed statement gets one author, with no DELETED + ADDED.
  DiD expects 3 for stable-key, not 6 (Appendix).
- **`setId` continuity:** one output `setId` per package-1 chain, original and refined, and
  the same `setId` after a changed jurisdiction list.
- **Coupled tests** (augmented-output snapshots, and the ladder, pruning and change-type code
  tests) are turned off or expected-to-fail while their code is reworked, then replaced.
- **Synthetic regenerated-id pairs**, with expected outcomes:

  | case                                              | expected                                                              |
  | ------------------------------------------------- | --------------------------------------------------------------------- |
  | a corrected code on a singleton                   | pairs at step 3, `paired_by: singleton`                               |
  | the same, among peers of its template             | step 4 if only the code differs; step 5 (`unmatched`) at three fields |
  | a corrected code whose `effectiveTime` also moved | pairs at step 4                                                       |
  | a result gaining the trigger template             | pairs, with one `populated` finding                                   |
  | three problem concerns, one gaining a diagnosis   | each concern pairs through a Problem Observation                      |
  | two encounter diagnoses, one trigger-coded        | each pairs through its Problem Observation; no `did-add-detected`     |
  | a trigger diagnosis gaining `negationInd="true"`  | pairs, with one `trigger_retracted` finding                           |

**The fixtures aren't a model of production.** [computed] The stable-key fixture's five
"panels" are one result pasted five times, where a real `99449-1` reports a couple of dozen
pathogens.
What the cascade has to get right depends on how real senders version documents, which only
real version streams show (DQ4, DQ5). Until then, DiD builds synthetic pairs
shaped like real messages:

- panels gaining results
- P → F → C on `4.419` and `4.418`
- corrected values and qualitative flips
- every `<id>` regenerated
- vendor or missing templates
- text-to-code translations
- sections added or going to and from `nullFlavor`
- a one-out-one-in under a stable-id sender
- a Refiner fan-out pair

No production-derived documents are used without written APHL clearance.

### Consequences

- **Body collapse goes**, first through section units over today's matcher (Phase 1a).
- **Id churn goes** wherever an `<id>`, a nested `<id>` or identity fields pair a statement,
  and is reduced elsewhere. **Earlier augmentation** goes through layer 2.
- **Gaps 1-5 and #147 close**, except for leftovers step 4 can't pair. [inferred] If ids are
  widely regenerated, #147's common form rests on steps 3-4.
- **A sole statement genuinely replaced** under an id-regenerating sender (one diagnosis ruled
  out, another made) reads as one update with before and after. [computed] Today's matcher
  reads it as an update too, but without values: UPDATED `<value>` and `<low>`. A PHA rule
  keyed on "new = added" would miss it, unless DiD policy treats a singleton with changed
  identity fields as an addition. Under a stable-id sender, it reads as added.
- **Every finding explains itself**, which today's output can't.
- **Entry authors are a deployment setting** from Phase 0, written by today's placement until
  projection replaces it. The setting's default is pending (APHL Q19).
- **Retired:** the ladder, pruning and change-type codes. The XPath configuration form is
  kept only as an escape hatch (Baseline configuration).
- **`dibbs-ecr` grows a template model** the Refiner can later use (ADR 0010, Option D).
  Curation is ongoing.
- **Only partly addressed:**
  - header changes outside the patient and encounter units
  - cross-entry links (`related`)
  - removals (the footnote can list them; `<author>` waits on the IG)
  - display-name churn, which stays a finding
- **Not addressed:** diffing the RR (Out of scope).
- **Unknown unknowns.** The cascade isn't built, and real senders will produce cases no
  fixture models, as the Refiner learned from Epic (#1504, #1522, #1763). The concern and
  encounter-diagnosis rows, and the trigger retraction, all surfaced in one review round. The silent pilot is how such cases surface. Each is fixed
  by curation or a threshold, not redesign.

### Out of scope

- Removal flags (gap 6), pending APHL and the IG.
- Baseline choice. Today it's the latest earlier _actionable_ version
  (`did_lambda/dynamodb.py:25-36`), so the verdict decides it; see the actionability spike.
- Delivering findings beyond the augmented document.
- Diffing the RR.
- Cross-section links (order → result), the first to build after Phase 3. This is what
  answers "is the case confirmed?"
- Reading narrative content.

## Open Questions

- **Should DiD create its own output at all?** The IG gives DiD a new `id` / `setId` and a
  `relatedDocument` for its input `[aug-v5-v1 Table 1]`, which gives IG conformance and
  provenance. Gating and annotating only, passing `setId` through as received, would give
  continuity by construction. This ADR keeps the IG pattern until that's settled.

## Our questions to APHL (DQ1-DQ8)

These are ours, numbered DQ so they don't collide with APHL's Q1-Q19 in the callouts. Each has
a proposed answer, so work proceeds; a different answer changes a rule, not the design. DQ3,
DQ7 and DQ8 are answered from PHA and APHL feedback on the output (Phase 3).

1. **DQ1. Id-only changes:** should an otherwise unchanged entry ever be flagged (an open
   question on the gap deck's slide 25)? _Proposed:_ no; it's `identity_only`. Stable-key
   then expects 3 flags, not 6.
2. **DQ2. Singletons:** should the only element of its kind still pair (also slide 25)?
   _Proposed:_ yes, except where something in scope paired by `<id>`.
3. **DQ3. Panels:** should the organizer be marked when only a result changed? _Proposed:_ no; it
   would need a weaker code.
4. **DQ4. Test documents:** how were they built, and which edits were deliberate?
5. **DQ5. Real version streams:** can APHL supply or clear them, edited as little as possible?
   Ideally:

   - one `setId` across three or more versions, with RRs
   - more than one EHR vendor
   - a full lifecycle: suspected → ordered → preliminary → final → corrected
   - sections with several entries of one template

   They'd confirm production points 1 and 2, and show which ids senders keep.

6. **DQ6. The Trifolia export**, for the MAY constraints the Schematron omits.
7. **DQ7. `did-*` codes:** the IG already gives DiD `unchanged-removed` and `unchanged-flagged`
   (`[aug-v5-v1]` Table 1; `[aug-v5-v2]` lines 779-780), which mark _unchanged_ content. DiD
   marks what changed, which those can't express. _Proposed:_ add the `did-*` codes to the
   DYNAMIC value set (CONF:5573-43), including `did-unmatched-detected` for a statement that
   may be new or a changed one DiD couldn't match (Pairing, step 5). Was "unchanged" the
   intended model?
8. **DQ8. Removals:** how should one be represented, when an author can only sit in the newer
   document? Is `unchanged-removed` meant to cover this?

## Appendix

### Why not the RIM's split

The RIM splits act properties into _inert_ (about the record) and _descriptive_ (about the
act), and `negationInd` negates only the descriptive ones `[cda-book line 3726]`. It puts
`moodCode`, `id`, `statusCode` and `author` on the inert side
`[cda-book Table 12.4, lines 3736-3749]`. That answers what negation applies to, not what's
meaningful: `active` → `completed` is about the record, and still news to a PHA.

### Fixture expectations

- **Stable-key:** [computed] results 2-4 differ only in ids, so they pair (2 and 3 by
  `nested_id`, 4 under its organizer) and get no author. Results 1 (code) and 5
  (`statusCode`) get `did-update-detected`, as does Encounters for 46240-8 → 46240-7. That's 3
  expected against APHL's 6, pending DQ1.
- **Codes one at a time:** APHL's 3 stands, including the `@displayName` correction.

### Suggested Implementation Tickets

These are in DiD unless marked `dibbs-ecr`. A phase isn't done until its exit holds, and the
order is the part most open to feedback.

**Phase 0: ground and guard.** A measurable target and a safe floor.

- `test: did-test-package-1 difference inventory and expectations`: every difference, marked
  and unmarked. The marked ones become expected findings, mapped onto the refined files.
- `test: comparison harness and acceptance fixtures`: findings asserted, authors
  expected-to-fail, the pass count as progress
- `test: setId continuity`: the jurisdiction case fails today, and that's the point
- `fix: setId seed without jurisdiction`: after deciding how streams in flight cut over
- `feat: entry authors as a deployment setting, and decouple the coupled tests`: the verdict
  and diff output keep working with entry authors off. Snapshots are re-taken in this change
  alone. The default waits on APHL Q19.
- `feat: shadow comparison`: the Lambda runs a second comparison alongside the live one and
  logs its changes under their own event name, writing nothing. Today it has one path
  (`lambda_function.py:211-257`). Phase 1a and the Phase 1 pilot both run through it.

**Phase 1a: section units over today's matcher.** No more body collapse.

- `chore: adopt dibbs-ecr v0.1` (Refiner ADR 0017): drop the augmentation fork, take
  reportable conditions, raise `requires-python`, with no behaviour change
- `feat: section units and header pseudo-sections`: sections pair on `<id>`, then the
  co-asserted `templateId` root set, then LOINC. Today's matcher runs inside each pair, and
  among sections that don't pair uniquely. It runs in shadow first.

Exit:

- the harness's diff output is unchanged wherever the body already paired (package-1, the gap
  fixtures, the Mon Mothma chain)
- `/ClinicalDocument/component` ADDED/DELETED is zero in the shadow run's queries
- going live is decided from the verdict shift that run shows

**Phase 1: classify.** Added, updated and removed are right and explained. Each ticket shows
its effect on the fixtures.

- `feat: findings model`, carrying what both a footnote row and an `<author>` need
- `feat(dibbs-ecr): generic attribute meaning and change kinds`: layer 2, which defines
  `identity_only` and the non-clinical split
- `feat: pairing by id and field comparison`: step 1 replaces the matcher, with
  `identity_only`
- `feat(dibbs-ecr): template structure from Schematron`, for 3.1.1 and 1.1 with one
  generator, and a regeneration test
- `feat(dibbs-ecr): conformance chain from Volume 2`: the "Conforms to" statements, checked
  against the co-asserted roots in the IG's examples, and diffed against APHL's extraction if
  they send it (APHL Q13). Base root replaces the `templateId` root set in section pairing.
- `feat(dibbs-ecr): template meaning for the baseline templates`:
  - the trigger-code result and `4.419`
  - the other trigger templates, with `trigger_retracted`
  - the Problem Concern Act and Encounter Diagnosis
  - identity fields for each fixture template. These are per template, never one key per
    statement kind (B2).
- `feat: pairing by identity fields and singleton (steps 2-3)`
- `feat: the narrative-only section rule`
- `feat: telemetry for findings`
- `feat: similarity pairing for leftovers (step 4)`: no weights, ties refuse, off for
  stable-id senders
- `chore: silent production pilot`: runs through the shadow comparison, writing nothing, compared with
  the silent-evaluation queries: the `paired_by` distribution, the unmatched rate per base
  root, and step 4's differing-field counts. New edge cases become curation tickets.
- `spike: generic fallback for ambiguous sections`, from the pilot's ambiguous sections: how
  many, which senders, and what they hold. Modelled on the Refiner's specific/generic split.

Exit: the fixture findings pass, and the pilot's unmatched rate and `paired_by` distribution
are understood.

**Spike: what does actionability decide?** This comes after classification is fixed.

Today:

- v1 is always actionable, and gets a `did-no-change` header author: it has no baseline, so
  nothing was compared (DID-004)
- later versions are actionable if any change matches a rule
- a diff failure fails the whole manifest (`lambda_function.py:138-142`); the model's
  `True` default (`core/models.py:71`) is never reached
- non-actionable versions are dropped from the baseline

[inferred] That reads as "did anything change", not a judgement. Data quality is out of
scope, since inputs are valid reportable eICR/RR pairs.

The spike asks whether the verdict separates meaningful versions from noise, and what the
baseline filter does to later comparisons. Output: keep, redefine or drop the verdict, and
keep it if it's correct and fast on fixed findings. The result is recorded in
`docs/algorithms/ecr-diff.md`.

**Phase 2: judge.**

- `feat: baseline configuration v2 on the named-element catalog`, from APHL's MVP scope
  document with `aphl_baseline.json` as a regression floor, `Configuration-Spec.md` on catalog
  names, and the XPath rule kept as an escape hatch

**Phase 3: project.** Authors and footnote ship together.

- `feat: author placement from findings`: replaces today's placement, under the Phase 0
  setting
- `feat(dibbs-ecr): provenance footnote`, shared with the Refiner and rendered through the
  stylesheet, with a rendered example for APHL's Standards team
- `chore: PHA and APHL feedback on the output`, which answers DQ3, DQ7 and DQ8
- `docs: propose DiD's codes to the IG`, including `did-unmatched-detected`
- `chore: retire the stable-key ladder and outermost pruning`, once nothing writes from the old
  pipeline

**Spike: narrative content.** This is independent of the phases. What does a narrative change
mean across vendors, and does the stylesheet's rendering give a stable view?

### Links

- 0001 Adopt decision records
- Refiner ADR 0017 (`dibbs-ecr`; Proposed), ADR 0010 (defers the template-aware model)
- APHL's DiD gap analysis deck (22 October 2026) and test files, linked from #147
- [CDCgov/dibbs-ecr-diff#147](https://github.com/CDCgov/dibbs-ecr-diff/issues/147)
