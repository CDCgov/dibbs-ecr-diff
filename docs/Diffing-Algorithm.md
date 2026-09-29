# Diffing Algorithm

## Summary

The diffing algorithm compares a before eICR with an after eICR and reports
elements as added, updated, or deleted. It matches and compares XML elements across eICRs
by their logical identity where possible while ignoring when sibling elements get reordered.

## Some known elements are ignored

Some non-clinical values change every time a new eICR version is created, and these values are ignored. These ignored values, which occur as direct children of the CDA `ClinicalDocument`, are the following:

* `id` — the document instance identifier
* `effectiveTime` — the document version timestamp
* `versionNumber` — the document version number
* `relatedDocument` with `typeCode="RPLC"` — replacement-document lineage

If an `id`, `effectiveTime`, or `versionNumber` exists in an element that's *not* a child of `ClinicalDocument`, then it is *not* ignored. For example, a changed `effectiveTime` inside an observation is reported as an update.

## Recursive matching and comparison

The algorithm operates by descending recursively down the two eICR XML trees in parallel while matching and comparing elements across the eICRs at each level. This recursion starts at the top element of the eICR, the root ClinicalDocument element. By traversing the same level of the XML tree on each side at the same time, the algorithm can try to determine the elements that have been either added, updated, or deleted at that level across the eICRs. These are the scenarios encountered when trying to match elements at the same level across eICRs:

* `(None, after)` — The element was added.
* `(before, None)` — The element was deleted.
* `(before, after)` — The same element exists in both documents. It may or may not have been updated.

The added and deleted scenarios are fairly straightforward, and further recursion into those elements' child elements stops once an added or deleted element is found. 

When both a before element and an after element are matched, then the algorithm checks for an update by comparing the elements' tags, filtered attributes, and normalized direct text. If any of those are different, then those two elements are marked as an update. Then, regardless of whether those matched elements have been updated or not, the algorithm computes an order-insensitive subtree "fingerprint" for the before element and the after element and compares the two subtree fingerprints. A subtree fingerprint consists of all of an element's descendant elements, and any sibling elements in the subtree fingerprint are sorted so as to ignore any ordering changes. If the subtree fingerprints are equivalent, then the elements in them are identical across eICRs and recursion does not enter into those subtrees.

If the order-insensitive subtree fingerprints are different, then a new round of recursion begins that attempts to match the first level of subtree child elements across eICRs. The child elements are grouped by XML tag with one group per tag, per eICR, and the algorithm attempts to match child elements in identical tag groups across eICRs. e.g. there could be a group of sibling elements with the "entry" tag in each eICR, and the algorithm would attempt to find matches between the elements in the "entry" tag group from the before eICR with those in the after eICR. This results in new sets of adds (`(None, after)`), potential updates (`(before, after)`) and deletes (`(before, None)`).

## Element matching

For each pair of sibling tag groups, one sibling tag group from the before eICR and one sibling tag group from the after eICR, matching proceeds through the following stages.

### 1. (Currently ignored) Narrative table cells are paired by column position

When both child groups consist entirely of `td` or `th` elements, cells are
paired by their column position. Remaining cells on either side are treated as
additions or deletions. This is a special case because a cell's position is
part of the meaning of a table row even when the cell has no useful CDA
identifier.

### 2. Ranked exact stable-key matching

The algorithm derives all available stable-key candidates for every unmatched sibling
element for each eICR. It then attempts to match candidates across the eICRs starting from the strongest ranked candidate down to the weakest until a one-to-one match across eICRs, if any, is found. The ranks from strongest to weakest are defined in [Stable-Key.md](Stable-Key.md). If a one-to-one match is found at a given rank across eICRs, then that match is considered sufficient to claim that it's the same element across eICRs. The technical name given for this type of algorithm is "multipass deterministic matching."

At each rank:

1. Candidate values are found, if they exist, for each of the elements in the before and after sibling groups.
2. A candidate is eligible only if it occurs exactly once among the before siblings and exactly once among the after siblings. Otherwise, the one-to-one requirement is violated.
3. The before and after candidate must have the same key type and value.
4. Elements that match one-to-one across eICRs are paired and removed before attempting to match any remaining sibling elements at the next (lower) candidate rank.

#### Example: direct ID attribute key with update

```xml
<!-- before -->
<observation ID="obs-123"><value code="old"/></observation>

<!-- after -->
<observation ID="obs-123"><value code="new"/></observation>
```

The direct `ID` attribute value is unique and unchanged, so the observations pair and an update is found recursively in the changed `<value>` child.

#### Example: direct-child `<id>` key with no update

```xml
<!-- before -->
<observation><id root="urn:example:observation" extension="42"/></observation>

<!-- after -->
<observation><id root="urn:example:observation" extension="42"/></observation>
```

The observation's direct-child `<id>` stable-key candidate is the same on both sides. In the above scenario, the observations are matched but there's no update.

#### Example: multiple reordered child `<id>`'s as a key set

```xml
<!-- before -->
<observation>
  <id root="urn:example:a"/>
  <id root="urn:example:b"/>
</observation>

<!-- after: same set, different order -->
<observation>
  <id root="urn:example:b"/>
  <id root="urn:example:a"/>
</observation>
```

The observation's collection of child `<id>` elements is sorted and deduplicated, so child reordering does not change the candidate key. A collection key is still subject to one-to-one uniqueness across eICRs.

#### Example: a lower-ranked candidate matches after an ambiguous higher-ranked candidate

```xml
<!-- before -->
<observation ID="shared"><id root="observation-a"/></observation>
<observation ID="shared"><id root="observation-b"/></observation>

<!-- after -->
<observation ID="shared"><id root="observation-a"/></observation>
<observation ID="shared"><id root="observation-b"/></observation>
```

The observation's direct `ID` attribute candidate is ambiguous since it appears on two sibling elements. As a result, the `ID` attribute candidate is rejected for matching and the algorithm tries to match using a lower-ranked candidate. In the above case, once the algorithm reaches the candidate rank for a key set of child `<id>` elements, the two observations can be paired by their respective `<id>` `root` values.

### 3. Stable-key subset matching

Subset matching is used when a collection-based stable key changes because a value was added to or removed from the collection. Subset matching is still restricted to unambiguous one-to-one matches: one before element cannot match multiple after elements, and multiple before elements cannot match one after element.

The subset matching methods run in this order:

#### 3a. Partial child `<id>` overlap

For collections of direct child `<id>`'s and nested clinical-statement `<id>`'s, one shared
`root`/`extension` value across the eICR collections is sufficient to match, provided the shared `<id>` identifies only one element on each side.

```text
before direct child <id>'s: {A, B}
after direct child <id>'s:  {A, C}
result: match, because A is a shared <id> identifier, and <id> elements are generally considered to be strong identifiers
```

The partial child `<id>` overlap method is useful when one child `<id>` element stays the same while others get added or deleted.

#### 3b. Complete nested-section `<id>` subset

For wrappers identified by descendant section `<id>`'s, every `<id>` in the smaller set
must be completely contained in the larger set. It does not matter if the smaller set is in the before eICR or the after eICR.

```text
before section <id>'s: {section-A, section-B}
after section <id>'s:  {section-A, section-B, section-C}
result: match, because the smaller set is completely contained in the larger
```

This supports matching when a section is added or removed. Partial overlap is not sufficient:

```text
before: {section-A, section-B}
after:  {section-A, section-C}
result: no subset match
```

#### 3c. Complete direct-clinical-statement `<id>` subset

For wrappers such as `entry`, `entryRelationship`, or suitable `component`elements, the direct clinical-statement child `<id>`'s only match if every `<id>` in the smaller set is completely contained in the larger set, similar to 3b above. This supports matching when clinical statements are added or removed.

#### 3d. Complete template `<id>` subset

Direct-child, nested-section, and nested-clinical-statement template `<id>` sets are different types of sets, but they're all matched using template `<id>` sets. A match is only valid if every template `<id>` in the smaller set is completely contained in the larger set, similar to 3b above. This supports matching when template `<id>`'s are added or removed.

Template `<id>`'s describe conformance or content type more than an individual instance, so this is the weakest subset fallback.

### 4. Bucket and discriminator fallback

***NOTE: all logic associated with (4) needs to be refined further***

Elements that remain unmatched are placed into buckets before a final
pairing attempt. The bucket key is selected in this order:

1. Narrative table key, for `table` elements;
2. Narrative row key, for `tr` elements;
3. The element's highest-ranked stable key, with direct-child template IDs
   treated as a broad template-ID bucket; or
4. The XML tag when no more useful key exists.

If a bucket exists on only one side, its elements become additions or deletions.
If a bucket has exactly one element on each side, those elements are paired.
Otherwise, the algorithm applies two late discriminators.

#### 4a. Prefer-updates soft pairing in template-ID buckets

Within broad direct-template-ID buckets, the algorithm tries to pair elements as
updates rather than classify them as an addition and deletion. Its soft context
uses, in order:

* statement-level instance IDs;
* direct template IDs plus statement effective time, enclosing organizer
  context, and statement code.

This is intentionally a late, soft pairing step. It is useful when several
elements share a template ID, but is not the same level of evidence as an exact stable-key match.

#### 4b. Secondary discriminator matching

Remaining elements in a bucket are grouped by the best available discriminator
from this sequence:

1. Narrative table key;
2. Narrative row key;
3. Statement ID root/extension values;
4. Statement code and code system;
5. Effective time, using point, interval, center, or period representations;
6. Weak direct attributes: `classCode`, `typeCode`, and `use`;
7. An order-insensitive recursive element fingerprint.

Elements sharing a discriminator are paired up to the smaller group size.
Unpaired elements become additions or deletions.

## Important matching concepts

### Matching and content comparison are separate

Matching determines which before and after elements represent the same logical
element. An unchanged key does not mean the element's content is unchanged. After a match is established, the diff collector compares tags, attributes, text, and descendants to determine whether that element has been updated.

### Element key uniqueness is not global

Element key uniqueness is evaluated within the sibling group currently being matched. The same key value could therefore theoretically appear in different parts of a document without being a globally unique identifier. Duplicate key values within one sibling group, however, are treated as ambiguous rather than paired arbitrarily across eICRs.

### Key type matters

Equal key values of different types are not interchangeable. For example, a
direct-child `templateId` set is not treated as equal to a nested-section
`templateId` set containing the same root values. This avoids pairing elements
based only on values that do not take into account the type that those values appear in.

### The comparison algorithm is decoupled from actionability

The comparison algorithm compares the entirety of the eICRs without concern for which adds, updates, and deletes are considered actionable. This decouples the eICR comparison from what's actionable to users as defined in rules configurations.