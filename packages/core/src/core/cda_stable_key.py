"""CDA stable-key derivation for matching elements across document versions."""

from typing import Optional

from lxml import etree

from core.cda_clinical_statement import clinical_statement_element_for_key_derivation
from core.cda_key_models import (
    CodeKey,
    DirectChildIdElementSetKey,
    DirectChildTemplateIdElementSetKey,
    DirectIdAttributeKey,
    NestedClinicalStatementIdAttributeKey,
    NestedClinicalStatementIdElementSetKey,
    NestedClinicalStatementTemplateIdElementSetKey,
    NestedSectionIdElementSetKey,
    NestedSectionTemplateIdElementSetKey,
    RootExtensionKey,
    StableKey,
)
from core.cda_root_extensions import (
    direct_child_root_extensions_for_tag,
    nested_section_root_extensions_for_tag,
    root_extension_from_element,
)
from core.cda_tags import ID_TAG, TEMPLATE_ID_TAG
from core.constants import (
    CODE_KEY_ATTRS,
    DIRECT_ID_KEY_ATTRS,
)
from core.xml_utils import localname

CODE_ATTRIBUTE, CODE_SYSTEM_ATTRIBUTE = CODE_KEY_ATTRS
ELEMENT_LOCAL_NAMES_HAVING_ROOT_EXTENSION_KEYS = frozenset(
    {
        "id",
        "templateId",
        "setId",
    }
)


def _id_attribute_key(elem: etree._Element) -> Optional[DirectIdAttributeKey]:
    """Return a standalone ID/id attribute key, if present."""
    for attr in DIRECT_ID_KEY_ATTRS:
        attr_value = elem.get(attr)
        if attr_value:
            return DirectIdAttributeKey(
                name=attr,
                value=attr_value,
            )
    return None


def _root_extension_key(elem: etree._Element) -> Optional[RootExtensionKey]:
    """Return a direct root/extension key for matching CDA element names."""
    if localname(elem) not in ELEMENT_LOCAL_NAMES_HAVING_ROOT_EXTENSION_KEYS:
        return None

    root_extension = root_extension_from_element(elem)
    if root_extension is None:
        return None

    return RootExtensionKey(
        root=root_extension.root,
        extension=root_extension.extension,
    )


def _code_key(elem: etree._Element) -> Optional[CodeKey]:
    """Return a direct coded-concept key only when codeSystem is present."""
    code_value = elem.get(CODE_ATTRIBUTE)
    code_system = elem.get(CODE_SYSTEM_ATTRIBUTE)
    if not (code_value and code_system):
        return None

    return CodeKey(code=code_value, code_system=code_system)


def _attribute_key(elem: etree._Element) -> Optional[StableKey]:
    """
    Return an attribute-derived key for elem, if present.

    ID/id attributes are standalone keys. CDA root/extension attributes are
    only treated as keys on id/templateId-like elements, and code is only
    treated as a key when codeSystem is present on the same element.
    """
    id_attribute_key = _id_attribute_key(elem)
    if id_attribute_key:
        return id_attribute_key

    root_extension_key = _root_extension_key(elem)
    if root_extension_key:
        return root_extension_key

    code_key = _code_key(elem)
    if code_key:
        return code_key

    return None


def stable_key(elem: etree._Element) -> Optional[StableKey]:
    """
    Derive the most specific stable match key available for elem.

    The key is used to match elements across before/after versions.  Keys are
    tried from most to least specific; the first match wins.

    Priority:
      1. Element's own true direct attribute keys
      2. Direct child <id> root + optional extension keys
      3. Nested clinical statement direct ID/id attribute key
      4. Nested clinical statement child <id> keys
      5. Nested section <id> keys
      6. Direct child <templateId> root + extension keys
      7. Nested section templateId root + extension keys
      8. Nested clinical statement templateId root + extension keys
    """
    attribute_key = _attribute_key(elem)
    if attribute_key:
        return attribute_key

    child_id_root_extensions = direct_child_root_extensions_for_tag(
        elem,
        ID_TAG,
    )
    if child_id_root_extensions:
        return DirectChildIdElementSetKey(
            root_extensions=child_id_root_extensions,
        )

    clinical_statement_element = clinical_statement_element_for_key_derivation(elem)
    if clinical_statement_element is not None:
        stmt_id_attribute_key = _id_attribute_key(
            clinical_statement_element,
        )
        if stmt_id_attribute_key:
            return NestedClinicalStatementIdAttributeKey(
                name=stmt_id_attribute_key.name,
                value=stmt_id_attribute_key.value,
            )

        stmt_child_id_root_extensions = direct_child_root_extensions_for_tag(
            clinical_statement_element,
            ID_TAG,
        )
        if stmt_child_id_root_extensions:
            return NestedClinicalStatementIdElementSetKey(
                root_extensions=stmt_child_id_root_extensions,
            )

    nested_section_id_root_extensions = nested_section_root_extensions_for_tag(
        elem,
        child_tag=ID_TAG,
    )
    if nested_section_id_root_extensions:
        return NestedSectionIdElementSetKey(
            root_extensions=nested_section_id_root_extensions,
        )

    child_template_id_root_extensions = direct_child_root_extensions_for_tag(
        elem,
        TEMPLATE_ID_TAG,
    )
    if child_template_id_root_extensions:
        return DirectChildTemplateIdElementSetKey(
            root_extensions=child_template_id_root_extensions,
        )

    nested_section_template_id_root_extensions = nested_section_root_extensions_for_tag(
        elem,
        child_tag=TEMPLATE_ID_TAG,
    )
    if nested_section_template_id_root_extensions:
        return NestedSectionTemplateIdElementSetKey(
            root_extensions=nested_section_template_id_root_extensions,
        )

    if clinical_statement_element is not None:
        stmt_template_id_root_extensions = direct_child_root_extensions_for_tag(
            clinical_statement_element,
            TEMPLATE_ID_TAG,
        )
        if stmt_template_id_root_extensions:
            return NestedClinicalStatementTemplateIdElementSetKey(
                root_extensions=stmt_template_id_root_extensions,
            )

    return None
