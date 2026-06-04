from core.cda.stable_key import stable_key
from core.matching import match_children_ignore_order
from helpers import HL7_NS, elem, observation


def _entry_with_direct_observation_ids(*roots: str):
    observations = "\n".join(
        f"""
        <observation classCode="OBS" moodCode="EVN">
          <id root="{root}"/>
        </observation>
        """
        for root in roots
    )
    return elem(
        f"""
        <entry xmlns="{HL7_NS}">
          {observations}
        </entry>
        """
    )


def test_matching_pairs_by_id_when_template_ids_change():
    before = observation(
        """
        <templateId root="template-a"/>
        <id root="same-id" extension="1"/>
        """
    )
    after = observation(
        """
        <templateId root="template-b"/>
        <id root="same-id" extension="1"/>
        """
    )

    assert list(match_children_ignore_order([before], [after])) == [(before, after)]


def test_matching_pairs_by_unambiguous_overlapping_child_id_when_id_is_added():
    before = observation(
        """
        <id root="stable-id" extension="1"/>
        """,
    )
    after = observation(
        """
        <id root="stable-id" extension="1"/>
        <id root="new-id" extension="2"/>
        """,
    )

    assert list(match_children_ignore_order([before], [after])) == [(before, after)]


def test_matching_pairs_by_unambiguous_overlapping_nested_statement_id():
    before = elem(
        f"""
        <entry xmlns="{HL7_NS}">
          <observation>
            <id root="stable-id" extension="1"/>
          </observation>
        </entry>
        """
    )
    after = elem(
        f"""
        <entry xmlns="{HL7_NS}">
          <observation>
            <id root="stable-id" extension="1"/>
            <id root="new-id" extension="2"/>
          </observation>
        </entry>
        """
    )

    assert list(match_children_ignore_order([before], [after])) == [(before, after)]


def test_matching_does_not_pair_ambiguous_overlapping_child_ids():
    before_first = observation(
        """
        <id root="shared-id" extension="1"/>
        """,
        '<code code="one" codeSystem="test"/>',
    )
    before_second = observation(
        """
        <id root="shared-id" extension="1"/>
        """,
        '<code code="two" codeSystem="test"/>',
    )
    after = observation(
        """
        <id root="shared-id" extension="1"/>
        <id root="new-id" extension="2"/>
        """,
    )

    pairs = list(
        match_children_ignore_order(
            [before_first, before_second],
            [after],
        )
    )

    assert (before_first, after) not in pairs
    assert (before_second, after) not in pairs
    assert (before_first, None) in pairs
    assert (before_second, None) in pairs
    assert (None, after) in pairs


def test_template_id_extension_changes_do_not_match_as_same_element():
    before = observation(
        """
        <templateId root="1"/>
        <templateId root="2" extension="old"/>
        """
    )
    after = observation(
        """
        <templateId root="1"/>
        <templateId root="2" extension="new"/>
        """
    )

    pairs = list(match_children_ignore_order([before], [after]))

    assert len(pairs) == 2
    assert (before, None) in pairs
    assert (None, after) in pairs


def test_matching_pairs_by_complete_direct_template_id_subset():
    before = observation(
        """
        <templateId root="template-a"/>
        """
    )
    after = observation(
        """
        <templateId root="template-a"/>
        <templateId root="template-b"/>
        """
    )

    assert stable_key(before) != stable_key(after)
    assert list(match_children_ignore_order([before], [after])) == [(before, after)]


def test_matching_does_not_pair_partial_direct_template_id_overlap():
    before = observation(
        """
        <templateId root="template-a"/>
        <templateId root="template-b"/>
        """
    )
    after = observation(
        """
        <templateId root="template-a"/>
        <templateId root="template-c"/>
        """
    )

    pairs = list(match_children_ignore_order([before], [after]))

    assert (before, after) not in pairs
    assert (before, None) in pairs
    assert (None, after) in pairs


def test_matching_does_not_pair_ambiguous_direct_template_id_subset():
    before_first = observation(
        """
        <templateId root="template-a"/>
        """
    )
    before_second = observation(
        """
        <templateId root="template-b"/>
        """
    )
    after = observation(
        """
        <templateId root="template-a"/>
        <templateId root="template-b"/>
        """
    )

    pairs = list(
        match_children_ignore_order(
            [before_first, before_second],
            [after],
        )
    )

    assert (before_first, after) not in pairs
    assert (before_second, after) not in pairs
    assert (before_first, None) in pairs
    assert (before_second, None) in pairs
    assert (None, after) in pairs


def test_matching_pairs_by_complete_nested_section_template_id_subset():
    before = elem(
        f"""
        <component xmlns="{HL7_NS}">
          <section><templateId root="template-a"/></section>
        </component>
        """
    )
    after = elem(
        f"""
        <component xmlns="{HL7_NS}">
          <section><templateId root="template-a"/></section>
          <section><templateId root="template-b"/></section>
        </component>
        """
    )

    assert stable_key(before) != stable_key(after)
    assert list(match_children_ignore_order([before], [after])) == [(before, after)]


def test_template_id_subset_matching_does_not_cross_stable_key_kinds():
    before = elem(
        f"""
        <component xmlns="{HL7_NS}">
          <templateId root="template-a"/>
        </component>
        """
    )
    after = elem(
        f"""
        <component xmlns="{HL7_NS}">
          <section><templateId root="template-a"/></section>
        </component>
        """
    )

    pairs = list(match_children_ignore_order([before], [after]))

    assert (before, after) not in pairs
    assert (before, None) in pairs
    assert (None, after) in pairs


def test_matching_pairs_by_complete_nested_statement_template_id_subset():
    before = elem(
        f"""
        <entry xmlns="{HL7_NS}">
          <observation classCode="OBS" moodCode="EVN">
            <templateId root="template-a"/>
          </observation>
        </entry>
        """
    )
    after = elem(
        f"""
        <entry xmlns="{HL7_NS}">
          <observation classCode="OBS" moodCode="EVN">
            <templateId root="template-a"/>
            <templateId root="template-b"/>
          </observation>
        </entry>
        """
    )

    assert stable_key(before) != stable_key(after)
    assert list(match_children_ignore_order([before], [after])) == [(before, after)]


def test_matching_pairs_by_complete_nested_section_id_subset_when_section_is_added():
    before = elem(
        f"""
        <component xmlns="{HL7_NS}">
          <section><id root="section-a"/></section>
          <section><id root="section-b"/></section>
        </component>
        """
    )
    after = elem(
        f"""
        <component xmlns="{HL7_NS}">
          <section><id root="section-a"/></section>
          <section><id root="section-b"/></section>
          <section><id root="section-c"/></section>
        </component>
        """
    )

    assert stable_key(before) != stable_key(after)
    assert list(match_children_ignore_order([before], [after])) == [(before, after)]


def test_matching_pairs_by_complete_direct_statement_id_subset():
    before_ab = _entry_with_direct_observation_ids("a", "b")
    before_xy = _entry_with_direct_observation_ids("x", "y")
    after_xy = _entry_with_direct_observation_ids("x", "y")
    after_abz = _entry_with_direct_observation_ids("a", "b", "z")

    pairs = list(match_children_ignore_order(
        [before_ab, before_xy],
        [after_xy, after_abz],
    ))

    assert (before_ab, after_abz) in pairs
    assert (before_xy, after_xy) in pairs


def test_matching_does_not_pair_partial_nested_section_id_overlap():
    before = elem(
        f"""
        <component xmlns="{HL7_NS}">
          <section><id root="section-a"/></section>
          <section><id root="section-b"/></section>
        </component>
        """
    )
    after = elem(
        f"""
        <component xmlns="{HL7_NS}">
          <section><id root="section-a"/></section>
          <section><id root="section-c"/></section>
        </component>
        """
    )

    pairs = list(match_children_ignore_order([before], [after]))

    assert (before, after) not in pairs
    assert (before, None) in pairs
    assert (None, after) in pairs


def test_matching_does_not_pair_ambiguous_nested_section_id_overlap():
    before_first = elem(
        f"""
        <component xmlns="{HL7_NS}">
          <section><id root="section-a"/></section>
        </component>
        """
    )
    before_second = elem(
        f"""
        <component xmlns="{HL7_NS}">
          <section><id root="section-b"/></section>
        </component>
        """
    )
    after = elem(
        f"""
        <component xmlns="{HL7_NS}">
          <section><id root="section-a"/></section>
          <section><id root="section-b"/></section>
        </component>
        """
    )

    pairs = list(
        match_children_ignore_order(
            [before_first, before_second],
            [after],
        )
    )

    assert (before_first, after) not in pairs
    assert (before_second, after) not in pairs
    assert (before_first, None) in pairs
    assert (before_second, None) in pairs
    assert (None, after) in pairs


def test_matching_pairs_template_ids_independent_of_document_order():
    before_first = elem(f'<section xmlns="{HL7_NS}"><id root="a"/></section>')
    before_second = elem(f'<section xmlns="{HL7_NS}"><id root="b"/></section>')
    
    after_first = elem(f'<section xmlns="{HL7_NS}"><id root="b"/></section>')
    after_second = elem(f'<section xmlns="{HL7_NS}"><id root="a"/></section>')
    
    assert list(match_children_ignore_order(
        [before_first, before_second],
        [after_first, after_second],
    )) == [
               (before_first, after_second),
               (before_second, after_first),
           ]


def test_weak_attributes_are_only_late_in_bucket_discriminators():
    before_home = elem(
        f"""<telecom xmlns="{HL7_NS}" use="HP" value="tel:+15551110000"/>"""
    )
    before_work = elem(
        f"""<telecom xmlns="{HL7_NS}" use="WP" value="tel:+15552220000"/>"""
    )
    after_work = elem(
        f"""<telecom xmlns="{HL7_NS}" use="WP" value="tel:+15552229999"/>"""
    )
    after_home = elem(
        f"""<telecom xmlns="{HL7_NS}" use="HP" value="tel:+15551119999"/>"""
    )

    pairs = list(
        match_children_ignore_order(
            [before_home, before_work],
            [after_work, after_home],
        )
    )

    assert (before_home, after_home) in pairs
    assert (before_work, after_work) in pairs
