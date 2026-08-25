from syrupy import SnapshotAssertion

from e2e.helpers import Pair, Uploader


def test_happy_path(uploader: Uploader, snapshot: SnapshotAssertion) -> None:
    """Happy path test case."""
    input_manifest, complete_manifest, _persistence_id = uploader.send_manifest(
        [
            Pair(eicr="happy-path/1_eICR.xml", rr="happy-path/1_RR.xml"),
            Pair(eicr="happy-path/2_eICR.xml", rr="happy-path/2_RR.xml"),
            Pair(eicr="happy-path/3_eICR.xml", rr="happy-path/3_RR.xml"),
        ]
    )

    assert uploader.read_object(complete_manifest.key) == snapshot

    for index, manifest_file in enumerate(complete_manifest.files):
        for document_type, object_key in (
            ("eicr", manifest_file.eicr),
            ("rr", manifest_file.rr),
            ("eicr_diff_output", manifest_file.eicr_diff_output),
        ):
            if object_key:
                assert uploader.read_object_for_snapshot(object_key) == snapshot(
                    name=f"file_{index}_{document_type}"
                )
