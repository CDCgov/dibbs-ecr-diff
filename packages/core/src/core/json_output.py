"""JSON serialisation of the changes summary.

Produces the changes.json file consumed by downstream systems.
"""

import json

from lxml import etree

from core.constants import (
    HL7_NS,
    HL7_PREFIX,
    NAMESPACES,
)
from core.diff_types import AddedEntry, DeletedEntry, UpdatedEntry
from core.paths import stable_xml_path, xpath_with_predicates
from core.xml_utils import build_standalone_xml_string


def get_doc_metadata(root: etree._Element) -> tuple[str, str, str]:
    """Extract setId, clinicalDocumentId, and versionNumber from the document root."""
    set_id = root.xpath("string(hl7:setId/@root)", namespaces=NAMESPACES) or ""
    doc_id = root.xpath("string(hl7:id/@root)", namespaces=NAMESPACES) or ""
    version_number = (
        root.xpath("string(hl7:versionNumber/@value)", namespaces=NAMESPACES) or ""
    )
    return set_id, doc_id, version_number


def write_changes_json(
    output_path: str,
    after_root: etree._Element,
    added: list[AddedEntry],
    updated: list[UpdatedEntry],
    deleted: list[DeletedEntry],
    did_change: bool,
) -> None:
    """Write the changes summary to a JSON file at output_path.

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

    didChange reflects meaningful changes after ignored document-version
    metadata has been filtered by the diff engine.
    """
    set_id, doc_id, version_number = get_doc_metadata(after_root)

    added_entries = []
    updated_entries = []
    deleted_entries = []

    for added_node in added:
        added_entries.append(
            {
                "sourceDocument": "after",
                "xmlPath": stable_xml_path(added_node),
                "xPath": xpath_with_predicates(added_node),
                "xml": build_standalone_xml_string(added_node),
            }
        )

    for before_node, after_node in updated:
        updated_entries.append(
            {
                "sourceDocument": "after",
                "xmlPath": stable_xml_path(after_node),
                "xPath": xpath_with_predicates(after_node),
                "xmlBefore": build_standalone_xml_string(before_node),
                "xmlAfter": build_standalone_xml_string(after_node),
            }
        )

    for deleted_node in deleted:
        deleted_entries.append(
            {
                "sourceDocument": "before",
                "xmlPath": stable_xml_path(deleted_node),
                "xPath": xpath_with_predicates(deleted_node),
                "xml": build_standalone_xml_string(deleted_node),
            }
        )

    payload = {
        "setId": set_id,
        "clinicalDocumentId": doc_id,
        "versionNumber": version_number,
        "didChange": bool(did_change),
        "xPathNamespaceBinding": {HL7_PREFIX: HL7_NS},
        "changes": [
            {"added": added_entries},
            {"updated": updated_entries},
            {"deleted": deleted_entries},
        ],
    }

    with open(output_path, "w", encoding="utf-8") as output_file:
        json.dump(payload, output_file, indent=2, ensure_ascii=False)
