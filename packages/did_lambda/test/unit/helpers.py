"""Shared builders and parsers for Lambda unit tests."""

import json
from uuid import UUID

import pytest
from core import Change, ChangeType
from did_lambda.models import DIDOutputFile
from did_lambda.telemetry import DocumentTelemetry, ManifestEntryResult


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
            eicr="DIDOutputV2/2026/id/jurisdiction/eicr.xml",
            rr="DIDOutputV2/2026/id/jurisdiction/rr.xml",
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
