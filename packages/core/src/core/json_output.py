"""
core/json_output.py

JSON serialisation of the changes summary.

Produces the changes.json file consumed by downstream systems.
"""

import json
from typing import List, Tuple

from lxml import etree

from core.constants import AddedEntry, UpdatedEntry, DeletedEntry, HL7_NS, HL7_PREFIX, NS
from core.paths import stable_xml_path, xpath_with_predicates
from core.xml_utils import xml_string


def get_doc_metadata(root: etree._Element) -> Tuple[str, str, str]:
    """Extract setId, clinicalDocumentId, and versionNumber from the document root."""
    set_id         = root.xpath("string(hl7:setId/@root)",          namespaces=NS) or ""
    doc_id         = root.xpath("string(hl7:id/@root)",             namespaces=NS) or ""
    version_number = root.xpath("string(hl7:versionNumber/@value)", namespaces=NS) or ""
    return set_id, doc_id, version_number


def write_changes_json(
        output_path: str,
        after_root: etree._Element,
        added: List[AddedEntry],
        updated: List[UpdatedEntry],
        deleted: List[DeletedEntry],
        did_change: bool,
) -> None:
    """
    Write the changes summary to a JSON file at output_path.

    Structure:
      {
        setId, clinicalDocumentId, versionNumber,
        didChange,
        xPathNamespaceBinding,
        changes: [ {added: [...]}, {updated: [...]}, {deleted: [...]} ]
      }

    Each change entry contains sourceDocument, xmlPath, xPath, and one or
    more xml fields with self-contained XML snippets.

    sourceDocument indicates which document the xmlPath and xPath refer to:
      "after"  — for additions and updates (element exists in the after document)
      "before" — for deletions (element no longer exists in the after document)
    """
    set_id, doc_id, version_number = get_doc_metadata(after_root)

    added_entries   = []
    updated_entries = []
    deleted_entries = []

    for added_node in added:
        added_entries.append({
            "sourceDocument": "after",
            "xmlPath": stable_xml_path(added_node),
            "xPath":   xpath_with_predicates(added_node),
            "xml":     xml_string(added_node),
        })

    for before_node, after_node in updated:
        updated_entries.append({
            "sourceDocument": "after",
            "xmlPath":   stable_xml_path(after_node),
            "xPath":     xpath_with_predicates(after_node),
            "xmlBefore": xml_string(before_node),
            "xmlAfter":  xml_string(after_node),
        })

    for deleted_node in deleted:
        deleted_entries.append({
            "sourceDocument": "before",
            "xmlPath": stable_xml_path(deleted_node),
            "xPath":   xpath_with_predicates(deleted_node),
            "xml":     xml_string(deleted_node),
        })

    payload = {
        "setId":              set_id,
        "clinicalDocumentId": doc_id,
        "versionNumber":      version_number,
        "didChange":          bool(did_change),
        "xPathNamespaceBinding": {HL7_PREFIX: HL7_NS},
        "changes": [
            {"added":   added_entries},
            {"updated": updated_entries},
            {"deleted": deleted_entries},
        ],
    }

    with open(output_path, "w", encoding="utf-8") as output_file:
        json.dump(payload, output_file, indent=2, ensure_ascii=False)