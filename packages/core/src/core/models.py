from enum import StrEnum

from pydantic import BaseModel


class DiffingOptions(BaseModel):
    """Diffing options model."""

    file1: str
    file2: str


class ChangeType(StrEnum):
    """Enum of possible diff changes that can occur between eICRs.

    - ADDED: An element/attribute was added in the current document.
    - UPDATED: An existing element's value or attributes changed.
    - DELETED: An element in the prvious document was removed.
    """

    ADDED = "ADDED"
    DELETED = "DELETED"
    UPDATED = "UPDATED"


class Change(BaseModel):
    """A change in the diff output."""

    xpath: str
    changeType: ChangeType
    xml: str
    ancestor_xml: str | None


class DiffOutput(BaseModel):
    """Diff output model."""

    changes: list[Change] = []
