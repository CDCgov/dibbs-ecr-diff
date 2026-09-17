# Stable Key

## Purpose 

The stable key serves to identify the same XML element across different
versions of an eICR regardless of its position among sibling elements.
Stable keys are derived from the element and its CDA context; they are not
generated IDs, and they are not persisted anywhere after being used to compare eICRs.

A stable key is chosen from candidate keys that are ordered from 
strongest to weakest. The candidate key that is chosen as the stable key depends on whether that candidate key has a matching candidate key in the other eICR. If there is a non-None/non-null one-to-one match found across eICRs for that candidate key, then that candidate key is used as the stable key for the matched elements. The one-to-one match is evaluated within the relevant sibling group, not against every element in the entire other document.

## Stable key candidate hierarchy

The stable key candidate hierarchy reflects how uniquely a candidate key is expected to describe an element. For example, an ID attribute on the element itself is more specific than an identifier derived from its child elements. It is not expected that every key candidate will exist for a given element i.e. some key candidates may be None, in which case those candidates are ignored. The stable key candidates that the application looks for are listed below, ranked from strongest (1) to weakest (12):


| Rank | Candidate | Source and value |
| ---: | --- | --- |
| 1 | Direct ID attribute | `ID` or `id` on the element itself. |
| 2 | Direct root/extension | `root` and optional `extension` on an ID-like CDA element (`id`, `templateId`, or `setId`). |
| 3 | Direct code | `code` and `codeSystem` on the element itself when it is a CDA `code` element. |
| 4 | Direct child IDs | The complete set of `root`/`extension` values from the element's direct `id` children. |
| 5 | Clinical-statement ID attribute | `ID` or `id` on a clinical statement, such as an `observation` or `act`, either directly or through a suitable wrapper. |
| 6 | Clinical-statement IDs | The complete set of `root`/`extension` values from `id` children of a clinical statement, either directly or through a suitable wrapper. |
| 7 | Direct child codes | The complete set of `code`/`codeSystem` values from direct child `code` elements. |
| 8 | Clinical-statement codes | The complete set of `code`/`codeSystem` values from a nested clinical statement. |
| 9 | Section IDs | The complete set of `root`/`extension` values from descendant section `id` elements. |
| 10 | Direct child template IDs | The complete set of `root`/`extension` values from direct child `templateId` elements. |
| 11 | Section template IDs | The complete set of `root`/`extension` values from descendant section `templateId` elements. |
| 12 | Clinical-statement template IDs | The complete set of `root`/`extension` values from `templateId` children of a clinical statement, either directly or through a suitable wrapper. |

## Candidate key construction rules

* `root` is required for root/extension-based keys. A missing `extension` is
  treated as an empty value.
* A code key requires both `code` and `codeSystem`. A code without a code
  system is not used.
* Keys that are constructed with a collection of values have their values
  sorted and deduplicated, so that ordering and duplicate values are ignored.
* The key location is part of the key type. For example, in the unlikely scenario that an ID on a representedOrganization matches an ID on a nested clinical statement, those should not be considered a match since those values exist in different contexts.


## Limitations

Missing identifiers, reused identifiers, duplicated keys among
siblings, broad template IDs, or changes to the identifying fields can leave
an element without a sufficiently specific key. In that case, there is fallback matching logic that gets attempted after stable key matching fails.

Keys are not guaranteed to be globally unique across the document; uniqueness is evaluated within the context of sibling elements.

A candidate key can be present but still too broad to identify one element, especially a shared template ID or common code.

The matching and diffing procedures that consume these keys are specified
separately.
