from enum import StrEnum

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


class Status(StrEnum):
    """
    Enum of statuses assigned when a change is detected after rule evaluation.

    This is used to determine "actionability".
    - IGNORED: Change is not significant.
    - FLAGGED: Change is considered significant and potentially actionable.
    - UNKNOWN: Fallback state when no rule applies (should be set in ConfigDefaults).
    """

    IGNORED = "IGNORED"
    FLAGGED = "FLAGGED"
    UNKNOWN = "UNKNOWN"


class RuleApply(BaseModel):
    """
    Classification outcome that is applied to a change when a rule matches.

    This object determines the "then" part of a rule.
    If a change satisfies the XPath match conditions, this config
    should determine how it is labeled.
    """

    status: Status


class RuleDefaults(BaseModel):
    """
    Default rule configurations.

    A RuleApply must be defined to apply statuses for changes
    without matching rules.
    """

    apply: RuleApply


class RuleConfig(BaseModel):
    """
    Defines a single rule configuration.

    - id: Unique identifier for the rule
    - xpaths: List of XPath expressions used for matching
    - changeTypes: Types used to restrict the rule for specific changes
    - apply: Configuration used to classify changes for this rule
    """

    id: str = Field(min_length=1)
    xpaths: list[str] = Field(min_length=1)
    changeTypes: list[ChangeType] = Field(min_length=1)
    apply: RuleApply


class Configuration(BaseModel):
    """
    Difference in Docs configuration object.

    - defaults: Default rule configuration properties
    - rules: List of rule configurations
    """

    defaults: RuleDefaults
    rules: list[RuleConfig] = Field(default_factory=list)
