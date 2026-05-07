from enum import StrEnum
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


class ChangeType(StrEnum):
    """
    Enum of possible diff changes that can occur between eICRs.

    - NEW: An element/attribute was added in the current document.
    - UPDATED: An existing element's value or attributes changed.
    - DELETED: An element in the prvious document was removed.
    """

    NEW = "NEW"
    DELETED = "DELETED"
    UPDATED = "UPDATED"


class RuleConfig(BaseModel):
    """
    Defines a single rule configuration.

    - id: UUIDv4 identifier
    - displayName: Human-readable identifier for this rule
    - xpaths: List of XPath expressions used for matching.
    - changeTypes: Types used to restrict the rule for specific changes.
    - apply: Configuration used to classify changes for this rule.
    """

    id: UUID = Field(default_factory=uuid4)
    xpaths: list[str] = Field(min_length=1)
    changeTypes: list[ChangeType] = Field(min_length=1)


class Configuration(BaseModel):
    """
    Difference in Docs configuration object.

    - version: Semver string for config version.
    - defaults: Default rule configuration properties.
    - rules: List of rule configurations.
    """

    version: str
    rules: list[RuleConfig] = Field(default_factory=list)
