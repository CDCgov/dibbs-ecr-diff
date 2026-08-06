import pytest
from did_lambda.utils import (
    InfraError,
    get_did_output_key,
    get_did_output_path,
    get_key_basename,
    jurisdiction_id_from_key,
    persistence_id_from_manifest_key,
)

DID_OUTPUT_PREFIX = "DIDOutput/"
PERSISTENCE_ID = "2026/07/14/497dcba3-ecbf-4587-a2dd-5eb0665e6880"
MANIFEST_KEY = f"DIDInput/{PERSISTENCE_ID}"
EICR_KEY = f"DIDInput/{PERSISTENCE_ID}/SDDH/COVID19/eicr.xml"


def test_persistence_id_from_manifest_key_removes_input_prefix():
    assert persistence_id_from_manifest_key(MANIFEST_KEY) == PERSISTENCE_ID


def test_persistence_id_from_manifest_key_requires_content_after_prefix():
    with pytest.raises(InfraError):
        persistence_id_from_manifest_key("DIDInput/")


def test_jurisdiction_id_from_key_returns_nested_jurisdiction_id():
    assert jurisdiction_id_from_key(PERSISTENCE_ID, EICR_KEY) == "SDDH"


def test_jurisdiction_id_from_key_requires_matching_persistence_id():
    with pytest.raises(InfraError):
        jurisdiction_id_from_key("not-a-real-persistence-id", EICR_KEY)


def test_get_did_output_path_returns_output_path():
    assert (
        get_did_output_path(DID_OUTPUT_PREFIX, EICR_KEY)
        == f"{DID_OUTPUT_PREFIX}{PERSISTENCE_ID}/SDDH/COVID19"
    )


def test_get_did_output_key_preserves_path_after_input_prefix():
    assert (
        get_did_output_key(DID_OUTPUT_PREFIX, EICR_KEY)
        == f"{DID_OUTPUT_PREFIX}{PERSISTENCE_ID}/SDDH/COVID19/eicr.xml"
    )


def test_get_did_output_path_requires_a_nested_source_key():
    with pytest.raises(InfraError):
        get_did_output_path(DID_OUTPUT_PREFIX, "DIDInput/eicr.xml")


def test_key_basename_returns_basename():
    assert get_key_basename(EICR_KEY) == "eicr.xml"


def test_key_basename_rejects_empty_key():
    with pytest.raises(InfraError):
        get_key_basename("/")
