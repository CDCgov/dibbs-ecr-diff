import json

from helpers import HL7_NS


def test_cli_did_change_ignores_document_version_metadata(
    tmp_path,
    monkeypatch,
):
    from core.__main__ import main

    before_path = tmp_path / "before.xml"
    after_path = tmp_path / "after.xml"
    output_path = tmp_path / "changes.json"

    before_path.write_text(
        f"""
        <ClinicalDocument xmlns="{HL7_NS}">
          <id root="old-document-id"/>
          <setId root="same-document-series"/>
          <versionNumber value="1"/>
        </ClinicalDocument>
        """,
        encoding="utf-8",
    )
    after_path.write_text(
        f"""
        <ClinicalDocument xmlns="{HL7_NS}">
          <id root="new-document-id"/>
          <setId root="same-document-series"/>
          <versionNumber value="2"/>
          <relatedDocument typeCode="RPLC">
            <parentDocument>
              <id root="old-document-id"/>
              <setId root="same-document-series"/>
              <versionNumber value="1"/>
            </parentDocument>
          </relatedDocument>
        </ClinicalDocument>
        """,
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "sys.argv",
        [
            "core",
            str(before_path),
            str(after_path),
            "--output",
            str(output_path),
        ],
    )

    main()

    payload = json.loads(output_path.read_text(encoding="utf-8"))

    assert payload["didChange"] is False
    assert payload["clinicalDocumentId"] == "new-document-id"
    assert payload["versionNumber"] == "2"
    assert payload["changes"] == [
        {"added": []},
        {"updated": []},
        {"deleted": []},
    ]
