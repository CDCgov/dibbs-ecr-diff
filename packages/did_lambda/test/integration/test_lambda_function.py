from .helpers import (
    MockS3InputFile,
    build_doc,
    send_input_files,
)


def test_process_manifest_entry_with_single_file(
    s3_client, bucket_name, dynamodb_table
):
    from did_lambda.lambda_function import process_manifest_entry

    eicr_set_id = "eicr-set-id-1"
    version_number = 1

    eicr_body = build_doc(version_number, eicr_set_id)
    rr_body = build_doc(version_number, "rr-set-id-1")

    _manifest_key, manifest, persistence_id = send_input_files(
        s3_client,
        bucket_name=bucket_name,
        input_files=[
            MockS3InputFile(
                eicr_body=eicr_body,
                rr_body=rr_body,
                set_id=eicr_set_id,
                version_number=version_number,
            )
        ],
    )

    manifest_file = manifest.files[0]
    process_manifest_entry(bucket_name, persistence_id, manifest_file)

    record = dynamodb_table.get_item(
        Key={"setId": eicr_set_id, "versionNumber": version_number}
    )["Item"]

    assert record["s3Key"] == manifest_file.eicr
    assert record["s3KeyRR"] == manifest_file.rr
    assert record["s3KeyDiffOutput"] is None
    assert record["isActionable"] is True
    assert record["comparedToVersion"] is None
