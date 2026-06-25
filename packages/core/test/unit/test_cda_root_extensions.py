from core.cda.key_models import RootExtension
from core.cda.root_extensions import (
    MAX_NESTED_SECTION_ROOT_EXTENSIONS,
    direct_child_root_extensions_for_tag,
    nested_section_root_extensions_for_tag,
    root_extension_from_element,
)
from core.cda.tags import ID_TAG, TEMPLATE_ID_TAG
from helpers import HL7_NS, elem, observation


def test_root_extension_from_element_returns_root_and_normalized_extension():
    id_element = elem(
        f"""<id xmlns="{HL7_NS}" root="root-value" extension="extension-value"/>"""
    )
    set_id_element = elem(f"""<setId xmlns="{HL7_NS}" root="set-id-root"/>""")
    missing_root = elem(f"""<id xmlns="{HL7_NS}" extension="missing-root"/>""")

    assert root_extension_from_element(id_element) == RootExtension(
        root="root-value",
        extension="extension-value",
    )
    assert root_extension_from_element(set_id_element) == RootExtension(
        root="set-id-root",
    )
    assert root_extension_from_element(missing_root) is None


def test_direct_child_root_extensions_for_tag_sorts_deduplicates_and_skips_missing_root():
    element = observation(
        """
        <templateId root="2" extension="b"/>
        <templateId root="1"/>
        <templateId root="2" extension="b"/>
        <templateId extension="missing-root"/>
        """
    )

    assert direct_child_root_extensions_for_tag(
        element,
        TEMPLATE_ID_TAG,
    ) == (
        RootExtension(root="1"),
        RootExtension(root="2", extension="b"),
    )


def test_nested_section_root_extensions_for_tag_keeps_complete_set_at_limit():
    sections = "\n".join(
        f"""<section><id root="section-{index:02}"/></section>"""
        for index in range(MAX_NESTED_SECTION_ROOT_EXTENSIONS)
    )
    component = elem(
        f"""
        <component xmlns="{HL7_NS}">
          {sections}
        </component>
        """
    )

    assert nested_section_root_extensions_for_tag(
        component,
        child_tag=ID_TAG,
    ) == tuple(
        RootExtension(root=f"section-{index:02}")
        for index in range(MAX_NESTED_SECTION_ROOT_EXTENSIONS)
    )


def test_nested_section_root_extensions_for_tag_returns_no_key_above_limit():
    sections = "\n".join(
        f"""<section><id root="section-{index:02}"/></section>"""
        for index in range(MAX_NESTED_SECTION_ROOT_EXTENSIONS + 1)
    )
    component = elem(
        f"""
        <component xmlns="{HL7_NS}">
          {sections}
        </component>
        """
    )

    assert nested_section_root_extensions_for_tag(component, child_tag=ID_TAG) == ()
