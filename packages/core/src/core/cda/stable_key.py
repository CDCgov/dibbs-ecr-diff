"""CDA stable-key derivation for matching elements across document versions."""

from typing import NamedTuple

from lxml import etree

from core.cda.clinical_statement import clinical_statement_element_for_key_derivation
from core.cda.key_models import (
    CodeElement,
    CodeKey,
    DirectChildCodeElementSetKey,
    DirectChildIdElementSetKey,
    DirectChildTemplateIdElementSetKey,
    DirectIdAttributeKey,
    NestedClinicalStatementCodeElementSetKey,
    NestedClinicalStatementIdAttributeKey,
    NestedClinicalStatementIdElementSetKey,
    NestedClinicalStatementTemplateIdElementSetKey,
    NestedSectionIdElementSetKey,
    NestedSectionTemplateIdElementSetKey,
    RootExtensionKey,
    StableKey,
)
from core.cda.root_extensions import (
    direct_child_root_extensions_for_tag,
    nested_section_root_extensions_for_tag,
    root_extension_from_element,
)
from core.cda.tags import CODE_TAG, ID_TAG, SET_ID_TAG, TEMPLATE_ID_TAG
from core.constants import (
    CODE_KEY_ATTRS,
    DIRECT_ID_KEY_ATTRS,
)

CODE_ATTRIBUTE, CODE_SYSTEM_ATTRIBUTE = CODE_KEY_ATTRS
TAGS_HAVING_ROOT_EXTENSION_KEYS = frozenset(
    {
        ID_TAG,
        TEMPLATE_ID_TAG,
        SET_ID_TAG,
    }
)

type StableKeyRank = int
type StableKeyCandidates = dict[StableKeyRank, StableKey | None]


class StableKeyRanks(NamedTuple):
    """Explicit numeric ranks of stable-key candidates."""

    ID_ATTRIBUTE_RANK: StableKeyRank = 1
    ROOT_EXTENSION_RANK: StableKeyRank = 2
    CODE_RANK: StableKeyRank = 3
    DIRECT_CHILD_ID_RANK: StableKeyRank = 4
    CLINICAL_STATEMENT_ID_ATTRIBUTE_RANK: StableKeyRank = 5
    CLINICAL_STATEMENT_ID_RANK: StableKeyRank = 6
    DIRECT_CHILD_CODE_RANK: StableKeyRank = 7
    CLINICAL_STATEMENT_CODE_RANK: StableKeyRank = 8
    SECTION_ID_RANK: StableKeyRank = 9
    DIRECT_CHILD_TEMPLATE_ID_RANK: StableKeyRank = 10
    SECTION_TEMPLATE_ID_RANK: StableKeyRank = 11
    CLINICAL_STATEMENT_TEMPLATE_ID_RANK: StableKeyRank = 12


STABLE_KEY_RANKS = StableKeyRanks()

if len(set(STABLE_KEY_RANKS)) != len(STABLE_KEY_RANKS):
    raise ValueError("Stable key candidate ranks must be unique")


def _id_attribute_key(elem: etree._Element) -> DirectIdAttributeKey | None:
    """Return a standalone ID/id attribute key, if present."""
    for attr in DIRECT_ID_KEY_ATTRS:
        attr_value = elem.get(attr)
        if attr_value:
            return DirectIdAttributeKey(
                name=attr,
                value=attr_value,
            )
    return None


def _root_extension_key(elem: etree._Element) -> RootExtensionKey | None:
    """Return a direct root/extension key for matching CDA id-like elements."""
    if elem.tag not in TAGS_HAVING_ROOT_EXTENSION_KEYS:
        return None

    root_extension = root_extension_from_element(elem)
    if root_extension is None:
        return None

    return RootExtensionKey(
        root=root_extension.root,
        extension=root_extension.extension,
    )


def _code_element(elem: etree._Element) -> CodeElement | None:
    """Return comparable fields from a CDA <code> element."""
    if elem.tag != CODE_TAG:
        return None

    code = elem.get(CODE_ATTRIBUTE)
    code_system = elem.get(CODE_SYSTEM_ATTRIBUTE)
    if not (code and code_system):
        return None

    return CodeElement(code=code, code_system=code_system)


def _code_key(elem: etree._Element) -> CodeKey | None:
    """Return a direct CDA <code> key only when codeSystem is present."""
    code_element = _code_element(elem)
    if code_element is None:
        return None

    return CodeKey(code=code_element.code, code_system=code_element.code_system)


def _direct_child_code_elements(elem: etree._Element) -> tuple[CodeElement, ...]:
    """Return sorted key fields from direct child <code> elements."""
    child_code_elements: set[CodeElement] = set()

    for child_code_element in elem.iterchildren(tag=CODE_TAG):
        code_element = _code_element(child_code_element)
        if code_element is not None:
            child_code_elements.add(code_element)

    return tuple(sorted(child_code_elements))


def stable_key_candidates(elem: etree._Element) -> StableKeyCandidates:
    """Return every ranked stable-key candidate available for ``elem``.

    The dictionary is ordered from the most specific candidate to the weakest
    candidate.  Every element receives the same set of candidate names, with
    ``None`` used when a candidate is not available.

    The candidates are derived from these sources:

    1. ``ID_ATTRIBUTE_RANK`` — an ID/id attribute on ``elem``.
    2. ``ROOT_EXTENSION_RANK`` — root/extension fields on ``elem`` when
       ``elem`` is an ID-like CDA element.
    3. ``CODE_RANK`` — code/codeSystem fields when ``elem`` is a ``<code>``.
    4. ``DIRECT_CHILD_ID_RANK`` — root/extensions from direct child ``<id>``
       elements.
    5. ``CLINICAL_STATEMENT_ID_ATTRIBUTE_RANK`` — an ID/id attribute on a
       nested clinical statement.
    6. ``CLINICAL_STATEMENT_ID_RANK`` — root/extensions from child ``<id>``
       elements on a nested clinical statement.
    7. ``DIRECT_CHILD_CODE_RANK`` — code/codeSystem fields from direct child
       ``<code>`` elements.
    8. ``CLINICAL_STATEMENT_CODE_RANK`` — code fields from a nested clinical
       statement.
    9. ``SECTION_ID_RANK`` — root/extensions from descendant section ``<id>``
       elements.
    10. ``DIRECT_CHILD_TEMPLATE_ID_RANK`` — root/extensions from direct child
        ``<templateId>`` elements.
    11. ``SECTION_TEMPLATE_ID_RANK`` — root/extensions from descendant section
        ``<templateId>`` elements.
    12. ``CLINICAL_STATEMENT_TEMPLATE_ID_RANK`` — root/extensions from
        ``<templateId>`` elements on a nested clinical statement.

    Matching and candidate-selection behavior is implemented by the callers.
    """
    id_attribute_candidate = _id_attribute_key(elem)
    root_extension_candidate = _root_extension_key(elem)
    code_candidate = _code_key(elem)

    clinical_statement_id_attribute_candidate = None
    clinical_statement_element = clinical_statement_element_for_key_derivation(elem)
    if clinical_statement_element is not None:
        clinical_statement_id_attribute_key = _id_attribute_key(
            clinical_statement_element
        )
        if clinical_statement_id_attribute_key:
            clinical_statement_id_attribute_candidate = (
                NestedClinicalStatementIdAttributeKey(
                    name=clinical_statement_id_attribute_key.name,
                    value=clinical_statement_id_attribute_key.value,
                )
            )

    direct_child_id_root_extensions = direct_child_root_extensions_for_tag(
        elem,
        ID_TAG,
    )
    direct_child_id_candidate = (
        DirectChildIdElementSetKey(direct_child_id_root_extensions)
        if direct_child_id_root_extensions
        else None
    )

    clinical_statement_id_candidate = None
    if clinical_statement_element is not None:
        clinical_statement_id_root_extensions = direct_child_root_extensions_for_tag(
            clinical_statement_element,
            ID_TAG,
        )
        if clinical_statement_id_root_extensions:
            clinical_statement_id_candidate = NestedClinicalStatementIdElementSetKey(
                clinical_statement_id_root_extensions
            )

    direct_child_code_elements = _direct_child_code_elements(elem)
    direct_child_code_candidate = (
        DirectChildCodeElementSetKey(direct_child_code_elements)
        if direct_child_code_elements
        else None
    )

    clinical_statement_code_candidate = None
    if (
        clinical_statement_element is not None
        and clinical_statement_element is not elem
    ):
        clinical_statement_code_elements = _direct_child_code_elements(
            clinical_statement_element
        )
        if clinical_statement_code_elements:
            clinical_statement_code_candidate = (
                NestedClinicalStatementCodeElementSetKey(
                    clinical_statement_code_elements
                )
            )

    section_id_root_extensions = nested_section_root_extensions_for_tag(
        elem,
        child_tag=ID_TAG,
    )
    section_id_candidate = (
        NestedSectionIdElementSetKey(section_id_root_extensions)
        if section_id_root_extensions
        else None
    )

    direct_child_template_id_root_extensions = direct_child_root_extensions_for_tag(
        elem,
        TEMPLATE_ID_TAG,
    )
    direct_child_template_id_candidate = (
        DirectChildTemplateIdElementSetKey(direct_child_template_id_root_extensions)
        if direct_child_template_id_root_extensions
        else None
    )

    section_template_id_root_extensions = nested_section_root_extensions_for_tag(
        elem,
        child_tag=TEMPLATE_ID_TAG,
    )
    section_template_id_candidate = (
        NestedSectionTemplateIdElementSetKey(section_template_id_root_extensions)
        if section_template_id_root_extensions
        else None
    )
    clinical_statement_template_id_candidate = None
    if clinical_statement_element is not None:
        clinical_statement_template_id_root_extensions = (
            direct_child_root_extensions_for_tag(
                clinical_statement_element,
                TEMPLATE_ID_TAG,
            )
        )
        if clinical_statement_template_id_root_extensions:
            clinical_statement_template_id_candidate = (
                NestedClinicalStatementTemplateIdElementSetKey(
                    clinical_statement_template_id_root_extensions
                )
            )

    return {
        STABLE_KEY_RANKS.ID_ATTRIBUTE_RANK: id_attribute_candidate,
        STABLE_KEY_RANKS.ROOT_EXTENSION_RANK: root_extension_candidate,
        STABLE_KEY_RANKS.CODE_RANK: code_candidate,
        STABLE_KEY_RANKS.DIRECT_CHILD_ID_RANK: direct_child_id_candidate,
        STABLE_KEY_RANKS.CLINICAL_STATEMENT_ID_ATTRIBUTE_RANK: clinical_statement_id_attribute_candidate,
        STABLE_KEY_RANKS.CLINICAL_STATEMENT_ID_RANK: clinical_statement_id_candidate,
        STABLE_KEY_RANKS.DIRECT_CHILD_CODE_RANK: direct_child_code_candidate,
        STABLE_KEY_RANKS.CLINICAL_STATEMENT_CODE_RANK: clinical_statement_code_candidate,
        STABLE_KEY_RANKS.SECTION_ID_RANK: section_id_candidate,
        STABLE_KEY_RANKS.DIRECT_CHILD_TEMPLATE_ID_RANK: direct_child_template_id_candidate,
        STABLE_KEY_RANKS.SECTION_TEMPLATE_ID_RANK: section_template_id_candidate,
        STABLE_KEY_RANKS.CLINICAL_STATEMENT_TEMPLATE_ID_RANK: clinical_statement_template_id_candidate,
    }


# TODO: refactor to get rid of this. Likely as part of deleting paths.py and
# json_output.py
def highest_ranked_stable_key(elem: etree._Element) -> StableKey | None:
    """Retrieve the most specific stable match key available for elem."""
    candidates = stable_key_candidates(elem)
    for rank in STABLE_KEY_RANKS:
        candidate = candidates[rank]
        if candidate is not None:
            return candidate
    return None
