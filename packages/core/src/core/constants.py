"""
core/constants.py

Module-level constants and type aliases shared across all core modules.
"""

from typing import Tuple
from lxml import etree

# ---------------------------------------------------------------------------
# Identity key attributes
# ---------------------------------------------------------------------------

# Attributes treated as stable identity keys when present directly on an element.
#
#   ID, id, root, extension, code  — primary CDA identifiers and coded concept keys
#   moodCode   — distinguishes intent: EVN (occurred) vs RQO (ordered) vs INT (planned)
#   classCode  — distinguishes act class: ACT vs OBS vs ENC etc. on the same tag
#   typeCode   — distinguishes relationship semantics on entryRelationship, participant etc.
#   use        — distinguishes address/telecom purpose: H (home) vs WP (work) vs MC (mobile)
KEY_ATTRS = ("ID", "id", "root", "extension", "code",
             "moodCode", "classCode", "typeCode", "use")

# ---------------------------------------------------------------------------
# HL7 namespace
# ---------------------------------------------------------------------------

# HL7 namespace used throughout CDA/eICR documents
HL7_NS     = "urn:hl7-org:v3"
HL7_PREFIX = "hl7"

# Passed as namespaces= to every .xpath() call so we can write hl7:tag
# instead of *[local-name()='tag']
NS = {HL7_PREFIX: HL7_NS}

# ---------------------------------------------------------------------------
# Type aliases
# ---------------------------------------------------------------------------

# element present only in the after tree
AddedEntry = etree._Element

# (before_node, after_node) — element present in both trees with changed content
UpdatedEntry = Tuple[etree._Element, etree._Element]

# the deleted element from the before tree
DeletedEntry = etree._Element