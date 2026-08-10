"""Stateless extraction and sanitization helpers for Lambda telemetry."""

import hashlib
import hmac
import os
import re
from dataclasses import dataclass

from core import Change
from core.constants import NAMESPACES
from lxml.etree import ElementTree

DOCUMENT_CORRELATION_KEY_HEX_LENGTH = 32
MIN_LOG_HASH_SALT_BYTES = 32
_NUMERIC_POSITION_PREDICATE = re.compile(r"\[\d+\]")
_RR_CONDITION_OBSERVATION_TEMPLATE_ID = "2.16.840.1.113883.10.20.15.2.3.12"
_RR_CONDITION_VALUE_XPATH = (
    ".//hl7:observation[hl7:templateId[@root="
    f"'{_RR_CONDITION_OBSERVATION_TEMPLATE_ID}'"
    "]]/hl7:value"
)
_CONDITION_CODE_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}")
_CODE_SYSTEM_OID_PATTERN = re.compile(r"\d+(?:\.\d+)+")
_MAX_CODE_SYSTEM_OID_LENGTH = 128
_ENCOUNTER_CODE_PATH = "hl7:componentOf/hl7:encompassingEncounter/hl7:code"
_ACT_ENCOUNTER_CODE_SYSTEM = "2.16.840.1.113883.5.4"
_PHIN_VADS_CODE_SYSTEM = "2.16.840.1.114222.4.5.274"
_ENCOUNTER_TYPES = {
    (_ACT_ENCOUNTER_CODE_SYSTEM, "AMB"): "ambulatory",
    (_ACT_ENCOUNTER_CODE_SYSTEM, "EMER"): "emergency",
    (_ACT_ENCOUNTER_CODE_SYSTEM, "IMP"): "inpatient",
    (_ACT_ENCOUNTER_CODE_SYSTEM, "ACUTE"): "inpatient",
    (_ACT_ENCOUNTER_CODE_SYSTEM, "NONAC"): "inpatient",
    (_ACT_ENCOUNTER_CODE_SYSTEM, "OBSENC"): "observation",
    (_ACT_ENCOUNTER_CODE_SYSTEM, "PRENC"): "preadmission",
    (_ACT_ENCOUNTER_CODE_SYSTEM, "SS"): "short_stay",
    (_ACT_ENCOUNTER_CODE_SYSTEM, "HH"): "home_health",
    (_ACT_ENCOUNTER_CODE_SYSTEM, "FLD"): "field",
    (_ACT_ENCOUNTER_CODE_SYSTEM, "VR"): "virtual",
    (_PHIN_VADS_CODE_SYSTEM, "PHC2237"): "external_historical",
}


class TelemetryConfigurationError(RuntimeError):
    """Raised when required telemetry configuration is invalid."""


@dataclass(frozen=True, order=True, slots=True)
class ConditionCode:
    """A condition code without document-identifying context."""

    code_system: str
    code: str


def change_path_for_logging(change: Change) -> str:
    """Return a structural change path without positional predicates."""
    return _NUMERIC_POSITION_PREDICATE.sub("", change.xpath)


def make_document_correlation_key(set_id: str, version_number: int) -> str:
    """Create a deterministic pseudonymous document correlation key."""
    salt_value = os.environ.get("LOG_HASH_SALT")
    if salt_value is None:
        raise TelemetryConfigurationError("LOG_HASH_SALT is required")

    salt = salt_value.encode("utf-8")
    if len(salt) < MIN_LOG_HASH_SALT_BYTES:
        raise TelemetryConfigurationError(
            "LOG_HASH_SALT must contain at least 32 bytes"
        )

    message = set_id.encode("utf-8") + b"\x00" + str(version_number).encode("ascii")
    return hmac.new(salt, message, hashlib.sha256).hexdigest()[
        :DOCUMENT_CORRELATION_KEY_HEX_LENGTH
    ]


def condition_codes_from_rr(rr_tree: ElementTree) -> tuple[ConditionCode, ...]:
    """Return unique coded conditions from RR condition observations."""
    conditions: set[ConditionCode] = set()
    for value in rr_tree.xpath(_RR_CONDITION_VALUE_XPATH, namespaces=NAMESPACES):
        code = value.get("code")
        code_system = value.get("codeSystem")
        if code is None or code_system is None:
            continue

        code = code.strip()
        code_system = code_system.strip()
        if (
            _CONDITION_CODE_PATTERN.fullmatch(code)
            and len(code_system) <= _MAX_CODE_SYSTEM_OID_LENGTH
            and _CODE_SYSTEM_OID_PATTERN.fullmatch(code_system)
        ):
            conditions.add(ConditionCode(code_system=code_system, code=code))

    return tuple(sorted(conditions))


def encounter_type_from_eicr(eicr_tree: ElementTree) -> str:
    """Return a bounded encounter type from the eICR header."""
    encounter_code = eicr_tree.getroot().find(
        _ENCOUNTER_CODE_PATH, namespaces=NAMESPACES
    )
    if encounter_code is None:
        return "unknown"

    code = encounter_code.get("code")
    code_system = encounter_code.get("codeSystem")
    if code is None or code_system is None:
        return "unknown"

    return _ENCOUNTER_TYPES.get((code_system.strip(), code.strip()), "other")
