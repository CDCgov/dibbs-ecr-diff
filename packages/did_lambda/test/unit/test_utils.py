import json
from uuid import UUID

import pytest
from core import Change, ChangeType
from did_lambda.models import DIDOutputFile
from did_lambda.telemetry import DocumentTelemetry, ManifestEntryResult
from did_lambda.utils import (
    InfraError,
    get_did_output_key,
    get_did_output_path,
    persistence_id_from_manifest_key,
)

DID_OUTPUT_PREFIX = "DIDOutput/"
PERSISTENCE_ID = "2026/07/14/497dcba3-ecbf-4587-a2dd-5eb0665e6880"
MANIFEST_KEY = f"DIDInput/{PERSISTENCE_ID}"
REFINED_EICR_KEY = f"DIDInput/{PERSISTENCE_ID}/SDDH/COVID19/eicr.xml"
EICR_KEY = f"DIDInput/{PERSISTENCE_ID}"


def make_change(
    change_type: ChangeType,
    xpath: str = "/ClinicalDocument/component",
    section_loinc_code: str | None = None,
    is_actionable: bool = True,
) -> Change:
    """Build a representative reported change."""
    return Change(
        changeType=change_type,
        xpath=xpath,
        xpathDocumentId="document-id",
        isActionable=is_actionable,
        actionabilityRuleId=UUID(int=0),
        actionabilityRuleDisplayName="test rule",
        section_loinc_code=section_loinc_code,
    )


def make_result(
    *changes: Change,
    encounter_type: str = "ambulatory",
    unique_condition_count: int = 0,
    version_number: int = 1,
) -> ManifestEntryResult:
    """Build a representative successful manifest-entry result."""
    return ManifestEntryResult(
        output_file=DIDOutputFile(
            eicr="DIDOutput/2026/id/jurisdiction/eicr.xml",
            rr="DIDOutput/2026/id/jurisdiction/rr.xml",
            setId="set-id",
            versionNumber=version_number,
            is_actionable=True,
        ),
        changes=changes,
        telemetry=DocumentTelemetry(
            persistence_id_with_index="2026/id:0",
            version_number=version_number,
            encounter_type=encounter_type,
            unique_condition_count=unique_condition_count,
        ),
    )


def emitted_metrics(capsys: pytest.CaptureFixture[str]) -> list[dict]:
    """Return CloudWatch EMF objects emitted to standard output."""
    return [
        payload
        for line in capsys.readouterr().out.splitlines()
        if line.startswith("{") and "_aws" in (payload := json.loads(line))
    ]


def test_persistence_id_from_manifest_key_removes_input_prefix():
    assert persistence_id_from_manifest_key(MANIFEST_KEY) == PERSISTENCE_ID


def test_persistence_id_from_manifest_key_requires_content_after_prefix():
    with pytest.raises(InfraError):
        persistence_id_from_manifest_key("DIDInput/")


def test_get_did_output_path_returns_output_path():
    assert (
        get_did_output_path(DID_OUTPUT_PREFIX, PERSISTENCE_ID, REFINED_EICR_KEY)
        == f"{DID_OUTPUT_PREFIX}{PERSISTENCE_ID}/SDDH/COVID19"
    )


def test_get_did_output_key_preserves_path_after_input_prefix():
    assert (
        get_did_output_key(DID_OUTPUT_PREFIX, PERSISTENCE_ID, REFINED_EICR_KEY)
        == f"{DID_OUTPUT_PREFIX}{PERSISTENCE_ID}/SDDH/COVID19/eicr.xml"
    )


def test_get_did_output_key_on_unrefined_eicr():
    assert (
        get_did_output_key(DID_OUTPUT_PREFIX, PERSISTENCE_ID, EICR_KEY)
        == f"{DID_OUTPUT_PREFIX}{PERSISTENCE_ID}"
    )


def test_get_did_output_path_requires_a_nested_source_key():
    with pytest.raises(InfraError):
        get_did_output_path(DID_OUTPUT_PREFIX, PERSISTENCE_ID, "DIDInput/eicr.xml")
