"""CDA stable-key dataclasses."""

from dataclasses import dataclass


@dataclass(frozen=True, order=True)
class RootExtension:
    """Comparable CDA match fields from root and optional extension."""

    root: str
    extension: str = ""


@dataclass(frozen=True)
class IdAttributeKeyBase:
    """Base for stable-key variants backed by XML ID/id attributes.

    Subclasses of IdAttributeKeyBase are intentionally separate because the source location,
    as captured in the subclass' name, is part
    of the key. Dataclass equality requires the same concrete key class, so that
    identical field values from different locations do not provide a false positive.
    WARNING:Do not collapse these subclasses into a
    single dataclass unless the matching logic is updated accordingly.
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
    """Base for stable-key variants backed by sets of root/extension fields.

    Subclasses of RootExtensionSetKeyBase are intentionally separate because the source location,
    as captured in the subclass' name, is part
    of the key. Dataclass equality requires the same concrete key class, so that
    identical field values from different locations do not provide a false positive.
    WARNING:Do not collapse these subclasses into a
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
    """Stable key of child <templateId> fields on nested clinical statement."""


@dataclass(frozen=True)
class RootExtensionKey:
    """Stable key from root/extension fields for elements that can use root/extension as an identifier."""

    root: str
    extension: str = ""


@dataclass(frozen=True)
class CodeKey:
    """Stable key from code/codeSystem match fields."""

    code: str
    code_system: str


type StableKey = (
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
