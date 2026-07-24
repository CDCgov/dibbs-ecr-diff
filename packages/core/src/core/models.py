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
    """Difference in Docs diffing mode."""

    ADDED = "ADDED"
    DELETED = "DELETED"
    UPDATED = "UPDATED"


class Change(BaseModel):
    """Difference in Docs change."""

    xpath: str
    rule_name: str | None = None
    changeType: ChangeType
    # maybe omit the xml in prod mode?
    # or omit entirely for PII reasons
    xml: str


class DiffOutput(BaseModel):
    """Difference in Docs diff output."""

    changes: list[Change] = []


class RuleConfig(BaseModel):
    """Difference in Docs rule."""

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
