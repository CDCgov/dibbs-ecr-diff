"""CDA fallback discriminator and soft-context keys for ambiguous matching."""

from typing import Optional, Tuple

from lxml import etree

from core.cda_clinical_statement import clinical_statement_identity_element
from core.cda_key_models import RootExtension
from core.cda_narrative_keys import narrative_row_key, narrative_table_key
from core.cda_stable_key import (
    CODE_ATTRIBUTE,
    CODE_SYSTEM_ATTRIBUTE,
    DIRECT_ID_TAG,
    DIRECT_TEMPLATE_ID_TAG,
    EXTENSION_ATTRIBUTE,
    ROOT_ATTRIBUTE,
    _direct_child_root_extensions_for_tag,
)
from core.constants import WEAK_KEY_ATTRS
from core.xml_utils import (
    _complete_attribute_pair,
    _xpath_first_attribute_value,
    _xpath_first_element,
    fingerprint,
    localname,
)


def _complete_root_extension_from_element(
    element: etree._Element | None,
) -> Optional[RootExtension]:
    """Return root/extension only when both attributes are present."""
    pair = _complete_attribute_pair(element, ROOT_ATTRIBUTE, EXTENSION_ATTRIBUTE)
    if pair is None:
        return None

    root, extension = pair
    return RootExtension(root=root, extension=extension)


def _complete_root_extensions_from_direct_id_children(
    element: etree._Element,
) -> tuple[RootExtension, ...]:
    """Return sorted direct <id> root/extensions with both attributes present."""
    root_extensions: set[RootExtension] = set()

    for id_element in element.iterchildren(tag=DIRECT_ID_TAG):
        root_extension = _complete_root_extension_from_element(id_element)
        if root_extension:
            root_extensions.add(root_extension)

    return tuple(sorted(root_extensions))


def _statement_id_root_extensions(
    elem: etree._Element,
) -> tuple[RootExtension, ...]:
    """
    Return complete direct <id> root/extensions for statement fallback matching.

    Prefer IDs from the clinical statement itself when elem is a single-statement
    wrapper; fall back to elem's own direct IDs when no complete statement IDs
    are available.
    """
    clinical_statement_element = clinical_statement_identity_element(elem)
    if clinical_statement_element is not None:
        root_extensions = _complete_root_extensions_from_direct_id_children(
            clinical_statement_element,
        )
        if root_extensions:
            return root_extensions
    return _complete_root_extensions_from_direct_id_children(elem)


def _statement_code_pair(elem: etree._Element) -> Optional[Tuple[str, str]]:
    """Return (code, codeSystem) from the clinical statement's <code>, or None."""
    clinical_statement_element = clinical_statement_identity_element(elem)
    if clinical_statement_element is not None:
        pair = _complete_attribute_pair(
            _xpath_first_element(clinical_statement_element, "./hl7:code"),
            CODE_ATTRIBUTE,
            CODE_SYSTEM_ATTRIBUTE,
        )
        if pair:
            return pair
    return _complete_attribute_pair(
        _xpath_first_element(elem, "./hl7:code"),
        CODE_ATTRIBUTE,
        CODE_SYSTEM_ATTRIBUTE,
    )


def _effective_time_discriminator(node: etree._Element) -> Optional[tuple]:
    """
    Return a discriminator tuple from a node's <effectiveTime>, trying each
    representation in order: point value, low/high interval, center, period.
    Returns None if no effectiveTime is found.
    """
    point_value = _xpath_first_attribute_value(node, "./hl7:effectiveTime/@value")
    if point_value:
        return ("effectiveTime.value", point_value)

    low_value = _xpath_first_attribute_value(node, "./hl7:effectiveTime/hl7:low/@value")
    high_value = _xpath_first_attribute_value(
        node, "./hl7:effectiveTime/hl7:high/@value"
    )
    if low_value or high_value:
        return ("effectiveTime.lowhigh", (low_value or "", high_value or ""))

    center_value = _xpath_first_attribute_value(
        node, "./hl7:effectiveTime/hl7:center/@value"
    )
    if center_value:
        return ("effectiveTime.center", center_value)

    period_value = _xpath_first_attribute_value(
        node, "./hl7:effectiveTime/hl7:period/@value"
    )
    period_unit = _xpath_first_attribute_value(
        node, "./hl7:effectiveTime/hl7:period/@unit"
    )
    if period_value or period_unit:
        return ("effectiveTime.period", (period_value or "", period_unit or ""))

    return None


def _statement_effective_time(elem: etree._Element) -> Optional[tuple]:
    """
    Return an effectiveTime discriminator from the nested clinical statement
    if present, otherwise from elem itself.
    """
    clinical_statement_element = clinical_statement_identity_element(elem)
    if clinical_statement_element is not None:
        effective_time = _effective_time_discriminator(clinical_statement_element)
        if effective_time:
            return effective_time
    return _effective_time_discriminator(elem)


def _weak_attribute_discriminator(elem: etree._Element) -> Optional[tuple]:
    """
    Return weak direct attributes for late in-bucket discrimination.

    These attributes are intentionally not stable identities. They are only
    used after stronger CDA discriminators fail, and include the element tag so
    their meaning stays scoped to the element kind being compared.
    """
    items = [
        (attr, elem.attrib[attr]) for attr in WEAK_KEY_ATTRS if attr in elem.attrib
    ]
    if not items:
        return None
    return (elem.tag, tuple(items))


def secondary_discriminator(elem: etree._Element) -> tuple:
    """
    Return the best available secondary discriminator for elem.

    This is not only used when stable_key() is unavailable. It is also used
    after stable-key matching leaves an ambiguous bucket, especially when
    multiple elements share a broad stable key such as direct templateId
    root/extensions.

    Tried in priority order:
      narrative table key -> narrative row key -> statement IDs -> statement code
      -> effectiveTime -> weak direct attributes -> fingerprint
    """
    table_key = narrative_table_key(elem)
    if table_key:
        return ("narr_table", table_key)

    row_key = narrative_row_key(elem)
    if row_key:
        return ("narr_row", row_key)

    id_root_extensions = _statement_id_root_extensions(elem)
    if id_root_extensions:
        return ("id", id_root_extensions)

    code_pair = _statement_code_pair(elem)
    if code_pair:
        return ("code", code_pair)

    effective_time = _statement_effective_time(elem)
    if effective_time:
        return ("time", effective_time)

    weak_attrs = _weak_attribute_discriminator(elem)
    if weak_attrs:
        return ("weak_attrs", weak_attrs)

    return ("fp", fingerprint(elem))


def _organizer_context(elem: etree._Element) -> tuple:
    """
    Walk up the ancestor chain to find the nearest enclosing <organizer> and
    return a signature tuple for it.  Used so that observations nested inside
    different organizers (lab panels) are not incorrectly paired across panels.
    """
    current = elem.getparent()
    while current is not None:
        if localname(current) == "organizer":
            id_root_extensions = _statement_id_root_extensions(current)
            if id_root_extensions:
                return ("organizer.id", id_root_extensions)
            template_id_root_extensions = _direct_child_root_extensions_for_tag(
                current,
                DIRECT_TEMPLATE_ID_TAG,
            )
            code_pair = _statement_code_pair(current) or ("", "")
            effective_time = _statement_effective_time(current) or ("", "")
            return (
                "organizer.ctx",
                (
                    template_id_root_extensions,
                    code_pair,
                    effective_time,
                ),
            )
        current = current.getparent()
    return ("organizer.none", "")


def soft_context_key(elem: etree._Element) -> Optional[tuple]:
    """
    Return a soft context key for prefer-updates pairing.

    This is used within broad templateId buckets when stable keys alone are not
    enough to choose a one-to-one pairing. It tries to pair elements as updates
    rather than add/delete pairs when they share statement-level context.
    Returns None if no useful context can be derived.
    """
    id_root_extensions = _statement_id_root_extensions(elem)
    if id_root_extensions:
        return ("id", id_root_extensions)

    template_id_root_extensions = _direct_child_root_extensions_for_tag(
        elem,
        DIRECT_TEMPLATE_ID_TAG,
    )
    if not template_id_root_extensions:
        return None

    effective_time = _statement_effective_time(elem) or ("", "")
    organizer = _organizer_context(elem)
    code_pair = _statement_code_pair(elem) or ("", "")
    return (
        "ctx",
        (
            template_id_root_extensions,
            effective_time,
            organizer,
            code_pair,
        ),
    )
