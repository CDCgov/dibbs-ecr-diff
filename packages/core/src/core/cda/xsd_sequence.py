from lxml import etree

from core.xml_utils import localname

# TODO: eventually use XSD schema directly instead of hardcoded element sequences
SEQUENCE_ORDER_ACT_CHILDREN = [
    "realmCode",
    "typeId",
    "templateId",
    "id",
    "code",
    "text",
    "statusCode",
    "effectiveTime",
    "priorityCode",
    "languageCode",
    "subject",
    "specimen",
    "performer",
    "author",
    "informant",
    "participant",
    "entryRelationship",
    "reference",
    "precondition",
    "precondition2",
    "inFulfillmentOf1",
]

SEQUENCE_ORDER_ENCOUNTER_CHILDREN = [
    "realmCode",
    "typeId",
    "templateId",
    "id",
    "code",
    "text",
    "statusCode",
    "effectiveTime",
    "dischargeDispositionCode",
    "priorityCode",
    "subject",
    "specimen",
    "performer",
    "author",
    "informantparticipant",
    "entryRelationship",
    "reference",
    "precondition",
    "precondition2",
    "inFulfillmentOf1",
]

SEQUENCE_ORDER_OBSERVATION_CHILDREN = [
    "realmCode",
    "typeId",
    "templateId",
    "id",
    "category",
    "code",
    "derivationExpr",
    "text",
    "statusCode",
    "effectiveTime",
    "priorityCode",
    "repeatNumber",
    "languageCode",
    "interpretationCode",
    "methodCode",
    "targetSiteCode",
    "subject",
    "specimen",
    "performer",
    "author",
    "informantparticipant",
    "entryRelationship",
    "reference",
    "precondition",
    "precondition2referenceRange",
    "inFulfillmentOf1",
]

SEQUENCE_ORDER_OBSERVATION_MEDIA_CHILDREN = [
    "realmCode",
    "typeId",
    "templateId",
    "id",
    "languageCode",
    "value",
    "subject",
    "specimen",
    "performer",
    "author",
    "informantparticipant",
    "entryRelationship",
    "reference",
    "precondition",
    "precondition2",
]

SEQUENCE_ORDER_ORGANZIER_CHILDREN = [
    "realmCode",
    "typeId",
    "templateId",
    "id",
    "category",
    "code",
    "text",
    "statusCode",
    "effectiveTime",
    "subject",
    "specimen",
    "performer",
    "author",
    "informantparticipant",
    "reference",
    "precondition",
    "precondition2",
    "component",
]

SEQUENCE_ORDER_PROCEDURE_CHILDREN = [
    "realmCode",
    "typeId",
    "templateId",
    "id",
    "category",
    "code",
    "text",
    "statusCode",
    "effectiveTime",
    "priorityCode",
    "languageCode",
    "methodCode",
    "approachSiteCode",
    "targetSiteCode",
    "subject",
    "specimen",
    "performer",
    "author",
    "informant",
    "participant",
    "entryRelationship",
    "reference",
    "precondition",
    "precondition2inFulfillmentOf1",
]

SEQUENCE_ORDER_REGION_OF_INTEREST_CHILDREN = [
    "realmCode",
    "typeId",
    "templateId",
    "id",
    "code",
    "value",
    "subject",
    "specimen",
    "performer",
    "author",
    "informant",
    "participant",
    "entryRelationship",
    "reference",
    "precondition",
    "precondition2",
]

SEQUENCE_ORDER_SUBSTANCE_ADMINISTRATION_CHILDREN = [
    # starting from consumable which is always required
    "realmCode",
    "typeId",
    "templateId",
    "id",
    "code",
    "text",
    "statusCode",
    "effectiveTime",
    "priorityCode",
    "repeatNumber",
    "routeCode",
    "approachSiteCode",
    "doseQuantity",
    "rateQuantity",
    "maxDoseQuantity",
    "administrationUnitCode",
    "consumable",
    "subject",
    "specimen",
    "performer",
    "author",
    "informant",
    "participant",
    "entryRelationship",
    "reference",
    "precondition",
    "inFulfillmentOf1",
]

SEQUENCE_ORDER_SUPPLY_CHILDREN = [
    "realmCode",
    "typeId",
    "templateId",
    "id",
    "code",
    "text",
    "statusCode",
    "effectiveTime",
    "priorityCode",
    "repeatNumber",
    "independentInd",
    "quantity",
    "expectedUseTime",
    "product",
    "subject",
    "specimen",
    "performer",
    "author",
]

CDA_CLINICAL_STATEMENT_LOCALNAME_SEQUENCES = {
    "act": SEQUENCE_ORDER_ACT_CHILDREN,
    "encounter": SEQUENCE_ORDER_ENCOUNTER_CHILDREN,
    "observation": SEQUENCE_ORDER_OBSERVATION_CHILDREN,
    "observationMedia": SEQUENCE_ORDER_OBSERVATION_MEDIA_CHILDREN,
    "organizer": SEQUENCE_ORDER_ORGANZIER_CHILDREN,
    "procedure": SEQUENCE_ORDER_PROCEDURE_CHILDREN,
    "regionOfInterest": SEQUENCE_ORDER_REGION_OF_INTEREST_CHILDREN,
    "substanceAdministration": SEQUENCE_ORDER_SUBSTANCE_ADMINISTRATION_CHILDREN,
    "supply": SEQUENCE_ORDER_SUPPLY_CHILDREN,
}


def insert_sequenced_child_of_clinical_statement_parent(
    parent: etree._Element, new_child: etree._Element
) -> None:
    """Inserts child element into the correct XSD sequence position based on parent's existing children elements.

    Raises ValueError if parent does not have a known sequence order.
    """
    # In the future we could pull in the XSD to programmatically insert author at the correct sequence location.
    sequence_order = CDA_CLINICAL_STATEMENT_LOCALNAME_SEQUENCES.get(localname(parent))

    if sequence_order is None:
        raise ValueError(f"'{parent.tag}' does not have a known sequence order")

    _insert_in_sequence_order(parent, new_child, sequence_order)


def _insert_in_sequence_order(
    parent: etree._Element, new_child: etree._Element, sequence_order: list[str]
) -> None:
    """Inserts new child on parent according to the sequence order.

    Sequence order uses localnames for matching.

    Raises ValueError if the sequence order does not contain the new child localname.
    """
    sequence_rank_by_localname = {name: i for i, name in enumerate(sequence_order)}

    new_child_name = localname(new_child)
    if new_child_name not in sequence_rank_by_localname:
        raise ValueError(
            f"'{new_child_name}' is not a permitted child according to sequence order of parent '{parent.tag}'"
        )

    new_child_rank = sequence_rank_by_localname[new_child_name]

    insert_at_index = len(parent)  # append to end by default

    # Some elements in the sequence order might not exist on the parent
    # if they are optional. Therefore we need to insert the new child
    # in the order relative to the children that do exist.
    for i, child in enumerate(parent):
        if not isinstance(child.tag, str):
            continue  # skip comments

        child_rank = sequence_rank_by_localname.get(localname(child))
        if child_rank is None:
            continue

        if child_rank > new_child_rank:
            insert_at_index = i
            break

    parent.insert(insert_at_index, new_child)
