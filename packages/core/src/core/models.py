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
    config: str | None = None
    output_diff_file: str | None = None


class ChangeType(StrEnum):
    """Possible diff change types."""

    ADDED = "ADDED"
    UPDATED = "UPDATED"
    DELETED = "DELETED"


class Change(BaseModel):
    """Single changed node reported in the diff output."""

    # Arbitrary types allowed so that lxml Element can be included without being serialized
    model_config = ConfigDict(arbitrary_types_allowed=True)
    changeType: ChangeType
    xpath: str
    xpathDocumentId: str
    isActionable: bool = True
    actionabilityRuleId: UUID
    actionabilityRuleDisplayName: str
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
    configurationId: UUID
    configurationVersion: str
    configurationDisplayName: str
    setId: str
    currentDocument: Document
    previousDocument: Document
    hasActionableChanges: bool = True
    changes: list[Change] = Field(default_factory=list)


class Rule(BaseModel):
    """Configured rule used to match relevant XML nodes."""

    id: UUID = Field(default_factory=uuid4)
    displayName: str
    changeTypes: set[ChangeType] = Field(min_length=1)
    xpaths: list[str] = Field(default_factory=list)


class Configuration(BaseModel):
    """Configuration controlling which XML changes are actionable."""

    displayName: str
    specVersion: str
    configVersion: str
    id: UUID = Field(default_factory=uuid4)
    createdAt: str
    mode: DiffMode
    rules: list[Rule] = Field(default_factory=list)
