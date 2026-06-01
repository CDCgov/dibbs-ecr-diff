"""
core/constants.py

Module-level constants and type aliases shared across all core modules.
"""

from typing import Tuple

from lxml import etree

# ---------------------------------------------------------------------------
# Identity key attributes
# ---------------------------------------------------------------------------

# Attributes that can participate in stable identity keys when present directly
# on an element. Pair-valued attributes such as root/extension and
# code/codeSystem are interpreted together by the identity layer.
#
#   ID, id             — direct ID attributes
#   root, extension    — CDA II-style identifiers on id/templateId-like nodes
#   code, codeSystem   — coded concept keys when both are available
DIRECT_ID_IDENTITY_ATTRS = ("ID", "id")
ROOT_EXTENSION_KEY_ATTRS = ("root", "extension")
CODE_KEY_ATTRS = ("code", "codeSystem")
STRONG_KEY_ATTRS = (
    *DIRECT_ID_IDENTITY_ATTRS,
    *ROOT_EXTENSION_KEY_ATTRS,
    *CODE_KEY_ATTRS,
)

# Attributes that are useful for secondary matching context but are too broad
# to be used as standalone identity keys.
#
#   classCode  — distinguishes act class: ACT vs OBS vs ENC etc. on the same tag
#   typeCode   — distinguishes relationship semantics on entryRelationship, participant etc.
#   use        — distinguishes address/telecom purpose: H (home) vs WP (work) vs MC (mobile)
WEAK_KEY_ATTRS = ("classCode", "typeCode", "use")

# ---------------------------------------------------------------------------
# HL7 namespace
# ---------------------------------------------------------------------------

# HL7 namespace used throughout CDA/eICR documents
HL7_NS     = "urn:hl7-org:v3"
HL7_PREFIX = "hl7"

# SDTC extension namespace used in CDA/eICR documents.
SDTC_NS = "urn:hl7-org:sdtc"
SDTC_PREFIX = "sdtc"

# XML Schema instance namespace, used by attributes like xsi:type.
XSI_NS = "http://www.w3.org/2001/XMLSchema-instance"
XSI_PREFIX = "xsi"

# Passed as namespaces= to every .xpath() call so we can write hl7:tag
# instead of *[local-name()='tag']
HL7_NAMESPACE = {HL7_PREFIX: HL7_NS}

# Passed as namespaces= to XPath/ElementPath calls so code can use
# hl7:tag, sdtc:tag, etc. instead of local-name() expressions.
NAMESPACES = {
    HL7_PREFIX: HL7_NS,
    SDTC_PREFIX: SDTC_NS,
    XSI_PREFIX: XSI_NS,
}

XSI_TYPE_ATTR = f"{{{XSI_NS}}}type"

# ---------------------------------------------------------------------------
# Type aliases
# ---------------------------------------------------------------------------

# element present only in the after tree
AddedEntry = etree._Element

# (before_node, after_node) — element present in both trees with changed content
UpdatedEntry = Tuple[etree._Element, etree._Element]

# the deleted element from the before tree
DeletedEntry = etree._Element
