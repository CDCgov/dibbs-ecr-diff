from datetime import datetime
from enum import StrEnum
from uuid import UUID, uuid4

from lxml.etree import _Element
from pydantic import BaseModel, ConfigDict, Field


class DiffMode(StrEnum):
    """Configuration mode for deciding which configured changes are actionable."""

    WATCH_LIST = "WATCH_LIST"
    IGNORE_LIST = "IGNORE_LIST"


class DiffingOptions(BaseModel):
    """Runtime options supplied to the diff command."""

    file1: str
    file2: str
    config: str
    output_diff_file: str | None = None


class ChangeType(StrEnum):
    """Possible diff change types."""

    ADDED = "ADDED"
    DELETED = "DELETED"
    UPDATED = "UPDATED"


class Change(BaseModel):
    """Single changed node reported in the diff output."""

    # Arbitrary types allowed so that lxml Element can be included without being serialized
    model_config = ConfigDict(arbitrary_types_allowed=True)
    changeType: ChangeType
    xpath: str
    xpathDocumentId: str
    isActionable: bool = (
        True  # TODO: Replace placeholders once configurations implemented
    )
    actionabilityRuleId: UUID
    actionabilityRuleDisplayName: str = "placeholder"
    anchor_node: _Element | None = Field(
        exclude=True, default=None
    )  # needed for entry-level augmentation


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
    name: str
    xpaths: list[str] = Field(default_factory=list)


class Configuration(BaseModel):
    """Diff configuration loaded by the CLI."""

    version: str
    mode: DiffMode
    rules: list[RuleConfig] = Field(default_factory=list)
