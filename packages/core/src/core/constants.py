"""Shared key-attribute and namespace constants."""

from uuid import UUID

# Reserved rule identity used when an unmatched change is actionable under an
# IGNORE_LIST configuration.
DEFAULT_ACTIONABLE_RULE_ID = UUID("b3bdf60f-e22a-4467-8e1d-c8d4df7c8df0")
DEFAULT_ACTIONABLE_RULE_DISPLAY_NAME = "Default: actionable when no ignore rule matches"

# ---------------------------------------------------------------------------
# Stable key attributes
# ---------------------------------------------------------------------------

# Attribute names used by stable-key and fallback-key derivation.
#
# Pair-valued attributes such as root/extension and code/codeSystem are
# interpreted together by the key layer; they are not standalone keys.
#
#   ID, id             — direct ID attributes
#   root, extension    — CDA II-style identifiers on id/templateId/setId nodes
#   code, codeSystem   — coded concept keys on CDA <code> elements
DIRECT_ID_KEY_ATTRS = ("ID", "id")
ROOT_EXTENSION_KEY_ATTRS = ("root", "extension")
CODE_KEY_ATTRS = ("code", "codeSystem")

# Attributes that are useful for secondary matching context but are too broad
# to be used as standalone stable keys.
#
#   classCode  — distinguishes act class: ACT vs OBS vs ENC etc. on the same tag
#   typeCode   — distinguishes relationship semantics on entryRelationship, participant etc.
#   use        — distinguishes address/telecom purpose: H (home) vs WP (work) vs MC (mobile)
WEAK_KEY_ATTRS = ("classCode", "typeCode", "use")

# ---------------------------------------------------------------------------
# XML namespaces
# ---------------------------------------------------------------------------

# HL7 namespace used throughout CDA/eICR documents
HL7_NS = "urn:hl7-org:v3"
HL7_PREFIX = "hl7"

# SDTC extension namespace used in CDA/eICR documents.
SDTC_NS = "urn:hl7-org:sdtc"
SDTC_PREFIX = "sdtc"

# XML Schema instance namespace, used by attributes like xsi:type.
XSI_NS = "http://www.w3.org/2001/XMLSchema-instance"
XSI_PREFIX = "xsi"


# Passed as namespaces= to XPath/ElementPath calls so code can use
# hl7:tag, sdtc:tag, etc. instead of local-name() expressions.
NAMESPACES = {
    HL7_PREFIX: HL7_NS,
    SDTC_PREFIX: SDTC_NS,
    XSI_PREFIX: XSI_NS,
}
