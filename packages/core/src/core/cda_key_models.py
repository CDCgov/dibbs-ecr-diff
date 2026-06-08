"""CDA stable-key dataclasses."""

from dataclasses import dataclass
from typing import TypeAlias


@dataclass(frozen=True, order=True)
class RootExtension:
    """
    Comparable CDA match fields from root and optional extension.

    CDA <id> and <templateId> elements both use root as the main identifier.
    The extension, when present, further qualifies that identifier. Missing
    extensions are represented as an empty string so fields can be compared
    and sorted consistently.
    """

    root: str
    extension: str = ""


@dataclass(frozen=True)
class IdAttributeKeyBase:
    """
    Base for stable-key variants backed by XML ID/id attributes.

    Subclasses are intentionally separate because the source location is part
    of the key. Dataclass equality requires the same concrete class, so
    identical field values from different locations remain distinct.
    """

    name: str
    value: str


@dataclass(frozen=True)
class DirectIdAttributeKey(IdAttributeKeyBase):
    """Stable key from an ID/id attribute on the element itself."""


@dataclass(frozen=True)
class NestedClinicalStatementIdAttributeKey(IdAttributeKeyBase):
    """Stable key from an ID/id attribute on a nested clinical statement."""


@dataclass(frozen=True)
class RootExtensionSetKeyBase:
    """
    Base for stable-key variants backed by sets of root/extension fields.

    Subclasses are intentionally separate even when their fields are identical:
    the concrete class is part of the stable key. Do not collapse these into a
    single dataclass unless the matching logic is updated accordingly.
    """

    root_extensions: tuple[RootExtension, ...]


@dataclass(frozen=True)
class DirectChildIdElementSetKey(RootExtensionSetKeyBase):
    """Stable key from direct child <id> root/extension fields."""


@dataclass(frozen=True)
class NestedClinicalStatementIdElementSetKey(RootExtensionSetKeyBase):
    """Stable key from child <id> root/extensions on a nested clinical statement."""


@dataclass(frozen=True)
class NestedSectionIdElementSetKey(RootExtensionSetKeyBase):
    """Stable key from descendant section <id> root/extension fields."""


@dataclass(frozen=True)
class DirectChildTemplateIdElementSetKey(RootExtensionSetKeyBase):
    """Stable key from direct child <templateId> root/extension fields."""


@dataclass(frozen=True)
class NestedSectionTemplateIdElementSetKey(RootExtensionSetKeyBase):
    """Stable key from descendant section <templateId> root/extension fields."""


@dataclass(frozen=True)
class NestedClinicalStatementTemplateIdElementSetKey(RootExtensionSetKeyBase):
    """
    Stable key from child <templateId> fields on a nested clinical statement.
    """


@dataclass(frozen=True)
class RootExtensionKey:
    """Stable key from root/extension fields on id-like elements."""

    root: str
    extension: str = ""


@dataclass(frozen=True)
class CodeKey:
    """Stable key from code/codeSystem match fields."""

    code: str
    code_system: str


StableKey: TypeAlias = (
    DirectIdAttributeKey
    | NestedClinicalStatementIdAttributeKey
    | RootExtensionKey
    | CodeKey
    | DirectChildIdElementSetKey
    | NestedClinicalStatementIdElementSetKey
    | NestedSectionIdElementSetKey
    | DirectChildTemplateIdElementSetKey
    | NestedSectionTemplateIdElementSetKey
    | NestedClinicalStatementTemplateIdElementSetKey
)
