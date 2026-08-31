from syrupy import SnapshotAssertion

from e2e.helpers import Pair, Uploader


def test_refined_pairs(uploader: Uploader, snapshot: SnapshotAssertion) -> None:
    """Refined eICRs test case."""
    input_manifest, complete_manifest, _persistence_id = uploader.send_manifest(
        [
            Pair(eicr="happy-path/1_eICR.xml", rr="happy-path/1_RR.xml"),
            Pair(eicr="happy-path/2_eICR.xml", rr="happy-path/2_RR.xml"),
            Pair(eicr="happy-path/3_eICR.xml", rr="happy-path/3_RR.xml"),
        ]
    )

    assert len(complete_manifest.files) == 3

    assert complete_manifest.files[0].is_actionable
    assert complete_manifest.files[1].is_actionable
    assert not complete_manifest.files[2].is_actionable

    # first version should not have a diff output
    assert complete_manifest.files[0].versionNumber == 1
    assert complete_manifest.files[0].eicr_diff_output is None

    # snapshot assertions
    assert uploader.read_object(complete_manifest.key) == snapshot
    for index, manifest_file in enumerate(complete_manifest.files):
        for key in ("eicr", "rr", "eicr_diff_output"):
            if object_key := getattr(manifest_file, key):
                assert uploader.read_object(object_key) == snapshot(
                    name=f"file_{index}_{key}"
                )
