# 2. Section-scoped, template-aware comparison

Date: 2026-10-27

Measured against `dibbs-ecr-diff` @ `0cca149` and `dibbs-ecr-refiner` `main` @ `8cb55264`.

## Status

Proposed

## Context and Problem Statement

DiD compares two versions of an eICR (same `setId`) and stamps the newer one with authors that
tell a public health agency (PHA) what changed. Today it does that as one whole-document diff:

- every element gets a stable key from a twelve-rank fallback ladder
  (`core/cda/stable_key.py:48-62`). Pairs match on that key, and anything unmatched is
  reported as ADDED or DELETED.
- `_prune_to_outermost` (`diff_collector.py`) reduces each added or deleted subtree to its
  top node.
- a watch list of XPath rules decides which changes are actionable
  (`configurations/aphl_baseline.json`). It flags any change under `//hl7:entry` plus four
  header fields: patient deceased, birth time and name, and encounter end time.
- `augment.py` places one author per (element, function code), taking the function code from
  the change type.

APHL's evaluation found that this does not tell PHAs what changed, from two directions.

### What production shows (silent evaluation)

Measured over the CloudWatch Logs Insights export of DiD's silent evaluation in production
(queries q01 common change paths, q04 change-count distribution, q07 changes by version),
reproduced 2026-10-26 with the raw logs and the metrics agreeing to 0.05%.

1. **The document body fails to pair.** `/ClinicalDocument/component` is reported
   ADDED 14,981,552 and DELETED 14,981,501 times against at most 16.7M comparisons at
   version ≥2, so it fails in at least 89.7% of them. (The ≥2 filter rests on the manifest's
   `version_number`, which carries a constant (310) in some streams, so the denominator
   includes some non-comparisons; that only strengthens the bound.) The diff never descends
   past an unmatched node (`diff_collector.py:182-186`), so the real changes in those
   documents are never visited, let alone reported. The mechanism, probed: the body's key
   is built from its sections' `<id>`s, or from their `templateId`s when there are at most 12
   of those. eICR sections usually assert two each, so a body with more than six sections has
   no `templateId` key. Probed with eight sections whose `<id>`s are regenerated between
   versions, the only output is ADDED + DELETED `/ClinicalDocument/component`.
2. **Identity is diffed as content.** Even in entries that pair, the
   sender's instance `<id>` is reported deleted and re-added: 168.8M symmetric `…/id`
   changes across five paths. These can only come from documents whose body paired, and the
   change counts are heavily skewed: [stated] q04's mean is 31.7 against a median of 6.0
   and a p95 of 18.0 (Insights' percentile is an estimate), so [computed] the top
   5% of documents hold at least 46% of all changes. [inferred] The id churn therefore
   describes a minority of documents, possibly senders that keep section ids stable but
   regenerate entry ids. It is real, but not evidence of what a typical document does.
   Earlier augmentation authors (from tools upstream) add ±30.0M as content, and
   renumbered narrative pointers add about 40M `…/reference` updates.
3. **Narrative is a large share of what is reported.** `…/text/table/tbody/tr` is ADDED
   89.4M and DELETED 60.1M times; `…/tr/td` is UPDATED 72.2M times. Narrative has looser
   rules than entries and may or may not be linked to them, so most of this volume says
   little about what changed clinically.
4. **12.1% of reported changes have no coded section.** They are header and uncoded content.

Points 1 and 2 are arithmetic signatures in aggregate telemetry, not observed documents.
Real v1 → v2 pairs would confirm them; they are being requested from APHL.

### What controlled input shows (gap analysis)

APHL's gap analysis (deck of 22 October 2026, linked from #147, with its test files and
DiD's outputs) ran synthetic version pairs
with known changes. Every pair matched at the body, so none of them exercised point 1 above:
[computed] none of the six DiD diff outputs APHL supplied (54 changes) reports
`/ClinicalDocument/component`, and every path is inside a section. The fixtures keep their
one section `<id>` and every entry `<id>` identical from v1 to v2, so they don't model id
regeneration either (point 2). The gaps are in placement and classification. Across its
four scenarios DiD placed 31 flags against 38 expected (deck slide 3):

| scenario                     | placed / expected |
| ---------------------------- | ----------------- |
| nested and complex (v1 → v4) | 15 / 23           |
| multi-code update            | 6 / 6             |
| codes updated one at a time  | 4 / 3             |
| stable key changes           | 6 / 6             |

Matching counts aren't passes. For multi-code and stable key, APHL's notes say the count is
right "but code most likely incorrect": that's gap 5 and #147.

| gap | what happens                        | cause today                                                                                            |
| --- | ----------------------------------- | ------------------------------------------------------------------------------------------------------ |
| 1   | new section's statements unflagged  | pruning keeps one added node                                                                           |
| 2   | nested new statements unflagged     | same                                                                                                   |
| 3   | a section's own change unflagged    | rules match entries, never the section                                                                 |
| 4   | two authors on one statement        | a changed `@code` splits into DELETED + ADDED (`CODE_RANK`), deduplicated per (element, function code) |
| 5   | existing statement flagged as added | `_get_function_code_for_change` takes the function code from the child's change type                   |
| 6   | removals unflagged                  | `augment.py` drops DELETED -- out of scope, pending APHL and the IG                                    |

[#147](https://github.com/CDCgov/dibbs-ecr-diff/issues/147) is the classification side of
the same problem. A corrected code, or an `<id>` that gains an `@extension`, reads as a
deletion and an addition instead of an update. It shares the production root cause: DiD
uses identity either as the pairing key or as content.

### What neither shows

`change_path` carries no `templateId` and no values, so content-level classification is
invisible in production telemetry. That covers narrative changes, trigger-code changes, the
missing before/after values in today's output, corrected codes, and #147 itself. They are
found only by probe and synthetic files.

### Precedent and what is now available

- The 2025 Rhapsody DiD and its requirements 2-3 compared section by section.
- `dibbs-ecr` (Refiner ADR 0017) is the proposed shared package of eCR specification
  knowledge. Its first release would provide the section catalog, the version map, RR
  parsing and the augmentation writer. 0017 is itself still Proposed and `dibbs-ecr` v0.1
  hasn't shipped, so **this ADR depends on 0017 being accepted**. If 0017 changes, the F2
  placement fix and the DiD-only tickets still stand; the tickets marked `dibbs-ecr` land in
  DiD instead, behind the same interface.

**The question: how should DiD decide what changed between two eICR versions, so that it
fixes what APHL flagged and stays explainable?**

## Decision Drivers

- Fix what APHL flagged:
  - gaps 1-5
  - #147
  - the production signatures: the body failing to pair, ids diffed as content, and earlier
    augmentation diffed as content

  The exception is a statement whose `<id>` and identity fields both changed and that
  matches no single leftover at step 4 (Pairing). It is reported as added, and the pilot
  measures how often that happens.

- Deterministic and explainable: every finding can say why it paired and what changed. No
  weighted scoring, no learned models. The Lambda has little memory.
- A missed pairing fails safe: it degrades to today's DELETED + ADDED, never to a silent drop.
- Works on refined and unrefined documents alike.
- Specification comes from `dibbs-ecr`; DiD's choices (what matters, where flags go) stay in
  DiD.
- The improvement is measurable in production with the same queries the silent evaluation
  used.

## Considered Options

### A. Unit of comparison

- **A1. Whole document (today).** One key path from the root; a body or section that fails
  to pair takes everything beneath it (context 1).
- **A2. Section-scoped (RECOMMENDED).** Sections pair on a shared `<id>`, then their base
  template root, then LOINC; entries pair only within their section, and a failure stays
  inside one section. It matches how PHAs read documents and how the Refiner configures
  them.
- **A3. Entry-global.** Pair entries across the whole document. This loses section context
  and makes near-identical entries in different sections compete.

### B. Pairing entries

- **B1. Stable-key ladder (today).** Pairs on whatever key ranks first. A regenerated `<id>`
  or a changed `@code` splits one entry into two (context 2, gap 4, #147).
- **B2. One clinical key** (`code` + `effectiveTime` for every template). Fixes the
  regenerated `<id>`, but a corrected code with the same `<id>` regresses, because the key is
  the thing that changed. It is also the wrong key for some templates: on a Problem
  Observation `code` is the problem _type_ and the diagnosis is `value` (CONF:1198-9045,
  CONF:1198-9058).
- **B3. A cascade (RECOMMENDED).** Pair on a shared `<id>`, then on the template's own
  identity fields, then on a singleton, then on a single similar leftover. Anything left is
  reported as ambiguous. The id-only
  case and the corrected-code case need opposite keys, and the cascade serves both. The
  identity fields are per template, which is what separates step 2 from B2.

### C. How actionability is configured

- **C1. XPath rules (today).** Users write paths against document structure. They can't
  express "a section's own change" or "the result was finalised", and a broad rule like
  `//hl7:entry/descendant-or-self::*` flattens everything to one level of salience.
- **C2. A named-element catalog (RECOMMENDED).** Code defines units, pairing keys and kinds
  of change per section and pseudo-section; configuration picks from it. XPath stays an
  implementation detail, tested against IG examples.

### D. Flag placement

- **D1. Outermost changed node + change type (today).** This causes gaps 1, 2, 4 and 5.
- **D2. Placement from findings (RECOMMENDED).** An author goes only on a section or one of
  the nine clinical statements. There is one author per statement per pass, and its
  function code comes from the statement that carries it.

### E. Where the template knowledge is decided

- **E1. A separate template-model ADR before this one.** It would design the model before
  anyone states what it is for, which is how Refiner ADR 0010 (Option D) came to defer it.
- **E2. In this ADR, built in `dibbs-ecr` (RECOMMENDED).** This ADR states which template
  knowledge the fixes need and why. The code lands in `dibbs-ecr` under Refiner ADR 0017's
  admission rule, which lets specification in once one product needs it. That makes every
  piece of the model traceable to a gap. The cost is that DiD's needs shape the model first;
  the Refiner's matching and reconstruction needs are fitted in later, not designed for up
  front.

### F. Sequencing

- **F1. Rewrite only.** PHAs see no placement fix until the rewrite lands.
- **F2. Placement fixes first, then the rewrite (RECOMMENDED).** Gaps 1, 2, 4 and 5 are
  fixable in `augment.py` on today's matcher, so PHAs get correct flags before the rewrite
  lands. The cost is writing placement twice if the rewrite changes what a finding is; the
  acceptance fixtures carry over unchanged, so the second version is held to the same
  expectations.

  Its reach is limited. Today's matcher still collapses the body (context 1), and a
  collapsed body is actionable regardless of content, since the added body contains entries
  (probed). Under the added-wrapper rule,
  that would flag every section and statement as added. So the F2 fix never treats the
  document body as an added wrapper, and a collapsed document keeps today's output: one
  generic `did-add-detected` on the first section. Pairing the lone body on today's matcher
  instead was considered and rejected: [inferred] entries with regenerated ids would then
  fail to pair one by one (context 2) and be flagged as added just the same. The F2
  improvement therefore reaches senders with stable ids, which is what the fixtures model.
  Production gets better with the rewrite.

## Decision Outcome

Proposed: **A2 + B3 + C2 + D2 + E2 + F2**.

In short:

- the units are sections (paired on a shared `<id>`, then base template root, then LOINC),
  two header
  pseudo-sections, and entries, each `<entry>` compared as one pattern
- entries pair by a five-step cascade inside their section: shared `<id>`, identity fields,
  singleton, similar leftover, else ambiguous. Each finding says how it paired
- ids, augmentation authors and what upstream tools added are non-clinical, so id churn and
  earlier augmentation never surface as change
- narrative is read only in narrative-only sections, and only when it gains content
- an author goes on the section or statement that changed, one per statement per pass
- placement fixes ship first on today's matcher; the rewrite pilots silently against
  production before PHAs see it

### Units

- **Sections** pair on a shared section `<id>`, then their **base template root**, then
  LOINC, each unique on both sides; otherwise ambiguous, reported as added + removed, and
  only that section is affected. A templated section's LOINC is fixed by its template
  (Encounters Section SHALL be 46240-8, CONF:1198-15467), so a LOINC change is a section
  finding, not a reason to stop pairing. APHL's stable-key fixture changes exactly that
  (46240-8 → 46240-7, templateIds identical).
  - the base root is the top of the "Conforms to" chain. Encounters Section (entries
    required) `2.22.1` conforms to Encounters Section (entries optional) `2.22`, so `2.22` is
    the base, and a section asserting either pairs with one asserting the other
  - a nested `section/component/section` pairs within its parent section's pair
  - a section with no recognised `templateId` pairs on LOINC alone, or is ambiguous
  - each document uses the `dibbs-ecr` section catalog for its own detected version. The base
    root ignores extensions and LOINC is the fallback, so [inferred] a 1.1 → 3.1.1 pair still
    lines up; confirm against the 1.1 catalog

  A section with no counterpart is new or removed as a whole.

- **Header pseudo-sections.** `patient` (`recordTarget/patientRole`) and `encounter`
  (`componentOf/encompassingEncounter`) are compared as units with their own named
  elements, so the patient and encounter share of the 12.1% of changes outside coded
  sections has somewhere to belong. The rest of the header is compared but is not
  actionable under the baseline, as today.
- **Entries** are the unit. An `<entry>` and everything in it is compared as one pattern,
  so a panel is one unit, not a set of results to filter. (The Refiner prunes individual
  results at `organizer/component` because it builds condition-specific output; DiD only asks
  whether the entry is the same with new or changed information.) The entry's top-level
  clinical statement pairs within its section and template, and what it contains counts as
  evidence for that pairing (Pairing, step 1). Once paired, a clinical statement nested inside
  it (through `entryRelationship` or an organizer `component`) is paired the same way, within
  its parent pair (gap 2), so placement can still name the statement that changed.

  A template marked as a _qualifier_ under its parent (such as `4.419`) is the exception: it
  is compared as a field of its parent, not paired, and its changes are its parent's
  findings. Under a result organizer, organizer-scoped context is a qualifier of the
  organizer:
  - Laboratory Result Status `4.418` (CONF:4527-443)
  - Specimen Collection Procedure `4.415` (CONF:4527-450)
  - any statement that isn't an `<observation>` or nested `<organizer>`, whatever its
    `templateId` or lack of one (Epic sends specimen `<procedure>`s untemplated)

  The organizer rule decides by statement kind, as the Refiner's shared-context guard does
  after name-based versions failed both ways (`entry_match_rules.py:702-725`, Refiner
  #1522, #1763).

### Template knowledge (built in `dibbs-ecr`)

Three layers. The first two are generated or written once; the third is curated per template
and cites its CONF.

1. **Structure, per template -- generated**, with each part from the source that carries it.
   Each record holds root, extension, name, kind, child slots with cardinality and CONF,
   parent context, and the template it constrains.
   - **slots, SHALL and SHOULD:** the vendored eICR 3.1.1 Schematron (826 rules covering
     151 templates when keyed on rule id, measured)
   - **slots, MAY:** not in the Schematron at all, since a MAY can't fail validation; the
     IG's Vol 2 has 363 "MAY contain" constraints and the Schematron none. That includes the
     `4.419` slot (CONF:4411-445) and the `4.418` slot (CONF:4527-443). They are added by
     hand in layer 3 as each template is curated, CONF-cited. The Trifolia export the
     Schematron was generated from would carry them all; ask APHL for it as the upgrade path
   - **constrains:** the IG's "Conforms to …" statements and co-asserted `templateId`s,
     which give the base root that pairing uses
   - **kind:** _clinical statement_ comes from the CDA R2 XSD element type. _Wrapper_ and
     _qualifier_ are roles a template plays under its parent, so they are marked in layer 3
   - **versions:** v0.1 generates 3.1.1. eICR 1.1 documents get section catalog records and
     fall back to element kind plus layers 2 and 3 until their Schematron (already vendored)
     is generated
   - the generator and its pinned sources move with the output, as `template_oids.py` does
2. **Generic CDA meaning, per attribute -- written once.**
   - **non-clinical:** `id`, augmentation authors, narrative `reference/@value`, and what
     an upstream augmenting tool added. An augmentation author is one whose `functionCode`
     (or `assignedAuthoringDevice/softwareName`) is in the `eCRDataAugmentation` code system
     `2.16.840.1.113883.10.20.15.2.7.1`. It is recognised by code system, not by `templateId`,
     because text-to-code writes no `templateId` on its authors (`dibbs-text-to-code`
     `eicr_augmenter.py:283-332`; the CONF:5573-29 gap). DiD reports what the sender
     changed, not what a tool earlier in the chain `[aug-v5-v1 Table 1]` added:
     - text-to-code's `<translation>`s. Text-to-code doesn't mark the translation itself
       (`eicr_augmenter.py:344-353`), only the entry it sits in, with an author (`:334-340`).
       So a `<translation>` on a statement that carries a text-to-code author in the newer
       version is non-clinical, whether text-to-code ran on one version or both. The cost:
       a translation the sender added to that same statement is hidden too
     - the Refiner's provenance `<footnote>`s in a section's `<text>`, which carry its
       `config_version` and outcome (`dibbs-ecr-refiner` `narrative/footnote.py:150-160`).
       They are removed before the narrative compare, so a configuration bump between
       versions doesn't flag every section
   - **clinical:** `moodCode`, `statusCode`, `negationInd`, `effectiveTime`, `nullFlavor`,
     and on a code `@displayName`, `originalText` and `sdtc:valueSet`. A corrected display
     name is an update, as APHL expects (gap deck slide 19). Gaining `sdtc:valueSet` marks a
     code as a trigger, so it is a `populated` finding

   This split is DiD's own. It deliberately departs from the RIM's _inert_ / _descriptive_
   split, which puts `statusCode` and `moodCode` on the inert side (Appendix, "Why not the
   RIM's split").

   A change to a non-clinical attribute is never reported as a clinical change. This is what
   removes the 168.8M id changes and the 30M augmentation-author changes from what is
   reported. A clinician `author` stays clinical, since who recorded a statement can matter.
   Most mood changes (planned → performed) also change the template, for example Planned
   Observation to Result Observation. Pairing is within a template, so they show up as a
   removal and an addition, not as a mood change on one pair.

3. **Template meaning -- curated, CONF-cited.** It holds identity fields, meaningful fields,
   and status models that refine `statusCode`. The canonical case is Laboratory Observation
   Result Status (ID) `4.419`, where F → C is `completed` → `completed` at layer 2 yet is the
   most important change. Its only context is the Initial Case Report Trigger Code Result
   Observation, where it is optional `[eicr-3.1.1 Table 152]`. So the finalised → corrected
   kind exists only for trigger-coded results that carry it; other results fall back to
   layer 2. A second status template, Laboratory Result Status (ID) `4.418`, sits on the
   Trigger Code Result Organizer and covers the whole battery (MAY 0..1, CONF:4527-443).
   Trigger-code templates are also marked here.

   Identity fields say where a template's clinical concept lives, which isn't always `code`:

   | template            | identity fields                                 | basis                                                                                                                          |
   | ------------------- | ----------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------ |
   | Result Observation  | `code` (with its translations); `effectiveTime` | LOINC test (CONF:1198-7133); specimen time (CONF:1198-7140). `value` is the result, so it's a meaningful field, never identity |
   | Problem Observation | `value`; `effectiveTime/low`                    | `code` is the problem type (CONF:1198-9045); the diagnosis is `value` (CONF:1198-9058); onset SHALL (CONF:1198-15603)          |

   Each identity field is compared on its own. A coded field compares as the set of the code
   and its `translation`s and matches on any shared (`@codeSystem`, `@code`), so a correction
   that only adds a translation still pairs. Fields are never pooled across locations.
   Pooling would let a code on one field match a code on another, which has no clinical
   meaning. A culture battery, whose results share a generic LOINC and time and differ only in
   the organism on `value`, is equal on identity either way; step 2's uniqueness rule is what
   sends it on to step 3 instead of pairing in document order.

   The Refiner's `services/ecr/specification/entry_match_rules.py` records, per section and
   CONF-cited, where each template's _trigger_ code can sit. Its Results rules read `code`,
   `code/translation` and `value` as "one statement described three ways" (precedence group).
   That answers "does this statement match a condition", not "is this the same statement
   across versions". It is the starting point for meaningful fields and trigger marking, and
   a cross-check on identity fields, not a source of them.

   - curation starts with the templates the gap fixtures and the baseline exercise
   - an uncurated template falls back to layers 1 and 2, which are still correct but less
     specific; extending it is curation, not redesign. For pairing, an uncurated template
     has no identity fields, so step 2 is skipped and step 4 compares its generic fields

**Change kinds** say what a field change _means_. They are derived from layers 2 and 3, so
they are specification and belong in `dibbs-ecr`.

- examples: `identity_only`, `populated`, `blanked`, `value_changed`, `status_changed`,
  `negated`
- kinds are layered: a generic kind (`status_changed`) can be refined by a template kind
  (`result_finalized`, `result_corrected`)
- a finding carries both, so a consumer that knows only the generic kind still works
- adding a kind is a minor release

Whether a kind _matters_ is policy, so it stays in DiD.

### Pairing

All pairing happens inside one section pair; nothing pairs across sections. Within a
section, candidates are grouped by template, and nested statements are paired inside their
parent's pair.

**Which template.** A statement usually asserts several `templateId`s, which are
conformance assertions that stack `[cda-book line 3978]`. A trigger-coded result carries
`4.2`, `4.2`/`2015-08-01` and `15.2.3.2`/`2019-04-01` `[eicr-3.1.1 Figure 117]`, and can gain
the trigger template between versions. So:

- the pairing template is the statement's **base template root**, the C-CDA template its
  eICR templates constrain (layer 1 records the chain)
- extensions are ignored. The IG contradicts itself on them: the organizer cites `4.418` as
  `2018-06-11` (CONF:4527-444) while the template requires `2018-09-01` (CONF:3378-373)
- a trigger-code `templateId` is a field, not identity: gaining one is a finding, which is
  how DiD becomes aware of trigger codes at all
- a statement with no recognised root (vendor templates, or none) falls back to its element
  kind and its slot under the parent

This is what the Refiner arrived at in production: its rules match on the base root
(`templateId[@root=…]`) so trigger-coded and plain statements share a rule, and its
shared-context guard decides by statement kind before `templateId` after Epic's proprietary
and missing templateIds broke a name-based version (Refiner #1522, #1763).

**The cascade**, in order:

1. **shared `<id>`** → pair. `id` is 1..* (CONF:1198-7137, CONF:1198-9043), so any shared
   (`@root`, `@extension`) matches. An `<id nullFlavor>` never matches, and an `<id>`
   repeated among siblings disables this step for those siblings. A statement also pairs here
   when a clinical statement nested in it shares an `<id>` across versions and no other
   candidate does (`paired_by: nested_id`): the panel is the same panel because its result
   is the same result. Root and root + `@extension` stay distinct identifiers, as CDA's
   instance identifiers are. (APHL's stable-key fixture changes two panels' ids, one gaining
   `@extension` and one a new root, while each keeps its result's `<id>`; both pair here.)
2. **template identity fields** (layer 3) equal, with exactly one candidate on each side →
   pair. Two or more equal candidates (a repeated test at the same time, a culture battery)
   fall through rather than pair in document order
3. **singleton** → pair: the only unpaired statement of its template among the candidates
   that share its scope, on each side. For a top-level entry the scope is its section's
   entries; for a nested statement it is its paired parent. It pairs even when its `<id>` and
   identity fields both changed, which is the likely production form of #147 (a corrected
   code with a regenerated id). The finding records `paired_by: singleton` and which identity
   fields changed, so DiD policy can treat it as an addition if it chooses.
   **Not applied in a scope where any statement paired at step 1** (by `<id>` or
   `nested_id`): that sender evidently keeps ids stable, so a leftover with a new id is new.
   Take a Problems section where `P1` pairs by `<id>`, `P2` is removed and `P3` is new: `P3`
   is reported added, not as an update of `P2`. This fails safe, towards added. APHL asks
   the question this answers ("should a single element of its kind under the same parent
   still pair?", gap deck slide 25), and this is DiD's proposed answer
4. **similar leftover** → pair. This is an 80/20 stop gap. What steps 1-3 left unpaired on
   each side is anti-joined within the scope and template. A new leftover pairs with an old
   one when all of these hold:
   - they share the template and the skeleton of nested templates
   - they differ in at most two meaningful fields (layer 3, or for an uncurated template the
     generic `code`, `value`, `statusCode` and `effectiveTime`)
   - each is the only such candidate for the other; ties refuse

   It catches what falls off one version and looks like something that seems brand new in
   the next. Examples are a corrected code whose `effectiveTime` also moved, and a previous
   version that carried no reliable code. The finding records `paired_by: similar` and names
   the fields that differed ("paired as a probable update: only `code` and `effectiveTime`
   differed"). The step 3 guard applies here too. [inferred] It should catch most such
   cases, not all; the two-field limit is set from pilot data (Measurement)

5. otherwise **ambiguous**: reported as added or removed, as today. This is what the
   cascade doesn't fix (leftovers differing in more than two meaningful fields, or tied at
   step 4), and the pilot measures how often it happens. Meaningful fields help pair only at
   step 4, only on leftovers, capped, and with the differing fields reported as the change;
   pairing on the field you are trying to detect would otherwise hide it

Inside a pair, DiD compares **fields**, not children matched recursively. That way a changed
`@code` is one `value_changed` on one statement, not a DELETED + ADDED (gap 4, #147). Nested
clinical statements aren't fields: they go through this same cascade (Units).

The order is chosen on correctness, not on which step fires most. The `<id>` comes first
because it is the spec's identity: "any act that needs to be tracked through time should have
an id" `[cda-book line 5678]`. Each later step compensates for senders that regenerate it. How
often each step fires is unknown until real pairs are seen (context 2); `paired_by` in
telemetry measures it (Measurement).

### Findings

Each finding describes itself:

- section or pseudo-section
- unit and template
- kind: generic plus refined
- `paired_by`: `id` / `nested_id` / `identity` / `singleton` / `similar`, plus the fields
  that changed when paired by singleton or similarity
- before and after values, with display names
- `related`: empty for now; it reserves room for cross-entry links such as order → result
  without a schema change

`identity_only` findings are recorded and never flagged: an entry whose only change is its
`<id>` gets no author. Flagging it would make every production document from a sender that
regenerates ids actionable (context 2). APHL asks "should an otherwise unchanged entry ever be
reported as added when only its identifier changed?" (gap deck slide 25), and this is DiD's
proposed answer. An empty list is the "nothing new" signal.

### Narrative

Narrative is largely left alone. Its rules are looser than those for entries, and it may or
may not be linked to them, so reading it properly is a separate problem.

- **Sections with entries:** the narrative isn't compared. A section's own change still
  flags it, whatever its statements carry: its `code`, `title`, `nullFlavor` or
  participations (APHL's rule, gap deck slide 11). Gap 3's fixture is this case: Results
  goes from `nullFlavor="NI"` to populated with its entries flagged, and the section gets
  `did-update-detected` too.
- **Narrative-only sections** (no `<entry>` in _either_ version) carry a section-level
  author, since `Section` is author-capable in CDA R2, for two findings only:
  - `section_populated`: the section was `nullFlavor` and now has content
  - `narrative_expanded`: the narrative seems to contain _more_ information. After removing
    `ID` attributes, `reference/@value` targets, Refiner footnotes and whitespace, it has
    more table rows, list items or paragraphs, or, if it has none, longer text. This is an
    80/20 test
- A new narrative-only section gets `did-add-detected`; either finding above gets
  `did-update-detected`. Any other narrative difference (shrinking, rewording, reordering) is
  not reported, so a removal never leaks in as a section update. A section that loses all
  its entries between versions (for example under a new Refiner configuration) is not
  narrative-only: its entries are removed, which isn't flagged, and its narrative isn't
  read.

Reading narrative _content_ is out of scope. That would mean deciding what a row or cell
change means, where no rules govern narrative layout and Epic, Cerner and Meditech each
structure it differently. It is a separate spike, and may use the CDA R2 / eICR stylesheet
as a window into rendered content.

### Placement

Placement runs after every finding is collected, so authors written during a pass are never
read back as content.

- **Who can carry an author:** a section or one of the nine clinical statements. With
  `ClinicalDocument`, that is the 11 author-capable types in the CDA R2 XSD (9 + `Section` +
  `ClinicalDocument`).
- **Changes:** a change walks up to the nearest author-capable statement that isn't a
  qualifier and gets `did-update-detected`. A qualifier (`4.419`) belongs to its parent's
  finding.
- **Added wrappers:** read through one level, then flag the wrapper and every section or
  statement beneath it with `did-add-detected` (gaps 1, 2). The document body is never an
  added wrapper (F2).
- **One author per statement per pass.** The function code comes from the statement the
  author sits on, not from a child's change type (gaps 4, 5).
- **Header pseudo-sections** place their authors on `ClinicalDocument`, as today
  (`augment.py:810-812`), since `recordTarget` and `encompassingEncounter` can't carry one.
  They keep today's function codes: `did-patient-deceased`, `did-patient-birthTime`,
  `did-patient-name`, `did-encounter-closeTime`. All `did-*` codes are outside the bound
  _Data Augmentation Tool Operation_ value set `[aug-v5-v2 CONF:5573-43]`. The value set is
  DYNAMIC, so they are proposed to the IG rather than changed here.
- **Removals are not flagged** (gap 6, out of scope).

**Panels.** `<entry>` can't carry an author, since it is a relationship, not an act. For a
panel the choice is between the organizer, its results, or both. CDA conducts context down the
tree: a statement's author is the nearest one found by
`ancestor-or-self::*[cda:author][1]/cda:author` `[cda-book lines 3771-3775]`. So
`did-update-detected` on a panel says every result in it was updated, which overclaims when
one result of five changed. Few receivers follow that inheritance anyway ("relatively few CDA
processors are fully aware of the ITS context conduction rules", `[cda-book line 3779]`),
which is why gap 2 wants each new result flagged explicitly. The author goes where the change
is:

| what changed                                  | author on                                        |
| --------------------------------------------- | ------------------------------------------------ |
| new panel                                     | the organizer, and each result in it (gaps 1, 2) |
| the panel itself (its code, status, specimen) | the organizer                                    |
| one result's value, status or code            | that observation only                            |
| a new result in an existing panel             | that observation (gap 2)                         |

This is APHL's rule (nearest section or statement, gap deck slide 28), and it matches what
CDA's inheritance implies. Whether PHAs reading at panel level also want the organizer marked
when only a result changed is open with APHL (Questions to APHL). If they do, the panel needs a
distinct, weaker code, since `did-update-detected` there claims every result changed.

### Computation

One `SectionComparison` per section holds both originals for the whole pass. Pairing only
moves references between pools:

```python
@dataclass
class SectionComparison:
    section_key: str  # base template root; LOINC when the root isn't recognised
    old_section: _Element | None  # None: section is new
    new_section: _Element | None  # None: section was removed
    old_entries: tuple[_Element, ...]  # originals, never shrink
    new_entries: tuple[_Element, ...]
    pairs: list[tuple[_Element, _Element, PairedBy]]
    unpaired_old: list[_Element]
    unpaired_new: list[_Element]
```

- Invariant, asserted before the pass ends: every original is in exactly one of `pairs` or
  `unpaired_*`. Nested statements and nested sections get a comparison of the same shape
  under their parent pair, and the invariant holds at every level.
- Each unpaired original records why: `ambiguous` (candidates remained at step 4) or
  `no_counterpart`. Telemetry logs it alongside `paired_by`, so how often step 4 fires is
  measurable.
- Element references, not positional XPaths; XPaths are rendered only for output.
- Memory is bounded by one document pair. [inferred] That should be about the same as
  today's whole-document diff, since both hold two parsed trees; this hasn't been measured.

### Baseline configuration

There is one configuration, applied to every jurisdiction. Its new version is the minimum DiD
must deliver: **everything `aphl_baseline.json` promises today, plus the gaps filled.**
Expressed against the named-element catalog, it covers:

- any change to a clinical statement in any section (today's `//hl7:entry` rule), now
  including nested statements, statements in new sections, and status and code changes
- a section's own change, and a narrative-only section that is populated or expanded
- patient deceased, birth time and name, and encounter end time

`Configuration-Spec.md` moves to a version that names catalog elements instead of XPaths.
The XPath form remains readable until nothing uses it.

### Input

DiD compares refined and unrefined documents alike: it needs two documents of the same
`setId`, nothing more. A refined section compares equal across versions only when both the
sender's content _and_ the Refiner configuration are unchanged. The Refiner's footnotes are
non-clinical (layer 2), but its filter is not: it seeds `setId` on jurisdiction and scope
only (`dibbs-ecr-refiner` `services/ecr/augment.py:187-193`), so a configuration change
between v1 and v2 keeps the stream and changes what it retains. An entry the new configuration
newly retains then gets `did-add-detected` with no change from the sender.

That may be the right flag, since the entry is new to the PHA. Whether it should be is the
baseline question ("previous" vs "last delivered"), which is the Lambda's (Out of scope), not
this algorithm's. DiD reads `config_version` from both versions' footnotes
(`narrative/footnote.py:148`) and logs a mismatch, so these comparisons can be told apart.

An input may already carry DiD authors from an earlier pass (the multicode fixture does). They
are non-clinical, and the output keeps them, since augmentation authors accumulate across the
chain `[aug-v5-v2 §1.1]`. "One author per statement" is per pass, so an earlier pass's author
beside this pass's isn't gap 4. When a Refiner author is present, DiD logs it so a
refiner-driven difference can be told apart, but it doesn't use it in comparison.

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

The rewrite logs enough for the silent-evaluation queries to show its effect directly:

- **per finding:** the base template root (the one pairing used), `paired_by`, and kind;
  for step 4 pairs, the fields that differed
- **per unpaired original:** why (`ambiguous` or `no_counterpart`) and its base root
- **per document:** `setId`, `encounter_type`, the verdict, and the RR's reportable
  conditions by jurisdiction. The verdict is the document-level outcome (no change, no
  actionable change, or actionable), the deciding rule, and the version compared against.
  Today's telemetry records none of these, so the silent evaluation couldn't measure how
  often DiD would have held a document back

`encounter_type` is already captured on `DocumentTelemetry` and not logged
(`did_lambda/telemetry.py:34`, `:151-165`). With these fields, #147 becomes visible in
production, and failures can be grouped by condition. That answers whether particular
conditions need their own rules. `paired_by` also answers which cascade step does the work,
which context 2 can't (Pairing).

### Testing

- The gap-analysis documents become acceptance fixtures, each with its expected findings
  and authors: APHL expects 23, 6, 3 and 6 flags across the four scenarios, with function
  codes checked as well as counts. The stable-key count assumes id-only changes are flagged;
  DiD's expectation for that file is below.
- A synthetic pair whose body fails to pair under today's matcher (context 1) guards the F2
  placement fix. Its expected output is today's: exactly one `did-add-detected`, on the
  first section.
- Synthetic pairs with **regenerated entry `<id>`s**, since APHL's fixtures keep every id
  stable: a corrected code on a singleton (pairs at step 3, `paired_by: singleton`), the
  same with other unpaired statements of its template in scope (pairs at step 4 when only the
  code differs; added + removed when three fields differ), a corrected code whose
  `effectiveTime` also moved (step 4), and a result that gains the trigger-code `templateId`
  (pairs; one `populated` finding).
- The multicode scenario ships only `augmented_*` files, so its fixture starts from documents
  that already carry DiD authors. Layer 2 treats those as non-clinical, which the fixture
  also exercises.
- #147's three files (codeupdate, stablekeychanges, multicodeupdate) come back with one
  author per changed statement, and no DELETED + ADDED for a statement that existed. DiD's
  expected counts differ from APHL's for stable-key (3, not 6); the walkthrough is in the
  Appendix ("Fixture expectations").

The APHL fixtures are a starting point, not a model of production. [computed] The
stable-key fixture's five "panels" are one Adenovirus result pasted five times, each with
panel code `99449-1`, exactly one result and the same `effectiveTime`. A real `99449-1`
reports a couple of dozen pathogens. Ask APHL:

- how the fixtures were built (hand-edited, stitched from real messages, copy-pasted)
- which edits in each pair were deliberate test changes and which were incidental
- for real v1 → v2 pairs, as little edited as possible and from more than one vendor

Meanwhile DiD builds its own synthetic pairs, shaped like real messages, for what is expected
to change between versions:

- a panel that gains results across versions, preliminary → final
- result status P → F → C, on `4.419` and on the organizer's `4.418`
- a corrected result value, and a qualitative flip (Not detected → Detected)
- every `<id>` regenerated, section and entry
- vendor templates, and statements with no `templateId`
- a `<translation>` added by text-to-code between versions
- a new section, and a section going to or from `nullFlavor`
- a one-out-one-in replacement under a stable-id sender (step 3 guard)
- a Refiner fan-out pair (one per jurisdiction per condition)

Fixtures are synthetic: no production-derived documents without written APHL clearance.

### Consequences

- The body failing to pair (context 1) is removed by construction: sections never pair
  through a body key. Ids diffed as content (context 2) is removed wherever an `<id>`, nested
  `<id>` or identity field pairs a statement; elsewhere it is reduced to what steps 3-4 can't
  pair, which the pilot measures. Earlier augmentation diffed as content is removed by layer 2.
- Gaps 1-5 and #147 close, except for leftovers that step 4 can't pair. [inferred] If
  senders regenerate ids widely, a corrected code with a new id may be the common production
  form of #147. It then rests on steps 3 and 4, not on the cascade's first two.
- **Unknown unknowns.** Real senders will produce cases no fixture models. The Refiner found
  its hardest ones in production (Epic's proprietary and missing templateIds, #1504, #1522,
  #1763). So the rewrite runs silently against production before PHAs see its authors, as
  today's DiD did for the silent evaluation. The Measurement fields (`paired_by`, unpaired
  reason, differing fields, base root) are how those cases are found, and fixing each is
  curation or a threshold change, not redesign.
- From a sender that regenerates ids, a sole statement that is genuinely replaced (one
  diagnosis ruled out, another made) reads as one update with before and after, not an
  addition. Since removals aren't flagged, that carries more than today's bare addition, but
  a PHA rule keyed on "new = added" would miss it unless DiD policy treats a singleton with
  changed identity fields as an addition. From a stable-id sender it reads as added, because
  of the step 3 guard.
- Every finding says why it paired and what changed, with before and after values, which
  today's output cannot.
- `stable_key.py`'s ladder, `_prune_to_outermost` and change-type function codes are
  retired. The XPath configuration form is deprecated.
- `dibbs-ecr` grows the template model, and the Refiner can later use it for matching and
  reconstruction (Refiner ADR 0010, Option D).
- Layer 3 curation is ongoing work, and each template added makes findings more specific.

### Out of scope

- Removal flags (gap 6), pending APHL and the IG.
- Which version a new one is compared against. That is the Lambda's call; comparison takes
  two documents and doesn't care which baseline they came from.
- Where findings are delivered beyond the augmented document.
- Diffing the RR, which DiD doesn't do today either.
- Linking entries across sections, such as order → result. The `related` field reserves room
  for it.
- Reading narrative content (the narrative spike).

### Future-state problems (notes, not decisions)

**`setId` continuity.** `setId` is what tells DiD, and the PHA, that two documents are
versions of one stream, and DiD's verdict on whether a document is worth sending rests on it.
If it shifts between versions, continuity is gone: DiD finds no baseline and treats the
version as first, or the PHA receives what looks like an unrelated new document. This ADR
changes nothing about how DiD derives or writes `setId`, and should stay conservative here
until these are settled:

- **Where it breaks today.** The Lambda finds its baseline by the input `setId`
  (`did_lambda/lambda_function.py:179-183`). Upstream, the Refiner seeds its output `setId` on
  jurisdiction and scope (`dibbs-ecr-refiner` `services/ecr/augment.py:187-193`), so a scope
  change starts a new stream from DiD's point of view. DiD's own output `setId` seeds on the
  joined jurisdiction list, so it shifts when that list changes, and it reads `@root` only,
  so distinct sender streams that differ in `@extension` can collapse into one
  (`core/augment.py:101-125`).
- **Should DiD create its own output at all?** The IG gives DiD a new `id` / `setId` and a
  `relatedDocument` for its input `[aug-v5-v1 Table 1]`. The alternative is for DiD only to
  gate and annotate, passing `setId` through as received. One gives IG conformance and
  provenance; the other gives continuity by construction.
- **If DiD does derive one, how is continuity guaranteed?** The derivation would be a pure
  function of the stream's identity, never of per-version content such as the jurisdiction
  list; frozen as wire protocol once shipped, as each repo already declares for its own; tested
  so that every version of a stream maps to one output `setId`; and logged as both input and
  output `setId`, so a break is visible in telemetry.

## Open Questions

None within DiD: the decisions above are this ADR's answers. What depends on APHL is listed
under Questions to APHL, below, each with DiD's proposed answer, to be asked while the team
reviews.

## Questions to APHL

Each has DiD's proposed answer, so the work can proceed while they are open. A different
answer changes a rule, not the design.

1. **Id-only changes.** Should an otherwise unchanged entry ever be flagged when only its
   `<id>` changed (gap deck slide 25)? _Proposed:_ no. It is recorded as `identity_only` and
   gets no author, because senders that regenerate ids would otherwise make every document
   actionable (context 2). Under that rule the stable-key scenario expects 3 flags, not 6
   (Testing).
2. **Singleton pairing.** When an element can't be recognised, should the only one of its
   kind under the same parent still pair (slide 25)? _Proposed:_ yes, except where another
   statement in the same scope paired by `<id>`. There the sender evidently keeps ids
   stable, so a leftover with a new id is new (Pairing, step 3).
3. **Panel-level marking.** Do PHAs reading at panel level want the organizer marked when only
   a result inside it changed? _Proposed:_ no; the author goes on the result. An author on the
   organizer conducts to every result in it, so marking the panel would need a distinct,
   weaker function code (Placement).
4. **How the test documents were built.** Were the gap-analysis documents hand-edited,
   stitched from real messages, or copy-pasted? Which edits in each pair were deliberate test
   changes and which were incidental? The stable-key scenario's five panels are one result
   pasted five times (Testing).
5. **Real version pairs.** Can APHL supply or clear real v1 → v2 pairs, as little edited as
   possible and from more than one vendor? They would confirm or refute the production
   signatures (context points 1 and 2), and show whether section and entry ids are stable.
6. **The Trifolia export.** Can APHL or the IG authors share the Trifolia export the eICR
   Schematron was generated from? It carries the MAY constraints the Schematron omits, which
   DiD otherwise adds by hand (Template knowledge, layer 1).
7. **DiD's function codes.** The `did-*` codes, including `did-add-detected` and
   `did-update-detected`, are outside the bound _Data Augmentation Tool Operation_ value set
   `[aug-v5-v2 CONF:5573-43]`. That value set is DYNAMIC; DiD proposes adding them (Placement).
8. **Removals.** How should a statement removed between versions be represented, given that an
   author can only sit on an element in the newer document? Out of scope here, pending APHL and
   the IG (gap 6).

## Appendix

### Problems addressed

| problem today                                                            | addressed                               | how                                                                                        |
| ------------------------------------------------------------------------ | --------------------------------------- | ------------------------------------------------------------------------------------------ |
| the document body fails to pair (context 1)                              | yes                                     | sections pair on a shared `<id>`, then base template root, then LOINC                      |
| instance ids diffed as content (context 2)                               | yes                                     | the cascade; `identity_only` is never flagged                                              |
| earlier augmentation authors diffed as content                           | yes                                     | augmentation authors are non-clinical (layer 2)                                            |
| new sections' and nested statements' contents unflagged (gaps 1, 2)      | yes                                     | placement: added wrappers flag what's beneath them                                         |
| a section's own change unflagged (gap 3)                                 | yes                                     | a section's own change always flags                                                        |
| two authors on one statement (gap 4)                                     | yes                                     | one author per statement per pass                                                          |
| function code taken from a child's change type (gap 5)                   | yes                                     | function code from the statement that carries the author                                   |
| corrected code or an id gaining `@extension` reads as replacement (#147) | yes, except leftovers step 4 can't pair | step 1 (same `<id>`, or the panel's result's `<id>`), step 3 (singleton), step 4 (similar) |
| a watch-list UPDATED rule checks only the changed node                   | yes                                     | findings attach to the unit                                                                |
| one "any entry" rule flattens salience                                   | yes                                     | catalog of units and kinds                                                                 |
| no trigger-code awareness                                                | yes                                     | trigger-code templates in layer 3; gaining one is a finding                                |
| output carries no values or context                                      | yes                                     | before and after on every finding                                                          |
| telemetry never records the verdict                                      | yes                                     | Measurement                                                                                |
| header changes outside the four header rules get no author               | partly                                  | `patient` and `encounter` pseudo-sections; the rest stays non-actionable                   |
| rules see one version at a time                                          | partly                                  | kinds are cross-version; cross-entry links later                                           |
| removals unmarked (gap 6)                                                | no                                      | out of scope, pending APHL and the IG                                                      |
| the RR is never diffed                                                   | no                                      | out of scope                                                                               |
| the output `setId` can shift or collapse streams                         | no                                      | Future-state problems                                                                      |

### Why not the RIM's split

The HL7 Reference Information Model (RIM), CDA's underlying information model, gives each
clinical building block its semantic meaning. It divides an act's properties into _inert_
ones, about the record of the act, and _descriptive_ ones, about the act itself; `negationInd`
negates only the descriptive ones `[cda-book line 3726]`. Its inert list includes `moodCode`,
`id`, `statusCode` and `author` `[cda-book Table 12.4, lines 3736-3749]`. That answers "what
does negation apply to", not "is this change clinically meaningful": a result going from
`active` to `completed` is about the record in RIM terms, and still news to a PHA. So this ADR
doesn't use the RIM terms for its clinical / non-clinical split.

### Fixture expectations

**Stable-key changes.** [computed] Results 2-4 differ only in their ids: they pair (2 and 3
by `nested_id`, since each panel's result keeps its `<id>`; 4 under its unchanged organizer)
and get **no author** (`identity_only`). Results 1 (code) and 5 (`statusCode`) carry real
changes and get `did-update-detected`, and so does the Encounters section for its LOINC
change (46240-8 → 46240-7). DiD's expected count is 3, against APHL's 6, pending their answer
to slide 25 (Questions to APHL).

**Codes updated one at a time.** APHL's count of 3 stands, including the
`@displayName`-only correction.

### Suggested Implementation Tickets

In DiD unless marked `dibbs-ecr`. The acceptance fixtures come first, so every later ticket
is measured against them.

#### `test: gap-analysis and #147 acceptance fixtures`

Each gap document and #147 file, with its expected findings and authors. They fail today;
the count passing is the progress measure.

#### `fix: placement for gaps 1, 2, 4, 5 on the current matcher`

In `augment.py`, against the acceptance fixtures and the collapsed-body guard. It ships
before the rewrite.

#### `chore: adopt dibbs-ecr v0.1`

Covered by Refiner ADR 0017: drop the augmentation fork, take reportable conditions, raise
`requires-python`.

#### `feat(dibbs-ecr): template structure from Schematron`

The generator, its pinned source, the generated records and a regeneration test.

#### `feat(dibbs-ecr): generic attribute meaning and change kinds`

Layer 2 plus the generic kind vocabulary.

#### `feat(dibbs-ecr): template meaning for the baseline templates`

Layer 3 for the templates the fixtures exercise, starting with the Initial Case Report
Trigger Code Result Observation and its Laboratory Observation Result Status qualifier
(`4.419`), the other trigger-code templates, and identity fields for each statement template
the fixtures touch. Identity fields are per template, never one key per statement kind (B2).

#### `feat: section units and header pseudo-sections`

#### `feat: pairing cascade (steps 1-3) and field comparison`

#### `feat: findings model and the narrative-only section rule`

#### `feat: placement from findings`

#### `feat: baseline configuration v2 on the named-element catalog`

Also update `Configuration-Spec.md`.

#### `feat: telemetry for findings`

Base template root, `paired_by`, kind, step 4's differing fields, the unpaired reason,
`encounter_type`, the verdict, and reportable conditions.

#### `chore: retire the stable-key ladder and outermost pruning`

#### `feat: similarity pairing for leftovers (step 4)`

The anti-join over what steps 1-3 leave, within one scope and template:

- same template, same skeleton of nested templates, at most two meaningful fields different
- binary and explainable: "paired as a probable update: only `code` differed"
- ties refuse to pair; never across sections; off where the sender's ids are evidently stable
- no weights, no new dependency; the limit is revisited from pilot telemetry

#### `chore: silent production pilot`

Run the rewrite alongside today's DiD without writing authors, and compare with the
silent-evaluation queries: the `paired_by` distribution, the ambiguous rate per base root,
and the differing-fields counts at step 4. New edge cases become curation tickets.

#### `spike: narrative content`

What a narrative change means across Epic, Cerner and Meditech, and whether the eICR
stylesheet's rendering gives a stable view to compare.

### Links

- 0001 Adopt decision records
- Refiner ADR 0017 (`dibbs-ecr` shared package; Proposed), ADR 0010 (defers the
  template-aware model)
- APHL's DiD gap analysis deck (22 October 2026) and test files, linked from #147
- [CDCgov/dibbs-ecr-diff#147](https://github.com/CDCgov/dibbs-ecr-diff/issues/147)
