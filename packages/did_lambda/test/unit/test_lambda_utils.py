import pytest
from did_lambda.utils import (
    InfraError,
    get_did_output_key,
    get_did_output_path,
    persistence_id_from_manifest_key,
)

OUTPUT_PREFIX = "DIDOutputV2/"
PERSISTENCE_ID = "2026/07/14/497dcba3-ecbf-4587-a2dd-5eb0665e6880"
MANIFEST_KEY = f"DIDInput/{PERSISTENCE_ID}"
REFINED_EICR_KEY = f"DIDInput/{PERSISTENCE_ID}/SDDH/COVID19/eicr.xml"
EICR_KEY = f"DIDInput/{PERSISTENCE_ID}"


def test_persistence_id_from_manifest_key_removes_input_prefix():
    assert persistence_id_from_manifest_key(MANIFEST_KEY) == PERSISTENCE_ID


def test_persistence_id_from_manifest_key_requires_content_after_prefix():
    with pytest.raises(InfraError):
        persistence_id_from_manifest_key("DIDInput/")


def test_get_did_output_path_returns_output_path():
    assert (
        get_did_output_path(OUTPUT_PREFIX, PERSISTENCE_ID, REFINED_EICR_KEY)
        == f"{OUTPUT_PREFIX}{PERSISTENCE_ID}/SDDH/COVID19"
    )


def test_get_did_output_key_preserves_path_after_input_prefix():
    assert (
        get_did_output_key(
            root_prefix=OUTPUT_PREFIX,
            persistence_id=PERSISTENCE_ID,
            source_key=REFINED_EICR_KEY,
            fallback_basename="eICR.xml",
        )
        == f"{OUTPUT_PREFIX}{PERSISTENCE_ID}/SDDH/COVID19/eicr.xml"
    )


def test_get_did_output_key_on_unrefined_eicr():
    assert (
        get_did_output_key(
            root_prefix=OUTPUT_PREFIX,
            persistence_id=PERSISTENCE_ID,
            source_key=EICR_KEY,
            fallback_basename="eICR.xml",
        )
        == f"{OUTPUT_PREFIX}{PERSISTENCE_ID}/eICR.xml"
    )


def test_get_did_output_path_requires_a_nested_source_key():
    with pytest.raises(InfraError):
        get_did_output_path(OUTPUT_PREFIX, PERSISTENCE_ID, "DIDInput/eicr.xml")
