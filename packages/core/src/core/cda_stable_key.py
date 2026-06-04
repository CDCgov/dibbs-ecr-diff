"""CDA stable-key derivation for matching elements across document versions."""

from typing import Optional

from lxml import etree

from core.cda_clinical_statement import clinical_statement_identity_element
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
    RootExtension,
    RootExtensionKey,
    StableKey,
)
from core.constants import (
    CODE_KEY_ATTRS,
    DIRECT_ID_KEY_ATTRS,
    ROOT_EXTENSION_KEY_ATTRS,
    hl7_clark_tag,
)
from core.xml_utils import localname

DIRECT_TEMPLATE_ID_TAG = hl7_clark_tag("templateId")
DIRECT_ID_TAG = hl7_clark_tag("id")
SECTION_TAG = hl7_clark_tag("section")
ROOT_ATTRIBUTE, EXTENSION_ATTRIBUTE = ROOT_EXTENSION_KEY_ATTRS
CODE_ATTRIBUTE, CODE_SYSTEM_ATTRIBUTE = CODE_KEY_ATTRS
ELEMENTS_HAVING_ROOT_EXTENSION_IDENTITY = frozenset(
    {
        "id",
        "templateId",
        "setId",
    }
)


def _root_extension_from_element(
    element: etree._Element,
) -> Optional[RootExtension]:
    """Return root/extension fields from one element, or None without root."""
    root_value = element.get(ROOT_ATTRIBUTE)
    if not root_value:
        return None

    return RootExtension(
        root=root_value,
        extension=element.get(EXTENSION_ATTRIBUTE) or "",
    )


def _direct_child_root_extensions_for_tag(
    element: etree._Element,
    child_tag: str,
) -> tuple[RootExtension, ...]:
    """
    Return sorted root/extensions from direct children matching child_tag.

    Missing extensions are normalized to an empty string. The returned tuple is
    sorted and deduplicated so document order and duplicate declarations do not
    affect the exact key. Children without @root are skipped because they are
    not useful for identity matching.
    """
    root_extensions: set[RootExtension] = set()

    for child_element in element.iterchildren(tag=child_tag):
        root_extension = _root_extension_from_element(child_element)
        if root_extension is not None:
            root_extensions.add(root_extension)

    return tuple(sorted(root_extensions))


def _nested_section_root_extensions_for_tag(
    element: etree._Element,
    *,
    child_tag: str,
    limit: int = 12,
) -> tuple[RootExtension, ...]:
    """
    Return root/extensions collected from descendant sections, or no key if too broad.

    Each descendant section contributes root/extensions from direct children
    matching child_tag. The complete descendant section root/extension set is
    only used when it stays small enough to be a useful wrapper key. If the set
    grows beyond limit, return no key rather than a document-order-dependent
    partial key.
    """
    if limit <= 0:
        return ()

    nested_section_root_extensions: set[RootExtension] = set()

    for section_element in element.iterdescendants(tag=SECTION_TAG):
        nested_section_root_extensions.update(
            _direct_child_root_extensions_for_tag(section_element, child_tag)
        )
        if len(nested_section_root_extensions) > limit:
            return ()

    return tuple(sorted(nested_section_root_extensions))


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
    if localname(elem) not in ELEMENTS_HAVING_ROOT_EXTENSION_IDENTITY:
        return None

    root_extension = _root_extension_from_element(elem)
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
    Derive the most specific stable identity key available for elem.

    The key is used to match elements across before/after versions.  Keys are
    tried from most to least specific; the first match wins.

    Priority:
      1. Element's own true direct attribute keys
      2. Direct child <id> root + optional extension identities
      3. Nested clinical statement direct ID/id attribute key
      4. Nested clinical statement child <id> identities
      5. Nested section <id> identities
      6. Direct child <templateId> root + extension identities
      7. Nested section templateId root + extension identities
      8. Nested clinical statement templateId root + extension identities
    """
    attribute_key = _attribute_key(elem)
    if attribute_key:
        return attribute_key

    child_id_root_extensions = _direct_child_root_extensions_for_tag(
        elem,
        DIRECT_ID_TAG,
    )
    if child_id_root_extensions:
        return DirectChildIdElementSetKey(
            root_extensions=child_id_root_extensions,
        )

    clinical_statement_element = clinical_statement_identity_element(elem)
    if clinical_statement_element is not None:
        stmt_id_attribute_key = _id_attribute_key(
            clinical_statement_element,
        )
        if stmt_id_attribute_key:
            return NestedClinicalStatementIdAttributeKey(
                name=stmt_id_attribute_key.name,
                value=stmt_id_attribute_key.value,
            )

        stmt_child_id_root_extensions = _direct_child_root_extensions_for_tag(
            clinical_statement_element,
            DIRECT_ID_TAG,
        )
        if stmt_child_id_root_extensions:
            return NestedClinicalStatementIdElementSetKey(
                root_extensions=stmt_child_id_root_extensions,
            )

    nested_section_id_root_extensions = _nested_section_root_extensions_for_tag(
        elem,
        child_tag=DIRECT_ID_TAG,
    )
    if nested_section_id_root_extensions:
        return NestedSectionIdElementSetKey(
            root_extensions=nested_section_id_root_extensions,
        )

    child_template_id_root_extensions = _direct_child_root_extensions_for_tag(
        elem,
        DIRECT_TEMPLATE_ID_TAG,
    )
    if child_template_id_root_extensions:
        return DirectChildTemplateIdElementSetKey(
            root_extensions=child_template_id_root_extensions,
        )

    nested_section_template_id_root_extensions = _nested_section_root_extensions_for_tag(
        elem,
        child_tag=DIRECT_TEMPLATE_ID_TAG,
    )
    if nested_section_template_id_root_extensions:
        return NestedSectionTemplateIdElementSetKey(
            root_extensions=nested_section_template_id_root_extensions,
        )

    if clinical_statement_element is not None:
        stmt_template_id_root_extensions = _direct_child_root_extensions_for_tag(
            clinical_statement_element,
            DIRECT_TEMPLATE_ID_TAG,
        )
        if stmt_template_id_root_extensions:
            return NestedClinicalStatementTemplateIdElementSetKey(
                root_extensions=stmt_template_id_root_extensions,
            )

    return None
