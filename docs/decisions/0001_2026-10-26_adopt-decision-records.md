# 1. Adopt decision records

Date: 2026-10-26

## Status

Proposed

## Context and Problem Statement

This repository has no decision record. `docs/` holds specifications —
`Diffing-Algorithm.md`, `Stable-Key.md`, `Configuration-Spec.md`,
`Storage-Architecture.md` — and each describes what the code does rather than
why that shape was chosen or what was rejected on the way. Decisions that are
load-bearing today exist only as code: the twelve-rank fallback ladder in
`packages/core/src/core/cda/stable_key.py:48-62`, the DynamoDB `setId` / `versionNumber`
key pair, the choice to carry watch and ignore rules as bundled XPath JSON
rather than as persisted configuration.

`dibbs-ecr-refiner` is the only repository in this portfolio that keeps a
decision record: sixteen records in `docs/decisions/`, authored with
`just rfc new "Title"`. The process has worked there and the tooling is small
enough to port, which this change does.

It carries one gap worth naming before we inherit it. **A record captures what
was proposed, and nothing in the process captures how the implementation then
diverged from it.** The only edit an implementing pull request makes to its
record is the status label:

- Record 0001 was introduced as `Proposed` in refiner PR #584 (2025-11-12) and
  implemented in PR #646 (2026-01-08). The implementing PR's entire change to
  the record was `-Status: Proposed` / `+Status: Accepted` — one line.
- Record 0002 is the same shape: the only content edit after introduction was
  `-Proposed` / `+Accepted`.
- Across all sixteen, every other post-introduction commit is incidental
  formatting — trailing-whitespace strips from refiner PRs #1091 and #1631.

Two workarounds in that history show the need is already felt, and that nothing
in the template tells an author where to put it:

- Record 0014 carries the drift in its status line as prose: `Superceded - need
to rework this to account for changes in data schema after code management
work. Left in its original form for posterity.`
- Record 0011 appends a `## Post-review refinements (expert IG review,
2026-06-25)` section, which the template does not define.

The status vocabulary has drifted alongside it. The template offers
`Proposed/Accepted/Superseded`; practice holds `Accepted` (ten), `Proposed`
(three), `Deprecated` (one), the free-text `Superceded - …` above, and record
0012, which has no `## Status` section at all. The refiner's
`docs/decisions/index.liquid` styles only `Accepted` and `Proposed`, so
everything else renders as an undifferentiated badge.

The consequence is that a reader cannot tell from an `Accepted` record whether
the shipped system still matches it. Dates compound this: record 0001 reads as a
decision dated 2025-10-31, and it was accepted on 2026-01-08 — the status flip
is undated, so the two-month gap between proposing and accepting is recoverable
only from `git log`.

## Decision Drivers

- **Authoring cost has to stay near zero.** The refiner's record exists because
  `just rfc new` makes starting one cheaper than not starting one.
- **The record has to stay trustworthy as the implementation moves.** A record
  that silently describes a superseded design is worse than no record, because
  it is read with confidence.
- **No new runtime dependency.** This repository is a pure uv/Python workspace
  with no Node toolchain; the refiner's generator is a Node script.
- **Whatever we choose must be answerable from the files themselves,** not from
  commit archaeology across two repositories.

## Considered Options

**1. Port the refiner's workflow unchanged.** Cheapest, and the mechanics are
proven over sixteen records and roughly a year. Inherits the gap above verbatim.

**2. Port it, and add an amendment section.** A record gains a dated
`## Amendments` section when the implementation departs from the decision. This
is what refiner record 0011 did by hand. Keeps one decision in one file, so the
reader has a single place to look; costs nothing when nothing drifted. The risk
is that the original text and its amendment disagree on the page and the reader
has to reconcile them.

**3. Port it, and supersede with a new record per material change.** The
original is frozen and its status becomes `Superseded by NNNN`. Clean history,
and each record is internally consistent. But it inflates the numbering for what
may be a small correction, and splits one decision across several files.

**4. Port it, and version the record.** A revised decision becomes `0001.1` or
gains a `## Revision` block carrying its own date and status, so the original
stays readable while the current state is unambiguous. This is the option
discussed when this change was proposed. It needs a convention the tooling does
not have yet — `just rfc new` derives the next number from the leading four
digits of existing filenames, so a `0001.1` would need the generator to grow a
notion of revising an existing record rather than creating the next one.

## Decision Outcome

Adopt the workflow. `just rfc new "Title"` writes
`docs/decisions/NNNN_YYYY-MM-DD_kebab-title.md` from
`docs/decisions/.template`, exposed as the `decisions` module with an `rfc`
alias, matching the refiner so the muscle memory transfers between
repositories. Two deliberate differences from the refiner: the generator is
stdlib Python rather than Node, since this repository has no Node toolchain, and
the next number is derived as `max(existing) + 1` rather than `count + 1`, so a
deleted or withdrawn record cannot hand its number to the next one.

**The drift-recording mechanism is deliberately left open.** Options 2, 3 and 4
each have a real cost and the choice should be made by the team reviewing this
record, not by the record proposing the process — so this stays `Proposed` until
that question is answered, and the answer belongs in this section.

Two smaller questions that fall out of the same gap and want an answer at the
same time:

- **Should the status flip carry its own date?** `Date:` is the authoring date.
  If `Accepted` carried a date, the proposed-to-accepted interval would be
  readable without `git log`.
- **Should the status values be enumerated?** The refiner's five-plus-absent set
  grew from a template that lists three. Naming the allowed values here is
  cheap now and awkward after the tenth record.
