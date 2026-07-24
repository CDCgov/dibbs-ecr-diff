from enum import StrEnum
from uuid import UUID, uuid4

from lxml.etree import _Element
from pydantic import BaseModel, ConfigDict, Field


class DiffMode(StrEnum):
    """Indicates whether the config list of rules is a watch list or ignore list."""

    WATCH_LIST = "WATCH_LIST"
    IGNORE_LIST = "IGNORE_LIST"


class DiffingOptions(BaseModel):
    """Options to pass into the diffing CLI."""

    file1: str
    file2: str
    config: str
    output_diff_file: str | None = None


class ChangeType(StrEnum):
    """Indicates what type of change was detected."""

    ADDED = "ADDED"
    DELETED = "DELETED"
    UPDATED = "UPDATED"


class Change(BaseModel):
    """Represents a detected change while performing a diff."""

    # Arbitrary types allowed so that lxml Element can be included without being serialized
    model_config = ConfigDict(arbitrary_types_allowed=True)
    xpath: str
    rule_name: str | None = None
    changeType: ChangeType
    xml: str
    anchor_node: _Element = Field(exclude=True)  # needed for entry-level augmentation


class DiffOutput(BaseModel):
    """Output list of changes."""

    changes: list[Change] = []


class RuleConfig(BaseModel):
    """Config of an individual rule with a list of xpaths that trigger it."""

    id: UUID = Field(default_factory=uuid4)
    name: str
    xpaths: list[str] = Field(default_factory=list)


class Configuration(BaseModel):
    """Determines how the diff engine will process detected changes based on the mode and rules."""

    version: str
    mode: DiffMode
    rules: list[RuleConfig] = Field(default_factory=list)
