from enum import StrEnum
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


class DiffMode(StrEnum):
    WATCH = "WATCH"
    IGNORE = "IGNORE"


class DiffingOptions(BaseModel):
    file1: str
    file2: str
    config: str


class ChangeType(StrEnum):
    ADDED = "ADDED"
    DELETED = "DELETED"
    UPDATED = "UPDATED"


class Change(BaseModel):
    xpath: str
    rule_name: str = ""
    changeType: ChangeType
    xml: str
    ancestor_xml: str | None


class DiffOutput(BaseModel):
    changes: list[Change] = []


class RuleConfig(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    name: str
    xpaths: list[str] = Field(default_factory=list)


class Configuration(BaseModel):
    version: str
    mode: DiffMode
    rules: list[RuleConfig] = Field(default_factory=list)
