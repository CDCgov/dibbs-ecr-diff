from did_lambda.utils import get_did_output_key

from .helpers import (
    MockS3InputFile,
    build_doc,
    build_sqs_record,
    send_input_files,
)

DID_COMPLETE_PREFIX = "DIDComplete/"
DID_OUTPUT_PREFIX = "DIDOutput/"


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

    # dynamodb should have a record for our processed file
    assert record["s3Key"] == manifest_file.eicr
    assert record["s3KeyRR"] == manifest_file.rr
    assert record["s3KeyDiffOutput"] is None
    assert record["isActionable"] is True
    assert record["comparedToVersion"] is None

    # make sure the augmented eicr/rr were correctly put in DIDOutput/
    for input_key in (manifest_file.eicr, manifest_file.rr):
        output_key = get_did_output_key(DID_OUTPUT_PREFIX, input_key)
        response = s3_client.get_object(Bucket=bucket_name, Key=output_key)
        assert response["ResponseMetadata"]["HTTPStatusCode"] == 200


def test_process_sqs_record_with_eicr_diff(s3_client, bucket_name, dynamodb_table):
    from did_lambda.lambda_function import process_sqs_record

    eicr_set_id = "eicr-set-id-1"
    rr_set_id = "rr-set-id-1"

    eicr_body_1 = build_doc(
        version_number=1,
        set_id=eicr_set_id,
        body="""
          <component>
            <section>
              <entry>
                <observation>
                    <code code="75323-6"></code>
                    <statusCode code="active" />
                </observation>
              </entry>
            </section>
          </component>
        """,
    )

    rr_body_1 = build_doc(version_number=1, set_id=rr_set_id)

    manifest_key_1, manifest_1, persistence_id_1 = send_input_files(
        s3_client,
        bucket_name=bucket_name,
        input_files=[
            MockS3InputFile(
                eicr_body=eicr_body_1,
                rr_body=rr_body_1,
                set_id=eicr_set_id,
                version_number=1,
            )
        ],
    )

    # process first input manifest
    process_sqs_record(build_sqs_record(bucket_name, manifest_key_1))

    eicr_body_2 = build_doc(
        version_number=2,
        set_id=eicr_set_id,
        body="""
          <component>
            <section>
              <entry>
                <observation>
                    <code code="75323-6"></code>
                    <statusCode code="completed" />
                </observation>
              </entry>
            </section>
          </component>
        """,
    )
    rr_body_2 = build_doc(version_number=2, set_id=rr_set_id)

    manifest_key_2, manifest_2, persistence_id_2 = send_input_files(
        s3_client,
        bucket_name=bucket_name,
        input_files=[
            MockS3InputFile(
                eicr_body=eicr_body_2,
                rr_body=rr_body_2,
                set_id=eicr_set_id,
                version_number=2,
            )
        ],
    )

    # process second input manifest
    process_sqs_record(build_sqs_record(bucket_name, manifest_key_2))

    # ensure all files exist in DIDOutput
    for manifest in (manifest_1, manifest_2):
        assert len(manifest.files) == 1
        manifest_file = manifest.files[0]
        for input_key in (manifest_file.eicr, manifest_file.rr):
            output_key = get_did_output_key(DID_OUTPUT_PREFIX, input_key)
            response = s3_client.get_object(Bucket=bucket_name, Key=output_key)
            assert response["ResponseMetadata"]["HTTPStatusCode"] == 200

    # ensure records exist in DB
    record_1 = dynamodb_table.get_item(Key={"setId": eicr_set_id, "versionNumber": 1})[
        "Item"
    ]
    record_2 = dynamodb_table.get_item(Key={"setId": eicr_set_id, "versionNumber": 2})[
        "Item"
    ]

    # v2 record should have been diffed with actionable changes against v1
    assert record_1["versionNumber"] == 1
    assert record_2["versionNumber"] == 2
    assert record_2["comparedToVersion"] == 1
    assert record_2["isActionable"] is True
    assert record_2["s3KeyDiffOutput"] is not None

    # ensure complete manifest was written
    for persistence_id in (persistence_id_1, persistence_id_2):
        response = s3_client.get_object(
            Bucket=bucket_name,
            Key=f"{DID_COMPLETE_PREFIX}{persistence_id}",
        )
        assert response["ResponseMetadata"]["HTTPStatusCode"] == 200
