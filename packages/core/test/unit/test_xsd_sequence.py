import pytest
from core.cda.clinical_statement import CDA_CLINICAL_STATEMENT_LOCAL_NAMES
from core.cda.xsd_sequence import (
    CDA_CLINICAL_STATEMENT_LOCALNAME_SEQUENCES,
    insert_sequenced_child_of_clinical_statement_parent,
)
from core.constants import HL7_NS
from core.xml_utils import hl7_clark_tag, localname
from helpers import elem
from lxml import etree


def _ordered_children_localname(parent: etree._Element) -> list[str]:
    return [localname(c) for c in parent if isinstance(c.tag, str)]


def _hl7_parent_with(parent_name: str, *child_names: str) -> etree._Element:
    """An HL7 parent element pre-populated (in order) with child localnames."""
    parent = etree.Element(hl7_clark_tag(parent_name))
    for name in child_names:
        etree.SubElement(parent, hl7_clark_tag(name))
    return parent


def test_sequence_dictionary_has_expected_clinical_statement_keys():
    assert (
        set(CDA_CLINICAL_STATEMENT_LOCALNAME_SEQUENCES.keys())
        == CDA_CLINICAL_STATEMENT_LOCAL_NAMES
    )


@pytest.mark.parametrize(
    "localname_key", list(CDA_CLINICAL_STATEMENT_LOCALNAME_SEQUENCES)
)
def test_every_sequence_permits_author(localname_key):
    assert "author" in CDA_CLINICAL_STATEMENT_LOCALNAME_SEQUENCES[localname_key]


def test_insert_raises_when_parent_has_no_known_sequence():
    parent = etree.Element(hl7_clark_tag("section"))
    child = etree.Element(hl7_clark_tag("author"))
    with pytest.raises(ValueError, match="does not have a known sequence order"):
        insert_sequenced_child_of_clinical_statement_parent(parent, child)


def test_insert_raises_when_child_not_permitted_by_parent_sequence():
    parent = etree.Element(hl7_clark_tag("act"))
    child = etree.Element(hl7_clark_tag("notARealElement"))
    with pytest.raises(ValueError, match="not a permitted child"):
        insert_sequenced_child_of_clinical_statement_parent(parent, child)


@pytest.mark.parametrize(
    "parent_localname", list(CDA_CLINICAL_STATEMENT_LOCALNAME_SEQUENCES)
)
def test_insert_adds_author_for_every_known_parent(parent_localname):
    parent = etree.Element(hl7_clark_tag(parent_localname))
    child = etree.Element(hl7_clark_tag("author"))
    insert_sequenced_child_of_clinical_statement_parent(parent, child)
    assert child in list(parent)


def test_insert_places_lower_ranked_child_before_existing_children():
    """
    templateId precedes id in the act sequence, so inserting it in
    front of an existing id and code puts templateId first.
    """
    parent = _hl7_parent_with("act", "id", "code")
    child = etree.Element(hl7_clark_tag("templateId"))
    insert_sequenced_child_of_clinical_statement_parent(parent, child)
    assert parent.index(child) == 0
    assert _ordered_children_localname(parent) == ["templateId", "id", "code"]


def test_insert_places_child_in_the_middle_respecting_rank():
    """
    code sits between id and statusCode, so it lands between them even
    though the text element is missing.
    """
    parent = _hl7_parent_with("act", "id", "statusCode")
    child = etree.Element(hl7_clark_tag("code"))
    insert_sequenced_child_of_clinical_statement_parent(parent, child)
    assert _ordered_children_localname(parent) == ["id", "code", "statusCode"]


def test_insert_appends_higher_ranked_child_at_end():
    """Author outranks the header elements, so it is appended last."""
    parent = _hl7_parent_with("act", "templateId", "id", "code")
    child = etree.Element(hl7_clark_tag("author"))
    insert_sequenced_child_of_clinical_statement_parent(parent, child)
    assert parent.index(child) == len(parent) - 1
    assert _ordered_children_localname(parent) == ["templateId", "id", "code", "author"]


def test_insert_only_grows_child_count_by_one():
    parent = _hl7_parent_with("act", "id", "code", "statusCode")
    child = etree.Element(hl7_clark_tag("author"))
    before = len(parent)
    insert_sequenced_child_of_clinical_statement_parent(parent, child)
    assert len(parent) == before + 1


def test_insert_appends_after_equal_ranked_child():
    parent = _hl7_parent_with("act", "templateId", "id", "author")
    assert localname(parent[2]) == "author"

    child = elem(f"<author xmlns='{HL7_NS}'/>")
    insert_sequenced_child_of_clinical_statement_parent(parent, child)
    assert parent.index(child) == 3
    assert localname(parent[2]) == "author"
    assert localname(parent[3]) == "author"


def test_sequence_order_skips_comment_nodes():
    parent = etree.Element(hl7_clark_tag("act"))
    parent.append(etree.Comment("a leading comment"))
    etree.SubElement(parent, hl7_clark_tag("id"))
    child = etree.Element(hl7_clark_tag("text"))
    insert_sequenced_child_of_clinical_statement_parent(parent, child)
    # comment stays put; element order is correct
    assert _ordered_children_localname(parent) == ["id", "text"]
