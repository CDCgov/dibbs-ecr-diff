from core.cda.key_models import (
    DirectChildIdElementSetKey,
    RootExtension,
)
from core.cda.stable_key import (
    highest_ranked_stable_key as stable_key,
)
from core.cda.tags import (
    EFFECTIVE_TIME_TAG,
    ID_TAG,
    OBSERVATION_TAG,
    SECTION_TAG,
    TEMPLATE_ID_TAG,
)
from core.diff_collector import (
    _equivalent_excluding_version_metadata,
    collect_additions_updates_deletes,
)
from core.xml_utils import localname
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
        (ID_TAG, "new-id"),
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
        (TEMPLATE_ID_TAG, "template-b"),
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
            SECTION_TAG,
            DirectChildIdElementSetKey(
                root_extensions=(RootExtension(root="section-c"),),
            ),
        ),
    ]
    assert updated == []
    assert deleted == []


def test_added_direct_statement_remains_visible_after_parent_statement_set_match():
    before_root = elem(
        f"""
        <ClinicalDocument xmlns="{HL7_NS}">
          <component>
            <entry>
              <observation><id root="statement-a"/></observation>
              <observation><id root="statement-b"/></observation>
            </entry>
            <entry>
              <observation><id root="statement-x"/></observation>
              <observation><id root="statement-y"/></observation>
            </entry>
          </component>
        </ClinicalDocument>
        """
    )
    after_root = elem(
        f"""
        <ClinicalDocument xmlns="{HL7_NS}">
          <component>
            <entry>
              <observation><id root="statement-x"/></observation>
              <observation><id root="statement-y"/></observation>
            </entry>
            <entry>
              <observation><id root="statement-a"/></observation>
              <observation><id root="statement-b"/></observation>
              <observation><id root="statement-z"/></observation>
            </entry>
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
            OBSERVATION_TAG,
            DirectChildIdElementSetKey(
                root_extensions=(RootExtension(root="statement-z"),),
            ),
        ),
    ]
    assert updated == []
    assert deleted == []


def test_reordered_duplicate_template_id_entry_relationships_do_not_report_updates():
    before_root = elem(
        f"""
        <ClinicalDocument
            xmlns="{HL7_NS}"
            xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
          <component>
            <section>
              <entry>
                <encounter classCode="ENC" moodCode="EVN">
                  <entryRelationship typeCode="COMP">
                    <act classCode="ACT" moodCode="EVN">
                      <templateId root="2.16.840.1.113883.10.20.22.4.80"/>
                      <code code="29308-4" codeSystem="2.16.840.1.113883.6.1"/>
                      <entryRelationship typeCode="SUBJ">
                        <observation classCode="OBS" moodCode="EVN">
                          <id root="covid-diagnosis-id"/>
                          <code code="75323-6" codeSystem="2.16.840.1.113883.6.1"/>
                          <value xsi:type="CD" code="840539006"/>
                        </observation>
                      </entryRelationship>
                    </act>
                  </entryRelationship>
                  <entryRelationship typeCode="COMP">
                    <act classCode="ACT" moodCode="EVN">
                      <templateId root="2.16.840.1.113883.10.20.22.4.80"/>
                      <code code="29308-4" codeSystem="2.16.840.1.113883.6.1"/>
                      <entryRelationship typeCode="SUBJ">
                        <observation classCode="OBS" moodCode="EVN">
                          <id root="flu-diagnosis-id"/>
                          <code code="75323-6" codeSystem="2.16.840.1.113883.6.1"/>
                          <value xsi:type="CD" code="772828001"/>
                        </observation>
                      </entryRelationship>
                    </act>
                  </entryRelationship>
                </encounter>
              </entry>
            </section>
          </component>
        </ClinicalDocument>
        """
    )
    after_root = elem(
        f"""
        <ClinicalDocument
            xmlns="{HL7_NS}"
            xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
          <component>
            <section>
              <entry>
                <encounter classCode="ENC" moodCode="EVN">
                  <entryRelationship typeCode="COMP">
                    <act classCode="ACT" moodCode="EVN">
                      <templateId root="2.16.840.1.113883.10.20.22.4.80"/>
                      <code code="29308-4" codeSystem="2.16.840.1.113883.6.1"/>
                      <entryRelationship typeCode="SUBJ">
                        <observation classCode="OBS" moodCode="EVN">
                          <id root="flu-diagnosis-id"/>
                          <code code="75323-6" codeSystem="2.16.840.1.113883.6.1"/>
                          <value xsi:type="CD" code="772828001"/>
                        </observation>
                      </entryRelationship>
                    </act>
                  </entryRelationship>
                  <entryRelationship typeCode="COMP">
                    <act classCode="ACT" moodCode="EVN">
                      <templateId root="2.16.840.1.113883.10.20.22.4.80"/>
                      <code code="29308-4" codeSystem="2.16.840.1.113883.6.1"/>
                      <entryRelationship typeCode="SUBJ">
                        <observation classCode="OBS" moodCode="EVN">
                          <id root="covid-diagnosis-id"/>
                          <code code="75323-6" codeSystem="2.16.840.1.113883.6.1"/>
                          <value xsi:type="CD" code="840539006"/>
                        </observation>
                      </entryRelationship>
                    </act>
                  </entryRelationship>
                </encounter>
              </entry>
            </section>
          </component>
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

    assert _equivalent_excluding_version_metadata(before_root, after_root)


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

    assert not _equivalent_excluding_version_metadata(before_root, after_root)


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
    assert updated[0][0].tag == EFFECTIVE_TIME_TAG
    assert updated[0][1].tag == EFFECTIVE_TIME_TAG
    assert deleted == []


def test_nested_updates_are_not_pruned_to_the_outermost_element():
    before_root = elem(
        f"""
        <ClinicalDocument xmlns="{HL7_NS}">
          <component>
            <observation classCode="OBS" moodCode="EVN" negationInd="false">
              <id root="same-observation-id"/>
              <statusCode code="active"/>
            </observation>
          </component>
        </ClinicalDocument>
        """
    )
    after_root = elem(
        f"""
        <ClinicalDocument xmlns="{HL7_NS}">
          <component>
            <observation classCode="OBS" moodCode="EVN" negationInd="true">
              <id root="same-observation-id"/>
              <statusCode code="completed"/>
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
    assert [localname(after) for _, after in updated] == [
        "observation",
        "statusCode",
    ]
    assert deleted == []
