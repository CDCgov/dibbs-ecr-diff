# Difference in Docs: HTML Generation of Augmented eCRs Spike
## Purpose
The purpose of this spike is to determine how an augmented eCR interacts with the code used to generate browser-viewable
HTML files for Electronic Case Reports

## How to generate an HTML file from an eCR


## DiD Augmented Author Element Example

### Describing changes using the functionCode element
The most important augmentation information is the code attribute of the functionCode element, which will indicate the nature
of the change to the eCR, e.g. "added" or "changed". So, a lab observation with an augmented author element containing an
"added" code will be present in the current eCR but not the previous comparison eCR.

### Why is the inner assignedAuthor element there if its just full of nullFlavors?
This is to maintain proper structure of an author element in a CDA eCR for validation. The assignedAuthor tag must contain
id, addr, and telecom elements. While we must include them we can leave them blank with a "NA" nullFlavor for "Not Applicable"

## Example Augmented Entry

This is an example augmented laboratory Observation added between two versions of an eCR

## Open questions

1. **How do we signal deletions, if at all:** We can't flag an element that doesn't exist anymore. Do we even need to acknowledge deletions at all? Is a deletion an inherently non-actionable change?

## Post-MVP considerations

Currently out of scope for MVP.

- **Marking individual tag changes within an element:** For MVP it makes sense to simply mark an element as having changes. There's work to be done in how best to mark individual field level changes using this code system, for example if only the value tag inside an element has changes.
- **Top level list of all diffs:** We'd thought a header level list of changes might be useful but after recent deliberation have decided to shelf the idea for MVP