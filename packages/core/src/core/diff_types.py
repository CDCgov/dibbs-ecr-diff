"""Type aliases for diff results shared by diff and output modules."""

from lxml import etree

# Element present only in the after tree.
AddedEntry = etree._Element

# Pair of matching before/after elements whose content changed.
UpdatedEntry = tuple[etree._Element, etree._Element]

# Element present only in the before tree.
DeletedEntry = etree._Element
