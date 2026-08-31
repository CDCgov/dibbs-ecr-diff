from syrupy import SnapshotAssertion

from e2e.helpers import Pair, Uploader


def test_refined_pairs(uploader: Uploader, snapshot: SnapshotAssertion) -> None:
    """Refined eICRs test case."""
    input_manifest, complete_manifest, _persistence_id = uploader.send_manifest(
        [
            Pair(eicr="example/1_eICR.xml", rr="example/1_RR.xml"),
            Pair(eicr="example/2_eICR.xml", rr="example/2_RR.xml"),
            Pair(eicr="example/3_eICR.xml", rr="example/3_RR.xml"),
            Pair(eicr="example/4_eICR.xml", rr="example/4_RR.xml"),
        ]
    )

    assert len(complete_manifest.files) == 4
    (file_1, file_2, file_3, file_4) = complete_manifest.files

    assert file_1.is_actionable
    assert file_2.is_actionable
    assert file_3.is_actionable
    assert not file_4.is_actionable

    # first version should not have a diff output
    assert file_1.versionNumber == 1
    assert file_1.eicr_diff_output is None

    # versions 2-4 should have diff outputs
    assert file_2.versionNumber == 2
    assert file_2.eicr_diff_output is not None
    assert file_3.versionNumber == 3
    assert file_3.eicr_diff_output is not None
    assert file_4.versionNumber == 4
    assert file_4.eicr_diff_output is not None

    # snapshot assertions
    assert uploader.read_object(complete_manifest.key) == snapshot
    for index, manifest_file in enumerate(complete_manifest.files):
        for key in ("eicr", "rr", "eicr_diff_output"):
            if object_key := getattr(manifest_file, key):
                assert uploader.read_object(object_key) == snapshot(
                    name=f"file_{index}_{key}"
                )
