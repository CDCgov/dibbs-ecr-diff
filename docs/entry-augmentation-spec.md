# Difference in Docs: Entry and Section level augmentation spec

**Spec version:** 1.0

## Purpose

Difference in Docs (DiD) will be marking changes between versions of Electronic Case Reports (eCR) with a data augmentation element.
In order to maintain proper eCR CDA formatting and adhere to APHL Data Augmentation specifications, this document will define the shape of
this augmentation to guide implementation within DiD.

## Augmentation Element Description

The augmentation will take the form of an Author element. As Section and Entry level elements
in eCRs can contain any amount of authors, DiD Augmentation Author elements can be attached without breaking eCR validation
or displacing existing author data. An indicator of the nature of the change within the eCR will be contained within the author tag in the form of a code.
Clear augmentation markings will differentiate augmented data from existing data.

## DiD Augmented Author Element Example
```xml
<author>
   <!-- DATA AUGMENTATION: functionCode specifies type of change
        "added" which signifies that the containing template has been
        added since the previous version of the document -->
   <functionCode code="added" codeSystem="2.16.840.1.113883.10.20.15.2.7.1"
                 codeSystemName="eCRDataAugmentation" />
   <!-- DATA AUGMENTATION: <time of data augmentation operation> -->
   <time value="20260507103000-0500" />
   <assignedAuthor>
       <!-- DATA AUGMENTATION: set to nullFlavor 'NA' -->
       <id nullFlavor="NA" />
       <!-- DATA AUGMENTATION: set to nullFlavor 'NA' -->
       <addr nullFlavor="NA" />
       <!-- DATA AUGMENTATION: set to nullFlavor 'NA' -->
       <telecom nullFlavor="NA" />
       <!-- DATA AUGMENTATION: set to 'Data Augmentation Tool' -->
       <assignedAuthoringDevice>
           <manufacturerModelName displayName="Data Augmentation Tool" />
       </assignedAuthoringDevice>
   </assignedAuthor>
</author>
```
### Describing changes using the functionCode element
The most important augmentation information is the code attribute of the functionCode element, which will indicate the nature
of the change to the eCR, e.g. `added` or `updated`. So, a lab observation with an augmented author element containing an
"added" code will be present in the current eCR but not the previous comparison eCR.

List of DiD MVP functionCode values:
-added
-updated

### Why is the inner assignedAuthor element there if its just full of nullFlavors?
This is to maintain proper structure of an author element in a CDA eCR for validation. The assignedAuthor tag must contain
id, addr, and telecom elements. While we must include them we can leave them blank with a "NA" nullFlavor for "Not Applicable"

## Example Augmented Entry

This is an example augmented laboratory Observation added between two versions of an eCR

```xml
<component>
   <observation classCode="OBS" moodCode="EVN">
      <templateId root="2.16.840.1.113883.10.20.22.4.2" />
      <templateId extension="2015-08-01" root="2.16.840.1.113883.10.20.22.4.2" />
      <templateId extension="2016-12-01" root="2.16.840.1.113883.10.20.15.2.3.2" />
      <id root="9890e2c3-019a-4168-8403-a0a069994440" />
      <code code="94310-0" codeSystem="2.16.840.1.113883.6.1"
            codeSystemName="LOINC"
            displayName="SARS-like Coronavirus N gene [Presence] in Unspecified specimen by NAA with probe detection"
            sdtc:valueSet="2.16.840.1.114222.4.11.7508"
            sdtc:valueSetVersion="20200429" xsi:type="CD" />
      <statusCode code="completed" />
      <effectiveTime value="20250205" />
      <value code="260373001" codeSystem="2.16.840.1.113883.6.96"
             codeSystemName="SNOMED-CT" displayName="Detected (qualifier value)"
             xsi:type="CD" />
      <author>
         <!-- DATA AUGMENTATION: functionCode specifies type of change
              "added" which signifies that the containing element has been
              added since the previous version of the document -->
         <functionCode code="added" codeSystem="2.16.840.1.113883.10.20.15.2.7.1"
                       codeSystemName="eCRDataAugmentation" />
         <!-- DATA AUGMENTATION: <time of data augmentation operation> -->
         <time value="20260507103000-0500" />
         <assignedAuthor>
            <!-- DATA AUGMENTATION: set to nullFlavor 'NA' -->
            <id nullFlavor="NA" />
            <!-- DATA AUGMENTATION: set to nullFlavor 'NA' -->
            <addr nullFlavor="NA" />
            <!-- DATA AUGMENTATION: set to nullFlavor 'NA' -->
            <telecom nullFlavor="NA" />
            <!-- DATA AUGMENTATION: set to 'Data Augmentation Tool' -->
            <assignedAuthoringDevice>
               <manufacturerModelName displayName="Data Augmentation Tool" />
            </assignedAuthoringDevice>
         </assignedAuthor>
      </author>
   </observation>
</component>
```

## Open questions

1. **How do we signal deletions, if at all:** We can't flag an element that doesn't exist anymore. Do we even need to acknowledge deletions at all? Is a deletion an inherently non-actionable change?
2. **How do we flag changes in sections of the document that can't accept an author element?** RecordTarget, which contains patient information, is a notable example of this

## Post-MVP considerations

Currently out of scope for MVP.

- **Marking individual tag changes within an element:** For MVP it makes sense to simply mark an element as having changes. There's work to be done in how best to mark individual field level changes using this code system, for example if only the value tag inside an element has changes.
- **Top level list of all diffs:** We'd thought a header level list of changes might be useful but after recent deliberation have decided to shelf the idea for MVP