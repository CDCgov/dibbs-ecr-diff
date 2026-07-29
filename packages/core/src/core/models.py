from datetime import datetime
from enum import StrEnum
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


class DiffMode(StrEnum):
    """Difference in Docs diffing mode."""

    WATCH_LIST = "WATCH_LIST"
    IGNORE_LIST = "IGNORE_LIST"


class DiffingOptions(BaseModel):
    """Diffing inputs."""

    file1: str | bytes
    file2: str | bytes
    config: str | None = None
    output_diff_file: str | None = None


class ChangeType(StrEnum):
    """Possible diff change types."""

    ADDED = "added"
    UPDATED = "updated"
    DELETED = "deleted"


class Change(BaseModel):
    """Single changed node reported in the diff output."""

    changeType: ChangeType
    xpath: str
    xpathDocumentId: str
    isActionable: bool = (
        True  # TODO: Replace placeholders once configurations implemented
    )
    actionabilityRuleId: UUID
    actionabilityRuleDisplayName: str = "placeholder"


class Document(BaseModel):
    """Document metadata included in the diff output for current and previous documents."""

    documentId: str
    versionNumber: str


class DiffOutput(BaseModel):
    """Top-level diff output payload."""

    outputSpecVersion: str = "1.0"
    generatedAt: datetime
    configurationId: str = "00000000-0000-0000-0000-000000000000"  # TODO: Populate from configuration once implemented
    configurationVersion: str = "placeholder"
    configurationDisplayName: str = "placeholder"
    setId: str
    currentDocument: Document
    previousDocument: Document
    hasActionableChanges: bool
    changes: list[Change] = Field(default_factory=list)


class RuleConfig(BaseModel):
    """Configured rule used to match relevant XML nodes."""

    id: UUID = Field(default_factory=uuid4)
    displayName: str
    changeTypes: set[ChangeType] = Field(default_factory=set)
    xpaths: list[str] = Field(default_factory=list)


class Configuration(BaseModel):
    """Difference in Docs configuration spec."""

    displayName: str
    specVersion: str
    id: UUID = Field(default_factory=uuid4)
    createdAt: str
    mode: DiffMode
    rules: list[RuleConfig] = Field(default_factory=list)
