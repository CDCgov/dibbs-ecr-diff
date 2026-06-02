from enum import StrEnum
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


class DiffMode(StrEnum):
    WATCH_LIST = "WATCH_LIST"
    IGNORE_LIST = "IGNORE_LIST"


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
    rule_name: str | None = None
    changeType: ChangeType
    # maybe omit the xml in prod mode?
    # or omit entirely for PII reasons
    xml: str
    ancestor_xml: str | None = None


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
