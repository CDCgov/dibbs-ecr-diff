from core.cda_key_models import (
    DirectChildIdElementSetKey,
    RootExtension,
)
from core.cda_stable_key import (
    stable_key,
)
from core.diff_engine import (
    _fingerprint_excluding_version_metadata,
    collect_additions_updates_deletes,
)
from helpers import HL7_NS, elem


def test_added_child_id_remains_visible_after_parent_overlap_match():
    before_root = elem(
        f"""
        <ClinicalDocument xmlns="{HL7_NS}">
          <component>
            <observation>
              <id root="stable-id" extension="1"/>
            </observation>
          </component>
        </ClinicalDocument>
        """
    )
    after_root = elem(
        f"""
        <ClinicalDocument xmlns="{HL7_NS}">
          <component>
            <observation>
              <id root="stable-id" extension="1"/>
              <id root="new-id" extension="2"/>
            </observation>
          </component>
        </ClinicalDocument>
        """
    )

    added, updated, deleted = collect_additions_updates_deletes(
        before_root,
        after_root,
    )

    assert [(node.tag, node.get("root")) for node in added] == [
        (f"{{{HL7_NS}}}id", "new-id"),
    ]
    assert updated == []
    assert deleted == []


def test_added_template_id_remains_visible_after_parent_subset_match():
    before_root = elem(
        f"""
        <ClinicalDocument xmlns="{HL7_NS}">
          <component>
            <observation>
              <templateId root="template-a"/>
            </observation>
          </component>
        </ClinicalDocument>
        """
    )
    after_root = elem(
        f"""
        <ClinicalDocument xmlns="{HL7_NS}">
          <component>
            <observation>
              <templateId root="template-a"/>
              <templateId root="template-b"/>
            </observation>
          </component>
        </ClinicalDocument>
        """
    )

    added, updated, deleted = collect_additions_updates_deletes(
        before_root,
        after_root,
    )

    assert [(node.tag, node.get("root")) for node in added] == [
        (f"{{{HL7_NS}}}templateId", "template-b"),
    ]
    assert updated == []
    assert deleted == []


def test_added_section_remains_visible_after_nested_section_overlap_match():
    before_root = elem(
        f"""
        <ClinicalDocument xmlns="{HL7_NS}">
          <component>
            <section><id root="section-a"/></section>
            <section><id root="section-b"/></section>
          </component>
        </ClinicalDocument>
        """
    )
    after_root = elem(
        f"""
        <ClinicalDocument xmlns="{HL7_NS}">
          <component>
            <section><id root="section-a"/></section>
            <section><id root="section-b"/></section>
            <section><id root="section-c"/></section>
          </component>
        </ClinicalDocument>
        """
    )

    added, updated, deleted = collect_additions_updates_deletes(
        before_root,
        after_root,
    )

    assert [(node.tag, stable_key(node)) for node in added] == [
        (
            f"{{{HL7_NS}}}section",
            DirectChildIdElementSetKey(
                root_extensions=(RootExtension(root="section-c"),),
            ),
        ),
    ]
    assert updated == []
    assert deleted == []


def test_document_version_metadata_is_ignored_by_diff():
    before_root = elem(
        f"""
        <ClinicalDocument
            xmlns="{HL7_NS}"
            xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
            xsi:schemaLocation="old-schema">
          <id root="old-document-id"/>
          <effectiveTime value="20200101"/>
          <setId root="same-document-series"/>
          <versionNumber value="1"/>
        </ClinicalDocument>
        """
    )
    after_root = elem(
        f"""
        <ClinicalDocument
            xmlns="{HL7_NS}"
            xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
            xsi:schemaLocation="new-schema">
          <id root="new-document-id"/>
          <effectiveTime value="20200102"/>
          <setId root="same-document-series"/>
          <versionNumber value="2"/>
          <relatedDocument typeCode="RPLC">
            <parentDocument>
              <id root="old-document-id"/>
              <setId root="same-document-series"/>
              <versionNumber value="1"/>
            </parentDocument>
          </relatedDocument>
        </ClinicalDocument>
        """
    )

    added, updated, deleted = collect_additions_updates_deletes(
        before_root,
        after_root,
    )

    assert added == []
    assert updated == []
    assert deleted == []


def test_fingerprint_excluding_version_metadata_ignores_document_version_metadata():
    before_root = elem(
        f"""
        <ClinicalDocument
            xmlns="{HL7_NS}"
            xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
            xsi:schemaLocation="old-schema">
          <id root="old-document-id"/>
          <effectiveTime value="20200101"/>
          <setId root="same-document-series"/>
          <versionNumber value="1"/>
          <component>
            <observation>
              <id root="same-observation-id"/>
              <code code="ASSERTION"/>
            </observation>
          </component>
        </ClinicalDocument>
        """
    )
    after_root = elem(
        f"""
        <ClinicalDocument
            xmlns="{HL7_NS}"
            xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
            xsi:schemaLocation="new-schema">
          <id root="new-document-id"/>
          <effectiveTime value="20200102"/>
          <setId root="same-document-series"/>
          <versionNumber value="2"/>
          <relatedDocument typeCode="RPLC">
            <parentDocument>
              <id root="old-document-id"/>
              <setId root="same-document-series"/>
              <versionNumber value="1"/>
            </parentDocument>
          </relatedDocument>
          <component>
            <observation>
              <id root="same-observation-id"/>
              <code code="ASSERTION"/>
            </observation>
          </component>
        </ClinicalDocument>
        """
    )

    assert _fingerprint_excluding_version_metadata(
        before_root
    ) == _fingerprint_excluding_version_metadata(after_root)


def test_fingerprint_excluding_version_metadata_includes_nested_observation_id():
    before_root = elem(
        f"""
        <ClinicalDocument xmlns="{HL7_NS}">
          <id root="before-document-id"/>
          <versionNumber value="1"/>
          <component>
            <observation>
              <id root="before-observation-id"/>
              <code code="ASSERTION"/>
            </observation>
          </component>
        </ClinicalDocument>
        """
    )
    after_root = elem(
        f"""
        <ClinicalDocument xmlns="{HL7_NS}">
          <id root="after-document-id"/>
          <versionNumber value="2"/>
          <component>
            <observation>
              <id root="after-observation-id"/>
              <code code="ASSERTION"/>
            </observation>
          </component>
        </ClinicalDocument>
        """
    )

    assert _fingerprint_excluding_version_metadata(
        before_root
    ) != _fingerprint_excluding_version_metadata(after_root)


def test_clinical_statement_effective_time_is_not_ignored_by_diff():
    before_root = elem(
        f"""
        <ClinicalDocument xmlns="{HL7_NS}">
          <setId root="same-document-series"/>
          <component>
            <observation>
              <id root="same-observation-id"/>
              <effectiveTime value="20200101"/>
            </observation>
          </component>
        </ClinicalDocument>
        """
    )
    after_root = elem(
        f"""
        <ClinicalDocument xmlns="{HL7_NS}">
          <setId root="same-document-series"/>
          <component>
            <observation>
              <id root="same-observation-id"/>
              <effectiveTime value="20200102"/>
            </observation>
          </component>
        </ClinicalDocument>
        """
    )

    added, updated, deleted = collect_additions_updates_deletes(
        before_root,
        after_root,
    )

    assert added == []
    assert len(updated) == 1
    assert updated[0][0].tag == f"{{{HL7_NS}}}effectiveTime"
    assert updated[0][1].tag == f"{{{HL7_NS}}}effectiveTime"
    assert deleted == []
