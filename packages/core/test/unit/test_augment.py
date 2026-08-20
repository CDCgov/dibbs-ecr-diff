import datetime
import uuid

import pytest
from core.augment import (
    DIFF_DETERMINISTIC_NS,
    AugmentationRun,
    _contains_diff_author_direct_child,
    _create_diff_author_element,
    _derive_augmented_eicr_id,
    _derive_augmented_eicr_setid,
    _derive_augmented_rr_id,
    _derive_augmented_rr_setid,
    _find_best_author_allowed_element,
    augment_eicr_in_place,
    augment_rr_in_place,
    create_augmentation_run,
    FUNCTION_CODE_ADD_DETECTED,
    FUNCTION_CODE_UPDATE_DETECTED,
)
from core.cda.clinical_statement import CDA_CLINICAL_STATEMENT_TAGS
from core.constants import HL7_NS, NAMESPACES
from core.models import Change, ChangeType, DiffOutput, Document
from core.xml_utils import hl7_clark_tag
from helpers import elem
from lxml import etree

# NOTE:
# HELPERS
# =============================================================================

# fixed values used across tests so assertions don't depend on UUIDs or
# wall-clock time. Tests that need to verify ID stamping derive the
# expected augmented values via the _derive_* helpers using these inputs.
_TEST_JURISDICTION_ID = "SDDH"
_TEST_AUGMENTATION_TIME = "20260325120000+0000"


def _make_run(**overrides) -> AugmentationRun:
    """
    Creates a deterministic AugmentationRun for testing.

    AugmentationRun carries only the values shared across every
    augmentation in a session: the timestamp, the inherited
    versionNumber, and the source eICR's setId root (used as the seed
    for RR-side setId derivations). Per-call discriminators —
    jurisdiction_id and tool identity travel as direct arguments to
    augment_eicr_in_place / augment_rr_in_place, not on the run.

    Augmented identifiers are NOT on the run; they are derived inside
    augment_eicr_in_place / augment_rr_in_place from (run, jurisdiction, captured
    input identity). Tests that need to assert against specific
    augmented values compute them via _derive_* using the fixture's
    original identifiers.
    """

    defaults = {
        "augmentation_time": _TEST_AUGMENTATION_TIME,
        "version_number": "1",
        "original_eicr_setid_root": "orig-eicr-setid-from-run",
    }
    defaults.update(overrides)
    return AugmentationRun(**defaults)


def _make_empty_diff_output() -> DiffOutput:
    return DiffOutput(
        generatedAt=datetime.datetime.strptime(
            _TEST_AUGMENTATION_TIME, "%Y%m%d%H%M%S%z"
        ),
        configurationId=uuid.UUID("7f32fea9-5a2a-47de-80e5-808ee9be919b"),
        configurationVersion="1",
        configurationDisplayName="test",
        setId="abc",
        currentDocument=Document(documentId="123", versionNumber="2"),
        previousDocument=Document(documentId="345", versionNumber="1"),
        hasDetectedChanges=False,
        hasActionableChanges=False,
        changes=[],
    )


# NOTE:
# EICR AUGMENTATION TESTS
# =============================================================================


def test_augment_eicr_in_place_adds_template_id(eicr_1_root_v3_1_1: etree.Element):
    """
    The eICR augmentation templateId should be added before the document id.
    """

    run = _make_run()
    augment_eicr_in_place(
        eicr_1_root_v3_1_1,
        run,
        jurisdiction_id=_TEST_JURISDICTION_ID,
        diff_output=_make_empty_diff_output(),
    )

    template_ids = eicr_1_root_v3_1_1.xpath(
        "hl7:templateId[@root='2.16.840.1.113883.10.20.15.2.1.3']",
        namespaces=NAMESPACES,
    )
    assert len(template_ids) == 1
    assert template_ids[0].get("extension") == "2025-11-01"


def test_augment_eicr_in_place_replaces_document_id(eicr_1_root_v3_1_1: etree.Element):
    """
    The document id should be replaced with the derived augmented eICR
    id (seeded from the input eICR's id and the jurisdiction),
    with assigningAuthorityName set to the tool code.
    """

    original_eicr_id = eicr_1_root_v3_1_1.find("hl7:id", NAMESPACES)
    assert original_eicr_id is not None
    original_eicr_id_root = original_eicr_id.get("root")
    assert original_eicr_id_root is not None

    expected_id = _derive_augmented_eicr_id(
        original_eicr_id_root,
        _TEST_JURISDICTION_ID,
    )

    run = _make_run()
    augment_eicr_in_place(
        eicr_1_root_v3_1_1,
        run,
        jurisdiction_id=_TEST_JURISDICTION_ID,
        diff_output=_make_empty_diff_output(),
    )

    doc_id = eicr_1_root_v3_1_1.find("hl7:id", NAMESPACES)
    assert doc_id is not None
    assert doc_id.get("root") == expected_id
    assert doc_id.get("assigningAuthorityName") == "ecr-difference-in-docs"


def test_augment_eicr_in_place_replaces_set_id_and_version(
    eicr_1_root_v3_1_1: etree.Element,
):
    """
    setId should get the derived augmented eICR setId (seeded from the
    run's original_eicr_setid_root, which the pipeline supplies from
    the source eICR) and versionNumber should inherit from the run.
    """

    # the run's original_eicr_setid_root is what the pipeline would
    # have captured off the source eICR — point the test run at the
    # fixture's setId so the derivation reflects reality
    original_eicr_setid = eicr_1_root_v3_1_1.find("hl7:setId", NAMESPACES)
    assert original_eicr_setid is not None
    original_eicr_setid_root = original_eicr_setid.get("root")
    assert original_eicr_setid_root is not None

    expected_setid = _derive_augmented_eicr_setid(
        original_eicr_setid_root,
        _TEST_JURISDICTION_ID,
    )

    run = _make_run(
        version_number="3",
        original_eicr_setid_root=original_eicr_setid_root,
    )
    augment_eicr_in_place(
        eicr_1_root_v3_1_1,
        run,
        jurisdiction_id=_TEST_JURISDICTION_ID,
        diff_output=_make_empty_diff_output(),
    )

    set_id = eicr_1_root_v3_1_1.find("hl7:setId", NAMESPACES)
    assert set_id is not None
    assert set_id.get("root") == expected_setid

    version = eicr_1_root_v3_1_1.find("hl7:versionNumber", NAMESPACES)
    assert version is not None
    assert version.get("value") == "3"


def test_augment_eicr_in_place_adds_author(eicr_1_root_v3_1_1: etree.Element):
    """
    A new author should be added with the v4 shape:
      - NO functionCode (removed per Vol 1 change log 2026-03-10)
      - softwareName carries coded attributes from the Data
        Augmentation Tool value set
      - id, addr, telecom each have nullFlavor="NA"
    """

    run = _make_run()

    # count existing authors before augmentation
    authors_before = len(eicr_1_root_v3_1_1.findall("hl7:author", NAMESPACES))

    augment_eicr_in_place(
        eicr_1_root_v3_1_1,
        run,
        jurisdiction_id=_TEST_JURISDICTION_ID,
        diff_output=_make_empty_diff_output(),
    )

    authors_after = eicr_1_root_v3_1_1.findall("hl7:author", NAMESPACES)
    assert len(authors_after) == authors_before + 1

    # the new author should be the last one
    new_author = authors_after[-1]

    # v4: no functionCode at the header level
    assert new_author.find("hl7:functionCode", NAMESPACES) is None

    # softwareName carries coded attributes
    software_name = new_author.find(
        ".//hl7:assignedAuthoringDevice/hl7:softwareName", NAMESPACES
    )
    assert software_name is not None
    assert software_name.get("code") == "ecr-difference-in-docs"
    assert software_name.get("codeSystem") == "2.16.840.1.113883.10.20.15.2.7.1"
    assert software_name.get("codeSystemName") == "eCRDataAugmentation"
    assert software_name.get("displayName") == "Difference in Docs"

    # nullFlavor elements
    assigned_author = new_author.find("hl7:assignedAuthor", NAMESPACES)
    assert assigned_author is not None

    aa_id = assigned_author.find("hl7:id", NAMESPACES)
    assert aa_id is not None
    assert aa_id.get("nullFlavor") == "NA"

    aa_addr = assigned_author.find("hl7:addr", NAMESPACES)
    assert aa_addr is not None
    assert aa_addr.get("nullFlavor") == "NA"

    aa_telecom = assigned_author.find("hl7:telecom", NAMESPACES)
    assert aa_telecom is not None
    assert aa_telecom.get("nullFlavor") == "NA"


def test_augment_eicr_in_place_adds_related_document(eicr_1_root_v3_1_1: etree.Element):
    """
    For an original-input eICR, exactly one relatedDocument sibling
    should be added with typeCode XFRM. Its parentDocument should
    contain the original document's id, setId, and versionNumber, with
    assigningAuthorityName="original-document" on both id and setId.
    """

    # capture the original identity before augmentation
    original_id = eicr_1_root_v3_1_1.find("hl7:id", NAMESPACES)
    assert original_id is not None
    original_setid = eicr_1_root_v3_1_1.find("hl7:setId", NAMESPACES)
    assert original_setid is not None
    original_version = eicr_1_root_v3_1_1.find("hl7:versionNumber", NAMESPACES)
    assert original_version is not None

    # capture the relatedDocument count before augmentation so we can
    # assert relative growth
    original_related_docs = eicr_1_root_v3_1_1.findall(
        "hl7:relatedDocument[@typeCode='XFRM']", NAMESPACES
    )
    starting_related_doc_len = len(original_related_docs)

    run = _make_run()
    augment_eicr_in_place(
        eicr_1_root_v3_1_1,
        run,
        jurisdiction_id=_TEST_JURISDICTION_ID,
        diff_output=_make_empty_diff_output(),
    )

    related_docs = eicr_1_root_v3_1_1.findall(
        "hl7:relatedDocument[@typeCode='XFRM']", NAMESPACES
    )
    assert len(related_docs) == starting_related_doc_len + 1

    parent_doc = related_docs[0].find("hl7:parentDocument", NAMESPACES)
    assert parent_doc is not None

    parent_id = parent_doc.find("hl7:id", NAMESPACES)
    assert parent_id is not None
    assert parent_id.get("root") == original_id.get("root")
    assert parent_id.get("assigningAuthorityName") == "original-document"

    parent_setid = parent_doc.find("hl7:setId", NAMESPACES)
    assert parent_setid is not None
    assert parent_setid.get("root") == original_setid.get("root")
    assert parent_setid.get("assigningAuthorityName") == "original-document"

    parent_version = parent_doc.find("hl7:versionNumber", NAMESPACES)
    assert parent_version is not None
    assert parent_version.get("value") == original_version.get("value")


def test_augment_eicr_in_place_replaces_effective_time(
    eicr_1_root_v3_1_1: etree.Element,
):
    """
    effectiveTime should be replaced with the augmentation timestamp.
    """

    run = _make_run()
    augment_eicr_in_place(
        eicr_1_root_v3_1_1,
        run,
        jurisdiction_id=_TEST_JURISDICTION_ID,
        diff_output=_make_empty_diff_output(),
    )

    eff_time = eicr_1_root_v3_1_1.find("hl7:effectiveTime", NAMESPACES)
    assert eff_time is not None
    assert eff_time.get("value") == _TEST_AUGMENTATION_TIME


# NOTE:
# RR AUGMENTATION TESTS
# =============================================================================


def test_augment_rr_in_place_adds_rr_augmentation_template_id(
    rr_1_root_v1_1: etree.Element,
):
    """
    Under v4, the RR gets its own augmentation header template
    (Vol 1 §2, Vol 2 §1.2), distinct from the eICR's. The RR
    augmentation templateId is 2.16.840.1.113883.10.20.15.2.1.4 with
    extension 2026-04-01.
    """

    run = _make_run()
    augment_rr_in_place(
        rr_1_root_v1_1,
        run,
        jurisdiction_id=_TEST_JURISDICTION_ID,
    )

    rr_aug_template = rr_1_root_v1_1.xpath(
        "hl7:templateId[@root='2.16.840.1.113883.10.20.15.2.1.4']",
        namespaces=NAMESPACES,
    )

    assert len(rr_aug_template) == 1
    assert rr_aug_template[0].get("extension") == "2026-04-01"

    # the eICR augmentation templateId should NOT appear on the RR —
    # they're distinct templates with distinct CONF numbers
    eicr_aug_template = rr_1_root_v1_1.xpath(
        "hl7:templateId[@root='2.16.840.1.113883.10.20.15.2.1.3']",
        namespaces=NAMESPACES,
    )
    assert len(eicr_aug_template) == 0


def test_augment_rr_in_place_replaces_set_id_and_version_unconditionally(
    rr_1_root_v1_1: etree.Element,
):
    """
    Under v4 RR augmentation header (CONF:5573-77/78), setId and
    versionNumber are 1..1 SHALL on the augmented RR — they are added
    even if the input RR didn't have them.

    The augmented RR's setId is derived from the run's
    original_eicr_setid_root (the eICR-side seed; see pair
    recoverability), and the jurisdiction. versionNumber
    inherits from the eICR via run.version_number.
    """

    original_eicr_setid_root = "orig-set-2222"
    expected_setid = _derive_augmented_rr_setid(
        original_eicr_setid_root,
        _TEST_JURISDICTION_ID,
    )

    run = _make_run(
        version_number="3",
        original_eicr_setid_root=original_eicr_setid_root,
    )
    augment_rr_in_place(
        rr_1_root_v1_1,
        run,
        jurisdiction_id=_TEST_JURISDICTION_ID,
    )

    set_id = rr_1_root_v1_1.find("hl7:setId", NAMESPACES)
    assert set_id is not None
    assert set_id.get("root") == expected_setid

    version = rr_1_root_v1_1.find("hl7:versionNumber", NAMESPACES)
    assert version is not None
    assert version.get("value") == "3"


def test_augment_rr_in_place_replaces_document_id(rr_1_root_v1_1: etree.Element):
    """
    The RR's document id should be the derived augmented RR id
    (seeded from the input RR's id and the jurisdiction),
    with the tool code as authority name.
    """

    original_rr_id = rr_1_root_v1_1.find("hl7:id", NAMESPACES)
    assert original_rr_id is not None
    original_rr_id_root = original_rr_id.get("root")
    assert original_rr_id_root is not None
    expected_id = _derive_augmented_rr_id(
        original_rr_id_root,
        _TEST_JURISDICTION_ID,
    )

    run = _make_run()
    augment_rr_in_place(
        rr_1_root_v1_1,
        run,
        jurisdiction_id=_TEST_JURISDICTION_ID,
    )

    doc_id = rr_1_root_v1_1.find("hl7:id", NAMESPACES)
    assert doc_id is not None
    assert doc_id.get("root") == expected_id
    assert doc_id.get("assigningAuthorityName") == "ecr-difference-in-docs"


def test_augment_rr_in_place_adds_author_and_related_document(
    rr_1_root_v1_1: etree.Element,
):
    """
    The RR should get a v4-shape author and relatedDocument: author
    has no functionCode, softwareName has coded attrs, and the
    relatedDocument's parentDocument carries the original RR's id with
    assigningAuthorityName="original-document".
    """

    # Doc id that has already been augmented by Refiner
    input_doc_id = rr_1_root_v1_1.find("hl7:id", NAMESPACES)
    assert input_doc_id is not None

    # Doc id from the original non-augmented RR
    original_doc_id = rr_1_root_v1_1.find(
        "hl7:relatedDocument[@typeCode='XFRM']/hl7:parentDocument/hl7:id", NAMESPACES
    )
    assert original_doc_id is not None

    run = _make_run()
    augment_rr_in_place(
        rr_1_root_v1_1,
        run,
        jurisdiction_id=_TEST_JURISDICTION_ID,
    )

    # author added with v4 shape
    authors = rr_1_root_v1_1.findall("hl7:author", NAMESPACES)
    assert any(
        a.find("hl7:functionCode", NAMESPACES) is None
        and (
            software_name := a.find(
                ".//hl7:assignedAuthoringDevice/hl7:softwareName", NAMESPACES
            )
        )
        is not None
        and software_name.get("code") == "ecr-difference-in-docs"
        for a in authors
    )

    # relatedDocuments referencing the input RR and the original RR
    related_docs = rr_1_root_v1_1.findall(
        "hl7:relatedDocument[@typeCode='XFRM']", NAMESPACES
    )
    assert related_docs is not None
    assert len(related_docs) == 2

    result_original_doc_id = related_docs[0].find(
        "hl7:parentDocument/hl7:id", NAMESPACES
    )
    assert result_original_doc_id is not None
    assert result_original_doc_id.get("root") == original_doc_id.get("root")
    assert result_original_doc_id.get("assigningAuthorityName") == "original-document"

    result_input_doc_id = related_docs[1].find("hl7:parentDocument/hl7:id", NAMESPACES)
    assert result_input_doc_id is not None
    assert result_input_doc_id.get("root") == input_doc_id.get("root")
    assert result_input_doc_id.get("assigningAuthorityName") == "ecr-refiner"


def test_augment_rr_in_place_relatedDocument_carries_setId_and_version_when_input_has_them(
    rr_1_root_v1_1: etree.Element,
):
    """
    When the input RR *does* carry <setId> and <versionNumber>, the
    augmented RR's relatedDocument/parentDocument carries both into
    the lineage — faithfully, not synthesized.

    This is the diff-of-an-already-augmented-document case: augment_rr_in_place
    writes setId/versionNumber unconditionally under v4, so feeding an
    augmented RR back through diffing produces an input that has
    them. The omission in the sibling test is input-conditional, not a
    blanket RR behavior; this test pins the other half of that
    contract so a regression in _build_related_document_for_input
    can't silently drop prior identity from the chain.
    """

    # confirm the precondition before augmenting
    input_setid = rr_1_root_v1_1.find("hl7:setId", NAMESPACES)
    input_version = rr_1_root_v1_1.find("hl7:versionNumber", NAMESPACES)
    assert input_setid is not None
    assert input_version is not None

    run = _make_run()
    augment_rr_in_place(
        rr_1_root_v1_1,
        run,
        jurisdiction_id=_TEST_JURISDICTION_ID,
    )

    related_docs = rr_1_root_v1_1.findall(
        "hl7:relatedDocument[@typeCode='XFRM']", NAMESPACES
    )

    # original non-augmented parent document should not contain setId or versionNumber
    original_parent_doc = related_docs[0].find("hl7:parentDocument", NAMESPACES)
    assert original_parent_doc is not None
    assert original_parent_doc.find("hl7:setId", NAMESPACES) is None
    assert original_parent_doc.find("hl7:versionNumber", NAMESPACES) is None

    # the parent doc used as input which has already been previously augmented
    augmented_parent_doc = related_docs[1].find("hl7:parentDocument", NAMESPACES)
    assert augmented_parent_doc is not None

    # the prior identity is carried into the lineage verbatim
    augmented_parent_setid = augmented_parent_doc.find("hl7:setId", NAMESPACES)
    augmented_parent_version = augmented_parent_doc.find(
        "hl7:versionNumber", NAMESPACES
    )

    assert augmented_parent_setid is not None, "parentDocument should carry setId"
    assert augmented_parent_setid.get("root") == input_setid.get("root")

    assert augmented_parent_version is not None, (
        "parentDocument should carry versionNumber"
    )
    assert augmented_parent_version.get("value") == input_version.get("value")


# NOTE:
# CHAINING TESTS — v4 N-sibling shape
# =============================================================================


def test_augment_eicr_in_place_chains_prior_relatedDocs_as_siblings(
    eicr_1_root_v3_1_1: etree.Element,
):
    """
    Under v4, when an already-augmented eICR is augmented again, the
    output document carries N relatedDocument siblings rather than one
    block with a cumulative id list. The prior relatedDocument(s) are
    preserved verbatim and a new one is added for the augmentation we
    just performed.

    Per Vol 2 Figure 2, the original-document-pointing block appears
    first, followed by augmentation siblings in chronological order.

    The two augmentations use different scopes so the derived
    identifiers differ between calls — that lets the test verify the
    second augmentation captured the first one's output rather than
    silently re-deriving the same values.
    """

    original_id = eicr_1_root_v3_1_1.find("hl7:id", NAMESPACES)
    assert original_id is not None

    # first augmentation simulates a prior tool (e.g., ecr-refiner).
    # tool_code/tool_display travel as kwargs on augment_eicr_in_place — they
    # default to the Difference in Docs's identity in production but tests can
    # override to simulate other tools in the chain.

    augment_eicr_in_place(
        eicr_1_root_v3_1_1,
        _make_run(),
        diff_output=_make_empty_diff_output(),
        jurisdiction_id=_TEST_JURISDICTION_ID,
        tool_code="ecr-refiner",
        tool_display="eCR Refiner",
    )

    # capture what the first augmentation wrote into the document —
    # these become the "original identity" that the second
    # augmentation will capture and carry forward in its relatedDocument
    first_aug_id = eicr_1_root_v3_1_1.find("hl7:id", NAMESPACES)
    assert first_aug_id is not None
    first_aug_setid = eicr_1_root_v3_1_1.find("hl7:setId", NAMESPACES)
    assert first_aug_setid is not None

    # second augmentation simulates Difference in Docs running
    # on the prior output
    augment_eicr_in_place(
        eicr_1_root_v3_1_1,
        _make_run(),
        diff_output=_make_empty_diff_output(),
        jurisdiction_id=_TEST_JURISDICTION_ID,
    )

    # there should be two relatedDocument siblings now
    related_docs = eicr_1_root_v3_1_1.findall(
        "hl7:relatedDocument[@typeCode='XFRM']", NAMESPACES
    )

    assert len(related_docs) == 2

    # first sibling: the original-document pointer (preserved verbatim
    # from the first augmentation)
    first_sibling_id = related_docs[0].find("hl7:parentDocument/hl7:id", NAMESPACES)
    assert first_sibling_id is not None
    assert first_sibling_id.get("root") == original_id.get("root")
    assert first_sibling_id.get("assigningAuthorityName") == "original-document"

    # second sibling: the new one we just built, pointing at the
    # output of the first augmentation (which we treated as the input
    # to the second augmentation)
    second_sibling_id = related_docs[1].find("hl7:parentDocument/hl7:id", NAMESPACES)
    assert second_sibling_id is not None
    assert second_sibling_id.get("root") == first_aug_id.get("root")
    assert second_sibling_id.get("assigningAuthorityName") == "ecr-refiner"

    # second sibling also carries the prior augmentation's setId and version
    second_sibling_setid = related_docs[1].find(
        "hl7:parentDocument/hl7:setId", NAMESPACES
    )
    assert second_sibling_setid is not None
    assert second_sibling_setid.get("root") == first_aug_setid.get("root")
    assert second_sibling_setid.get("assigningAuthorityName") == "ecr-refiner"


# NOTE:
# RUN FACTORY TESTS
# =============================================================================


def test_create_augmentation_run_inherits_version_number(
    eicr_1_root_v3_1_1: etree.Element,
):
    """
    The run's version_number is the input eICR's versionNumber, not a
    DID-invented value. Both the augmented eICR and augmented RR
    are stamped with this version, so the augmented pair's
    versionNumber tracks the EHR's clinical-case versioning stream.
    """

    expected_version = eicr_1_root_v3_1_1.find("hl7:versionNumber", NAMESPACES)
    assert expected_version is not None

    run = create_augmentation_run(eicr_root=eicr_1_root_v3_1_1)

    assert run.version_number == expected_version.get("value")


def test_create_augmentation_run_captures_eicr_setid_for_rr_seeding(
    eicr_1_root_v3_1_1: etree.Element,
):
    """
    The run carries original_eicr_setid_root because the RR-side setId
    derivation seeds from the eICR's setId, not the RR's. Keeping the
    value on the run means augment_rr_in_place does not need the eICR tree
    in scope to derive its setId.
    """

    expected_setid = eicr_1_root_v3_1_1.find("hl7:setId", NAMESPACES)
    assert expected_setid is not None

    run = create_augmentation_run(eicr_root=eicr_1_root_v3_1_1)

    assert run.original_eicr_setid_root == expected_setid.get("root")


def test_pair_recoverability_via_eicr_setid_only():
    """
    A PHA holding the original eICR's setId can derive the augmented
    RR's setId without seeing the RR — given the jurisdiction id.
    This pair-recoverability property is what justifies seeding
    the augmented RR setId from the eICR's setId rather than the RR's.
    """

    eicr_setid = "orig-set-2222"

    pha_derived = _derive_augmented_rr_setid(eicr_setid, _TEST_JURISDICTION_ID)

    diff_in_docs_derived = _derive_augmented_rr_setid(eicr_setid, _TEST_JURISDICTION_ID)

    assert pha_derived == diff_in_docs_derived


# NOTE:
# DERIVATION HELPER TESTS
# =============================================================================


def test_derive_augmented_eicr_id_is_pure_function_of_inputs():
    """
    The eICR id derivation depends only on (original eICR id,
    jurisdiction, condition grouper UUID) and produces deterministic
    output.
    """

    a = _derive_augmented_eicr_id("doc-1234", "SDDH")
    b = _derive_augmented_eicr_id("doc-1234", "SDDH")
    c = _derive_augmented_eicr_id("doc-5678", "SDDH")
    d = _derive_augmented_eicr_id("doc-1234", "NY")
    assert a == b  # same inputs → same output
    assert a != c  # different document id → different output
    assert a != d  # different jurisdiction → different output


def test_derive_augmented_eicr_setid_uses_prefix():
    """
    The eICR setId derivation prefixes the source value with
    "eicr-setid:" inside the seed string. Verifying that the
    derivation differs from a naked uuid5 of the source confirms the
    prefix is actually being used.
    """

    naked = str(uuid.uuid5(DIFF_DETERMINISTIC_NS, "orig-set-2222"))
    prefixed = _derive_augmented_eicr_setid("orig-set-2222", "SDDH")
    assert naked != prefixed


def test_derive_augmented_rr_setid_distinct_from_eicr_setid():
    """
    The RR setId derivation uses a different prefix than the eICR
    setId derivation.
    """

    source = "orig-set-2222"
    eicr_setid = _derive_augmented_eicr_setid(source, "SDDH")
    rr_setid = _derive_augmented_rr_setid(source, "SDDH")
    assert eicr_setid != rr_setid


# NOTE:
# DIFF AUGMENTATION TESTS
# =============================================================================


def test_no_diff_augmentation_with_no_diff_output_changes(
    eicr_1_root_v3_1_1: etree.Element,
):
    augment_eicr_in_place(
        eicr_1_root_v3_1_1,
        _make_run(),
        diff_output=_make_empty_diff_output(),
        jurisdiction_id=_TEST_JURISDICTION_ID,
    )

    # should produce no author that has a function code of added or updated
    all_authors = eicr_1_root_v3_1_1.findall("hl7:author", NAMESPACES)

    assert all(
        not (
            a.find(
                "hl7:assignedAuthor/hl7:assignedAuthoringDevice/hl7:softwareName[@code='ecr-difference-in-docs']",
                NAMESPACES,
            )
            is not None
            and (fc := a.find("hl7:functionCode", NAMESPACES)) is not None
            and fc.get("code") in ("ADDED", "UPDATED")
        )
        for a in all_authors
    )


# NOTE:
# Find best author allowed element tests
# =============================================================================


@pytest.mark.parametrize("tag", CDA_CLINICAL_STATEMENT_TAGS)
def test_find_best_author_allowed_element_returns_anchor_when_only_anchor_allowed(tag):
    anchor = etree.Element(tag)
    assert _find_best_author_allowed_element(anchor) is anchor


def test_find_best_author_allowed_element_returns_ancestor_when_only_ancestor_allowed():
    grandparent = etree.Element(hl7_clark_tag("act"))
    parent = etree.SubElement(grandparent, hl7_clark_tag("component"))
    anchor = etree.SubElement(parent, hl7_clark_tag("value"))
    assert _find_best_author_allowed_element(anchor) is grandparent


def test_find_best_author_allowed_element_closest_ancestor_wins():
    grandparent = etree.Element(hl7_clark_tag("act"))
    parent = etree.SubElement(grandparent, hl7_clark_tag("observation"))
    anchor = etree.SubElement(parent, hl7_clark_tag("value"))
    assert _find_best_author_allowed_element(anchor) is parent


def test_find_best_author_allowed_element_returns_descendant_when_only_descendant_allowed():
    anchor = etree.Element(hl7_clark_tag("body"))
    child = etree.SubElement(anchor, hl7_clark_tag("entry"))
    grandchild = etree.SubElement(child, hl7_clark_tag("observation"))
    assert _find_best_author_allowed_element(anchor) is grandchild


def test_find_best_author_allowed_element_closest_descendant_in_document_order_wins():
    anchor = etree.Element(hl7_clark_tag("body"))
    branch = etree.SubElement(anchor, hl7_clark_tag("entry"))
    first_match = etree.SubElement(branch, hl7_clark_tag("observation"))
    etree.SubElement(anchor, hl7_clark_tag("act"))  # second match
    # iterdescendants matches depth-first
    assert _find_best_author_allowed_element(anchor) is first_match


def test_find_best_author_allowed_element_anchor_takes_priority():
    parent = etree.Element(hl7_clark_tag("act"))
    anchor = etree.SubElement(parent, hl7_clark_tag("observation"))
    etree.SubElement(anchor, "encounter")
    assert _find_best_author_allowed_element(anchor) is anchor


def test_find_best_author_allowed_element_ancestor_takes_priority_over_descendant():
    parent = etree.Element(hl7_clark_tag("act"))
    anchor = etree.SubElement(parent, hl7_clark_tag("body"))
    etree.SubElement(anchor, hl7_clark_tag("observation"))
    assert _find_best_author_allowed_element(anchor) is parent


def test_find_best_author_allowed_element_returns_none_when_anchor_disallowed():
    anchor = etree.Element(hl7_clark_tag("root"))
    assert _find_best_author_allowed_element(anchor) is None


def test_find_best_author_allowed_element_returns_none_when_nothing_allowed():
    root = etree.Element(hl7_clark_tag("root"))
    child = etree.SubElement(root, hl7_clark_tag("child"))
    anchor = etree.SubElement(child, hl7_clark_tag("anchor"))
    etree.SubElement(anchor, hl7_clark_tag("leaf"))
    assert _find_best_author_allowed_element(anchor) is None


# NOTE:
# Create diff author element tests
# =============================================================================


def _create_change(changeType: ChangeType) -> Change:
    return Change(
        changeType=changeType,
        xpath="",
        xpathDocumentId="",
        isActionable=True,
        actionabilityRuleId=uuid.UUID("12345678-1234-5678-1234-567812345678"),
        actionabilityRuleDisplayName="test rule",
    )


@pytest.fixture
def diff_author() -> etree._Element:
    return _create_diff_author_element(
        _create_change(changeType=ChangeType.ADDED), _TEST_AUGMENTATION_TIME
    )


def test_create_diff_author_element_returns_lxml_element(diff_author: etree._Element):
    assert isinstance(diff_author, etree._Element)


def test_create_diff_author_element_returns_author(diff_author: etree._Element):
    assert diff_author.tag == hl7_clark_tag("author")


def test_create_diff_author_element_includes_function_code(diff_author: etree._Element):
    fc = diff_author.find(hl7_clark_tag("functionCode"))
    assert fc is not None
    assert fc.get("code") == FUNCTION_CODE_ADD_DETECTED
    assert fc.get("codeSystem") == "2.16.840.1.113883.10.20.15.2.7.1"
    assert fc.get("codeSystemName") == "eCRDataAugmentation"


def test_create_diff_author_element_function_code_reflects_adds():
    author = _create_diff_author_element(
        _create_change(ChangeType.ADDED),
        _TEST_AUGMENTATION_TIME,
    )
    fc = author.find(hl7_clark_tag("functionCode"))
    assert fc is not None
    assert fc.get("code") == FUNCTION_CODE_ADD_DETECTED


def test_create_diff_author_element_function_code_reflects_updates():
    author = _create_diff_author_element(
        _create_change(ChangeType.UPDATED),
        _TEST_AUGMENTATION_TIME,
    )
    fc = author.find(hl7_clark_tag("functionCode"))
    assert fc is not None
    assert fc.get("code") == FUNCTION_CODE_UPDATE_DETECTED


def test_create_diff_author_element_function_code_raises_error_for_deletes():
    with pytest.raises(ValueError):
        _create_diff_author_element(
            _create_change(ChangeType.DELETED),
            _TEST_AUGMENTATION_TIME,
        )


def test_create_diff_author_element_includes_timestamp(diff_author: etree._Element):
    time = diff_author.find(hl7_clark_tag("time"))
    assert time is not None
    assert time.get("value") == _TEST_AUGMENTATION_TIME


@pytest.mark.parametrize("ts", ["20250101000000+0000", "20261231235959-0500", ""])
def test_create_diff_author_element_time_value_passes_through_verbatim(ts):
    author = _create_diff_author_element(
        _create_change(ChangeType.ADDED),
        ts,
    )
    time = author.find(hl7_clark_tag("time"))
    assert time is not None
    assert time.get("value") == ts


def test_create_diff_author_element_assigned_author_present(
    diff_author: etree._Element,
):
    assert diff_author.find(hl7_clark_tag("assignedAuthor")) is not None


@pytest.mark.parametrize("child", ["id", "addr", "telecom"])
def test_create_diff_author_element_assigned_author_null_flavor_children(
    diff_author: etree._Element, child
):
    aa = diff_author.find(hl7_clark_tag("assignedAuthor"))
    assert aa is not None
    el = aa.find(hl7_clark_tag(child))
    assert el is not None
    assert el.get("nullFlavor") == "NA"


def test_create_diff_author_element_authoring_device_present(
    diff_author: etree._Element,
):
    aa = diff_author.find(hl7_clark_tag("assignedAuthor"))
    assert aa is not None
    assert aa.find(hl7_clark_tag("assignedAuthoringDevice")) is not None


def test_create_diff_author_element_software_name_attributes(
    diff_author: etree._Element,
):
    sw = diff_author.find(
        f"{hl7_clark_tag('assignedAuthor')}"
        f"/{hl7_clark_tag('assignedAuthoringDevice')}"
        f"/{hl7_clark_tag('softwareName')}"
    )
    assert sw is not None
    assert sw.get("code") == "ecr-difference-in-docs"
    assert sw.get("codeSystem") == "2.16.840.1.113883.10.20.15.2.7.1"
    assert sw.get("codeSystemName") == "eCRDataAugmentation"
    assert sw.get("displayName") == "Difference in Docs"


def test_create_diff_author_element_child_order(diff_author: etree._Element):
    tags = [child.tag for child in diff_author]
    assert tags == [
        hl7_clark_tag("functionCode"),
        hl7_clark_tag("time"),
        hl7_clark_tag("assignedAuthor"),
    ]


def test_create_diff_author_element_no_unexpected_extra_elements(
    diff_author: etree._Element,
):
    all_tags = sorted(el.tag for el in diff_author.iter())
    expected = sorted(
        hl7_clark_tag(name)
        for name in [
            "author",
            "functionCode",
            "time",
            "assignedAuthor",
            "id",
            "addr",
            "telecom",
            "assignedAuthoringDevice",
            "softwareName",
        ]
    )
    assert all_tags == expected


# NOTE:
# Contains diff author direct child tests
# =============================================================================


def test_contains_diff_author_direct_child_true_with_valid_diff_author(
    diff_author: etree._Element,
):
    root = etree.Element(hl7_clark_tag("root"))
    root.append(diff_author)
    assert _contains_diff_author_direct_child(root) is True


def _diff_author_override(override: dict[str, str]) -> str:
    author_xml = f"""
    <author xmlns="{HL7_NS}">
        <functionCode code="ADDED"
            codeSystem="{override.get("fc_code_system", "2.16.840.1.113883.10.20.15.2.7.1")}"
            codeSystemName="{override.get("fc_code_system_name", "eCRDataAugmentation")}"/>
        <time value="20260728110219-0400"/>
        <assignedAuthor>
            <id nullFlavor="NA"/>
            <addr nullFlavor="NA"/>
            <telecom nullFlavor="NA"/>
            <assignedAuthoringDevice>
                <softwareName code="{override.get("sft_code", "ecr-difference-in-docs")}"
                    codeSystem="{override.get("sft_code_system", "2.16.840.1.113883.10.20.15.2.7.1")}"
                    codeSystemName="{override.get("sft_code_system_name", "eCRDataAugmentation")}"
                    displayName="{override.get("sft_display_name", "Difference in Docs")}"/>
            </assignedAuthoringDevice>
        </assignedAuthor>
    </author>
    """
    return author_xml


@pytest.mark.parametrize(
    "override",
    [
        {"sft_code": "wrong_code"},
        {"sft_code_system": "9.9.9.9"},
        {"sft_code_system_name": "Wrong System Name"},
        {"sft_display_name": "Wrong Display"},
        {"fc_code_system": "9.9.9.9"},
        {"fc_code_system_name": "Wrong System Name"},
    ],
)
def test_contains_diff_author_direct_child_false_when_attribute_values_unmatched(
    override: dict[str, str],
):
    author_xml = _diff_author_override(override)
    root = f"<root>{author_xml}</root>"
    assert _contains_diff_author_direct_child(elem(root)) is False


@pytest.mark.parametrize(
    "override",
    [
        {"sft_code": None},
        {"sft_code_system": None},
        {"sft_code_system_name": None},
        {"sft_display_name": None},
        {"fc_code_system": None},
        {"fc_code_system_name": None},
    ],
)
def test_contains_diff_author_direct_child_false_when_missing_attributes(
    override: dict[str, str],
):
    author_xml = _diff_author_override(override)
    root = f"<root>{author_xml}</root>"
    assert _contains_diff_author_direct_child(elem(root)) is False


def test_contains_diff_author_direct_child_false_when_no_children():
    xml = f'<root xmlns="{HL7_NS}"/>'
    assert _contains_diff_author_direct_child(elem(xml)) is False


def test_contains_diff_author_direct_child_false_when_no_author():
    xml = f'<root xmlns="{HL7_NS}"><component><section/></component></root>'
    assert _contains_diff_author_direct_child(elem(xml)) is False


def test_contains_diff_author_direct_child_false_when_software_name_missing():
    # functionCode is valid, but assignedAuthoringDevice/softwareName is absent
    xml = f"""
        <root>
            <author xmlns="{HL7_NS}">
                <functionCode code="ADDED" codeSystem="2.16.840.1.113883.10.20.15.2.7.1" codeSystemName="eCRDataAugmentation"/>
                <time value="20260728110219-0400"/>
                <assignedAuthor>
                    <id nullFlavor="NA"/>
                    <addr nullFlavor="NA"/>
                    <telecom nullFlavor="NA"/>
                    <assignedAuthoringDevice />
                </assignedAuthor>
            </author>
        </root>
    """
    assert _contains_diff_author_direct_child(elem(xml)) is False


def test_contains_diff_author_direct_child_false_when_function_code_missing():
    # softwareName is valid, but functionCode is absent
    xml = f"""
        <root>
            <author xmlns="{HL7_NS}">
                <time value="20260728110219-0400"/>
                <assignedAuthor>
                    <id nullFlavor="NA"/>
                    <addr nullFlavor="NA"/>
                    <telecom nullFlavor="NA"/>
                    <assignedAuthoringDevice>
                        <softwareName code="ecr-difference-in-docs" codeSystem="2.16.840.1.113883.10.20.15.2.7.1" codeSystemName="eCRDataAugmentation" displayName="Difference in Docs"/>
                    </assignedAuthoringDevice>
                </assignedAuthor>
            </author>
        </root>
    """
    assert _contains_diff_author_direct_child(elem(xml)) is False
