import pytest
from core.cda.clinical_statement import CDA_CLINICAL_STATEMENT_LOCAL_NAMES
from core.cda.stable_key import (
    STABLE_KEY_RANKS,
    stable_key_candidates,
)
from core.cda.stable_key import (
    highest_ranked_stable_key as stable_key,
)
from core.matching import (
    _stable_key_matching,
    _stable_key_subset_matching,
    _unique_sibling_elements_by_key,
    match_children_ignore_order,
)
from helpers import HL7_NS, elem, observation


def _stable_key_candidates_by_element(*element_groups):
    return {
        element: stable_key_candidates(element)
        for element_group in element_groups
        for element in element_group
    }


def _entry_with_direct_statement_ids(
    statement_local_name: str,
    *roots: str,
):
    observations = "\n".join(
        f"""
        <{statement_local_name} classCode="OBS" moodCode="EVN">
          <id root="{root}"/>
        </{statement_local_name}>
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


def test_matching_pairs_by_id_when_lower_ranked_candidate_key_changes():
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


def test_changing_template_id_extension_does_not_result_in_match():
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


def test_matching_does_not_pair_partial_template_id_subset_overlap():
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


def test_matching_does_not_pair_many_to_one_template_id_subset():
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


def test_overlap_fallback_uses_section_ids_when_a_higher_ranked_key_changes():
    before = elem(
        f"""
        <component xmlns="{HL7_NS}">
          <code code="old-code" codeSystem="test"/>
          <section><id root="section-a"/></section>
        </component>
        """
    )
    after = elem(
        f"""
        <component xmlns="{HL7_NS}">
          <code code="new-code" codeSystem="test"/>
          <section><id root="section-a"/></section>
          <section><id root="section-b"/></section>
        </component>
        """
    )

    stable_key_candidates_by_element = _stable_key_candidates_by_element(
        [before],
        [after],
    )
    pairs, unmatched_before, unmatched_after = _stable_key_subset_matching(
        [before],
        [after],
        stable_key_candidates_by_element,
    )

    assert pairs == [(before, after)]
    assert not unmatched_before
    assert not unmatched_after


@pytest.mark.parametrize(
    "statement_local_name",
    sorted(CDA_CLINICAL_STATEMENT_LOCAL_NAMES),
)
def test_matching_pairs_by_complete_direct_statement_id_subset(statement_local_name):
    before_ab = _entry_with_direct_statement_ids(statement_local_name, "a", "b")
    before_xy = _entry_with_direct_statement_ids(statement_local_name, "x", "y")
    after_xy = _entry_with_direct_statement_ids(statement_local_name, "x", "y")
    after_abz = _entry_with_direct_statement_ids(
        statement_local_name,
        "a",
        "b",
        "z",
    )

    pairs = list(
        match_children_ignore_order(
            [before_ab, before_xy],
            [after_xy, after_abz],
        )
    )

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

    assert list(
        match_children_ignore_order(
            [before_first, before_second],
            [after_first, after_second],
        )
    ) == [
        (before_first, after_second),
        (before_second, after_first),
    ]


def test_ranked_matching_uses_next_candidate_after_first_pass():
    before_id = elem(f'<id xmlns="{HL7_NS}" ID="id-before"/>')
    before_root = elem(f'<id xmlns="{HL7_NS}" root="shared-root"/>')
    after_id = elem(f'<id xmlns="{HL7_NS}" ID="id-after"/>')
    after_root = elem(f'<id xmlns="{HL7_NS}" root="shared-root"/>')

    pairs, unmatched_before, unmatched_after = _stable_key_matching(
        [before_id, before_root],
        [after_id, after_root],
        _stable_key_candidates_by_element(
            [before_id, before_root],
            [after_id, after_root],
        ),
    )

    assert pairs == [(before_root, after_root)]
    assert unmatched_before == [before_id]
    assert unmatched_after == [after_id]


def test_ranked_matching_recovers_with_lower_rank_after_ambiguous_candidate():
    before_first = elem(f'<id xmlns="{HL7_NS}" ID="shared" root="root-a"/>')
    before_second = elem(f'<id xmlns="{HL7_NS}" ID="shared" root="root-b"/>')
    after_first = elem(f'<id xmlns="{HL7_NS}" ID="shared" root="root-a"/>')
    after_second = elem(f'<id xmlns="{HL7_NS}" ID="shared" root="root-b"/>')

    pairs, unmatched_before, unmatched_after = _stable_key_matching(
        [before_first, before_second],
        [after_first, after_second],
        _stable_key_candidates_by_element(
            [before_first, before_second],
            [after_first, after_second],
        ),
    )

    assert pairs == [(before_first, after_first), (before_second, after_second)]
    assert unmatched_before == []
    assert unmatched_after == []


def test_ranked_matching_pairs_multiple_unique_candidates_in_one_pass():
    before_first = elem(f'<id xmlns="{HL7_NS}" root="root-a"/>')
    before_second = elem(f'<id xmlns="{HL7_NS}" root="root-b"/>')
    after_first = elem(f'<id xmlns="{HL7_NS}" root="root-a"/>')
    after_second = elem(f'<id xmlns="{HL7_NS}" root="root-b"/>')

    pairs, unmatched_before, unmatched_after = _stable_key_matching(
        [before_first, before_second],
        [after_first, after_second],
        _stable_key_candidates_by_element(
            [before_first, before_second],
            [after_first, after_second],
        ),
    )

    assert pairs == [(before_first, after_first), (before_second, after_second)]
    assert unmatched_before == []
    assert unmatched_after == []


def test_ranked_matching_marks_four_duplicate_candidates_ambiguous():
    before_elements = [
        elem(f'<id xmlns="{HL7_NS}" root="shared-root"/>') for _ in range(4)
    ]
    after_elements = [
        elem(f'<id xmlns="{HL7_NS}" root="shared-root"/>') for _ in range(4)
    ]
    before_candidates = {
        element: stable_key_candidates(element) for element in before_elements
    }

    unique_elements = _unique_sibling_elements_by_key(
        before_elements,
        before_candidates,
        STABLE_KEY_RANKS.ROOT_EXTENSION_RANK,
    )

    shared_root_key = stable_key_candidates(before_elements[0])[
        STABLE_KEY_RANKS.ROOT_EXTENSION_RANK
    ]
    assert shared_root_key is not None
    assert unique_elements[shared_root_key] is None

    pairs, unmatched_before, unmatched_after = _stable_key_matching(
        before_elements,
        after_elements,
        _stable_key_candidates_by_element(before_elements, after_elements),
    )
    assert pairs == []
    assert unmatched_before == before_elements
    assert unmatched_after == after_elements


def test_ranked_matching_leaves_overlap_for_fallback_matching():
    before = observation('<id root="stable-id" extension="1"/>')
    after = observation(
        '<id root="stable-id" extension="1"/><id root="new-id" extension="2"/>'
    )

    ranked_pairs, unmatched_before, unmatched_after = _stable_key_matching(
        [before],
        [after],
        _stable_key_candidates_by_element([before], [after]),
    )

    assert ranked_pairs == []
    assert unmatched_before == [before]
    assert unmatched_after == [after]
    assert list(match_children_ignore_order([before], [after])) == [(before, after)]


def test_matching_does_not_emit_an_element_in_more_than_one_pair():
    before_first = elem(f'<id xmlns="{HL7_NS}" root="root-a"/>')
    before_second = elem(f'<id xmlns="{HL7_NS}" root="root-b"/>')
    after_first = elem(f'<id xmlns="{HL7_NS}" root="root-b"/>')
    after_second = elem(f'<id xmlns="{HL7_NS}" root="root-a"/>')

    pairs = list(
        match_children_ignore_order(
            [before_first, before_second],
            [after_first, after_second],
        )
    )

    assert pairs == [
        (before_first, after_second),
        (before_second, after_first),
    ]


def test_ranked_matching_rejects_one_to_many_matches():
    before = elem(f'<id xmlns="{HL7_NS}" root="shared-root"/>')
    after_first = elem(f'<id xmlns="{HL7_NS}" root="shared-root"/>')
    after_second = elem(f'<id xmlns="{HL7_NS}" root="shared-root"/>')

    pairs, unmatched_before, unmatched_after = _stable_key_matching(
        [before],
        [after_first, after_second],
        _stable_key_candidates_by_element([before], [after_first, after_second]),
    )

    assert pairs == []
    assert unmatched_before == [before]
    assert unmatched_after == [after_first, after_second]


def test_ranked_matching_rejects_many_to_one_matches():
    before_first = elem(f'<id xmlns="{HL7_NS}" root="shared-root"/>')
    before_second = elem(f'<id xmlns="{HL7_NS}" root="shared-root"/>')
    after = elem(f'<id xmlns="{HL7_NS}" root="shared-root"/>')

    pairs, unmatched_before, unmatched_after = _stable_key_matching(
        [before_first, before_second],
        [after],
        _stable_key_candidates_by_element(
            [before_first, before_second],
            [after],
        ),
    )

    assert pairs == []
    assert unmatched_before == [before_first, before_second]
    assert unmatched_after == [after]


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


@pytest.mark.parametrize(
    ("stable_key_rank", "xml"),
    [
        (
            STABLE_KEY_RANKS.ID_ATTRIBUTE_RANK,
            f'<observation xmlns="{HL7_NS}" ID="id"/>',
        ),
        (STABLE_KEY_RANKS.ROOT_EXTENSION_RANK, f'<id xmlns="{HL7_NS}" root="root"/>'),
        (
            STABLE_KEY_RANKS.CODE_RANK,
            f'<code xmlns="{HL7_NS}" code="code" codeSystem="system"/>',
        ),
        (
            STABLE_KEY_RANKS.DIRECT_CHILD_ID_RANK,
            f'<observation xmlns="{HL7_NS}"><id root="root-a"/><id root="root-b"/></observation>',
        ),
        (
            STABLE_KEY_RANKS.CLINICAL_STATEMENT_ID_ATTRIBUTE_RANK,
            f'<entry xmlns="{HL7_NS}"><observation ID="id"/></entry>',
        ),
        (
            STABLE_KEY_RANKS.CLINICAL_STATEMENT_ID_RANK,
            f'<entry xmlns="{HL7_NS}"><observation><id root="root-a"/><id root="root-b"/></observation></entry>',
        ),
        (
            STABLE_KEY_RANKS.DIRECT_CHILD_CODE_RANK,
            f'<observation xmlns="{HL7_NS}"><code code="code-a" codeSystem="system"/><code code="code-b" codeSystem="system"/></observation>',
        ),
        (
            STABLE_KEY_RANKS.CLINICAL_STATEMENT_CODE_RANK,
            f'<entry xmlns="{HL7_NS}"><observation><code code="code-a" codeSystem="system"/><code code="code-b" codeSystem="system"/></observation></entry>',
        ),
        (
            STABLE_KEY_RANKS.SECTION_ID_RANK,
            f'<component xmlns="{HL7_NS}"><section><id root="root-a"/><section><id root="root-b"/></section></section></component>',
        ),
        (
            STABLE_KEY_RANKS.DIRECT_CHILD_TEMPLATE_ID_RANK,
            f'<observation xmlns="{HL7_NS}"><templateId root="template-a"/><templateId root="template-b"/></observation>',
        ),
        (
            STABLE_KEY_RANKS.SECTION_TEMPLATE_ID_RANK,
            f'<component xmlns="{HL7_NS}"><section><templateId root="template-a"/><section><templateId root="template-b"/></section></section></component>',
        ),
        (
            STABLE_KEY_RANKS.CLINICAL_STATEMENT_TEMPLATE_ID_RANK,
            f'<entry xmlns="{HL7_NS}"><observation><templateId root="template-a"/><templateId root="template-b"/></observation></entry>',
        ),
    ],
)
def test_ranked_matching_pairs_each_stable_key_candidate_class(
    stable_key_rank,
    xml,
):
    before = elem(xml)
    after = elem(xml)

    candidates = _stable_key_candidates_by_element([before], [after])

    assert candidates[before][stable_key_rank] is not None
    assert list(match_children_ignore_order([before], [after])) == [(before, after)]


def test_subset_matching_applies_stronger_fallbacks_first_and_exhausts_matches():
    before_first = observation(
        '<id root="child-a"/>'
        '<id root="child-b"/>'
        '<templateId root="template-a"/>'
        '<templateId root="template-b"/>'
    )
    after_first = observation(
        '<id root="child-a"/>'
        '<id root="child-z"/>'
        '<templateId root="template-a"/>'
        '<templateId root="template-z"/>'
    )
    before_second = observation(
        '<id root="child-c"/><id root="child-d"/><templateId root="template-g"/>'
    )
    after_second = observation(
        '<id root="child-e"/>'
        '<id root="child-f"/>'
        '<templateId root="template-g"/>'
        '<templateId root="template-h"/>'
    )
    before_elements = [before_first, before_second]
    after_elements = [after_first, after_second]

    pairs = list(match_children_ignore_order(before_elements, after_elements))

    assert pairs == [
        (before_first, after_first),
        (before_second, after_second),
    ]


def test_matching_rejects_one_to_many_partial_child_id_subset_match():
    before_elements = [observation('<id root="a"/><id root="c"/>')]
    after_elements = [
        observation('<id root="a"/><id root="b"/>'),
        observation('<id root="c"/><id root="d"/>'),
    ]

    pairs = list(match_children_ignore_order(before_elements, after_elements))
    matched_pairs = [
        (before, after)
        for before, after in pairs
        if before is not None and after is not None
    ]
    deleted_elements = [before for before, after in pairs if after is None]
    added_elements = [after for before, after in pairs if before is None]

    assert matched_pairs == []
    assert deleted_elements == before_elements
    assert added_elements == after_elements


def test_matching_rejects_many_to_one_partial_child_id_subset_match():
    before_elements = [
        observation('<id root="a"/><id root="b"/>'),
        observation('<id root="b"/><id root="c"/>'),
    ]
    after_elements = [observation('<id root="a"/><id root="c"/>')]

    pairs = list(match_children_ignore_order(before_elements, after_elements))
    matched_pairs = [
        (before, after)
        for before, after in pairs
        if before is not None and after is not None
    ]
    deleted_elements = [before for before, after in pairs if after is None]
    added_elements = [after for before, after in pairs if before is None]

    assert matched_pairs == []
    assert deleted_elements == before_elements
    assert added_elements == after_elements


@pytest.mark.parametrize(
    ("before_count", "after_count"),
    [
        pytest.param(0, 0, id="both-empty"),
        pytest.param(1, 0, id="before-only"),
        pytest.param(0, 1, id="after-only"),
        pytest.param(2, 0, id="multiple-before-only"),
        pytest.param(0, 2, id="multiple-after-only"),
    ],
)
def test_matching_handles_empty_and_one_sided_input(before_count, after_count):
    before_elements = [observation("") for _ in range(before_count)]
    after_elements = [observation("") for _ in range(after_count)]

    assert list(match_children_ignore_order(before_elements, after_elements)) == [
        *[(before, None) for before in before_elements],
        *[(None, after) for after in after_elements],
    ]
