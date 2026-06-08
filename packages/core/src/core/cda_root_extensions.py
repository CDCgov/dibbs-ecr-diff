"""Helpers for CDA root/extension identifier fields."""

from lxml import etree

from core.cda_key_models import RootExtension
from core.cda_tags import SECTION_TAG
from core.constants import ROOT_EXTENSION_KEY_ATTRS

ROOT_ATTRIBUTE, EXTENSION_ATTRIBUTE = ROOT_EXTENSION_KEY_ATTRS
MAX_NESTED_SECTION_ROOT_EXTENSIONS = 12


def root_extension_from_element(
    element: etree._Element,
) -> RootExtension | None:
    """Return root/extension fields from one element, or None without root."""
    root_value = element.get(ROOT_ATTRIBUTE)
    if not root_value:
        return None

    return RootExtension(
        root=root_value,
        extension=element.get(EXTENSION_ATTRIBUTE) or "",
    )


def direct_child_root_extensions_for_tag(
    element: etree._Element,
    child_tag: str,
) -> tuple[RootExtension, ...]:
    """Return sorted root/extensions from direct children matching child_tag.

    Missing extensions are normalized to an empty string. The returned tuple is
    sorted and deduplicated so document order and duplicate declarations do not
    affect the exact key. Children without @root are skipped because they are
    not useful for key matching.
    """
    root_extensions: set[RootExtension] = set()

    for child_element in element.iterchildren(tag=child_tag):
        root_extension = root_extension_from_element(child_element)
        if root_extension is not None:
            root_extensions.add(root_extension)

    return tuple(sorted(root_extensions))


def nested_section_root_extensions_for_tag(
    element: etree._Element,
    *,
    child_tag: str,
    limit: int = MAX_NESTED_SECTION_ROOT_EXTENSIONS,
) -> tuple[RootExtension, ...]:
    """Return descendant section root/extensions, or no key if too broad.

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
            direct_child_root_extensions_for_tag(section_element, child_tag)
        )
        if len(nested_section_root_extensions) > limit:
            return ()

    return tuple(sorted(nested_section_root_extensions))
