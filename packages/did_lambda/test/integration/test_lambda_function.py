import json

from did_lambda.utils import get_did_output_key

from .helpers import (
    MockS3InputFile,
    build_doc,
    build_sqs_record,
    send_input_files,
)

COMPLETE_PREFIX = "DIDCompleteV2/"
OUTPUT_PREFIX = "DIDOutputV2/"


def test_lambda_handler_preserves_pipeline_and_emits_success_telemetry(
    s3_client,
    bucket_name,
    dynamodb_table,
    capsys,
    caplog,
):
    from did_lambda.lambda_function import lambda_handler

    eicr_set_id = "eicr-set-id-handler"
    manifest_key, manifest, persistence_id = send_input_files(
        s3_client,
        bucket_name=bucket_name,
        input_files=[
            MockS3InputFile(
                eicr_body=build_doc(1, eicr_set_id),
                rr_body=build_doc(1, "rr-set-id-handler"),
                set_id=eicr_set_id,
                version_number=1,
            )
        ],
    )
    caplog.set_level("INFO")

    response = lambda_handler(
        {"Records": [build_sqs_record(bucket_name, manifest_key).raw_event]},
        None,
    )

    assert response == {"statusCode": 200, "message": "OK"}

    manifest_file = manifest.files[0]

    for fallback_basename, source_key in (
        ("eICR.xml", manifest_file.eicr),
        ("RR.xml", manifest_file.rr),
    ):
        output_key = get_did_output_key(
            root_prefix=OUTPUT_PREFIX,
            persistence_id=persistence_id,
            source_key=source_key,
            fallback_basename=fallback_basename,
        )
        response = s3_client.get_object(Bucket=bucket_name, Key=output_key)
        assert response["ResponseMetadata"]["HTTPStatusCode"] == 200

    completion = s3_client.get_object(
        Bucket=bucket_name,
        Key=f"{COMPLETE_PREFIX}{persistence_id}",
    )
    assert completion["ResponseMetadata"]["HTTPStatusCode"] == 200

    stored_record = dynamodb_table.get_item(
        Key={"setId": eicr_set_id, "versionNumber": 1}
    )["Item"]
    assert stored_record["s3Key"] == manifest_file.eicr
    assert stored_record["s3KeyRR"] == manifest_file.rr
    assert stored_record["isActionable"] is True

    emf_objects = [
        payload
        for line in capsys.readouterr().out.splitlines()
        if line.startswith("{") and "_aws" in (payload := json.loads(line))
    ]
    aggregate = next(item for item in emf_objects if "BatchDurationMs" in item)
    assert aggregate["ManifestsProcessed"] == [1.0]
    assert aggregate["ManifestsFailed"] == [0.0]
    assert aggregate["DocumentsProcessed"] == [1.0]
    assert aggregate["DocumentsFailed"] == [0.0]
    assert aggregate["ChangesTotal"] == [0.0]

    encounter = next(item for item in emf_objects if "EncountersProcessed" in item)
    assert encounter["encounter_type"] == "unknown"
    assert encounter["EncountersProcessed"] == [1.0]
    assert all("SectionChanges" not in item for item in emf_objects)

    document_log = next(
        record for record in caplog.records if record.message == "document_processed"
    )
    document_fields = vars(document_log)
    assert document_fields["version_number"] == 1
    assert document_fields["unique_condition_count"] == 0
    assert document_fields["persistence_id_with_index"] == f"{persistence_id}:0"
    assert eicr_set_id not in caplog.text
    assert all(record.message != "xml_change" for record in caplog.records)


def test_lambda_handler_identifies_each_manifest_entry_by_persistence_id_and_index(
    s3_client,
    bucket_name,
    dynamodb_table,
    caplog,
):
    from did_lambda.lambda_function import lambda_handler

    set_ids = ("first-eicr-set-id", "second-eicr-set-id")
    manifest_key, _manifest, persistence_id = send_input_files(
        s3_client,
        bucket_name=bucket_name,
        input_files=[
            MockS3InputFile(
                eicr_body=build_doc(1, set_id),
                rr_body=build_doc(1, f"rr-{set_id}"),
                set_id=set_id,
                version_number=1,
            )
            for set_id in set_ids
        ],
    )
    caplog.set_level("INFO")

    response = lambda_handler(
        {"Records": [build_sqs_record(bucket_name, manifest_key).raw_event]},
        None,
    )

    assert response == {"statusCode": 200, "message": "OK"}
    document_logs = [
        record for record in caplog.records if record.message == "document_processed"
    ]
    assert [vars(record)["persistence_id_with_index"] for record in document_logs] == [
        f"{persistence_id}:0",
        f"{persistence_id}:1",
    ]
    assert all(set_id not in caplog.text for set_id in set_ids)


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
    process_manifest_entry(bucket_name, persistence_id, manifest_file, 0)

    record = dynamodb_table.get_item(
        Key={"setId": eicr_set_id, "versionNumber": version_number}
    )["Item"]

    # dynamodb should have a record for our processed file
    assert record["s3Key"] == manifest_file.eicr
    assert record["s3KeyRR"] == manifest_file.rr
    assert record["s3KeyDiffOutput"] is None
    assert record["isActionable"] is True
    assert record["comparedToVersion"] is None

    # make sure the augmented eicr/rr were correctly put in DIDOutputV2/
    for fallback_basename, input_key in (
        ("eICR.xml", manifest_file.eicr),
        ("RR.xml", manifest_file.rr),
    ):
        output_key = get_did_output_key(
            root_prefix=OUTPUT_PREFIX,
            persistence_id=persistence_id,
            source_key=input_key,
            fallback_basename=fallback_basename,
        )
        response = s3_client.get_object(Bucket=bucket_name, Key=output_key)
        assert response["ResponseMetadata"]["HTTPStatusCode"] == 200


def test_process_sqs_record_with_eicr_diff(s3_client, bucket_name, dynamodb_table):
    from did_lambda.lambda_function import process_sqs_record
    from did_lambda.telemetry import BatchProcessingStats

    eicr_set_id = "eicr-set-id-1"
    rr_set_id = "rr-set-id-1"
    stats = BatchProcessingStats()

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
    process_sqs_record(build_sqs_record(bucket_name, manifest_key_1), stats)

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
    process_sqs_record(build_sqs_record(bucket_name, manifest_key_2), stats)

    assert stats.documents_processed == 2

    # ensure all files exist in DIDOutputV2
    for manifest, persistence_id in (
        (manifest_1, persistence_id_1),
        (manifest_2, persistence_id_2),
    ):
        assert len(manifest.files) == 1
        manifest_file = manifest.files[0]
        for fallback_basename, input_key in (
            ("eICR.xml", manifest_file.eicr),
            ("RR.xml", manifest_file.rr),
        ):
            output_key = get_did_output_key(
                root_prefix=OUTPUT_PREFIX,
                persistence_id=persistence_id,
                source_key=input_key,
                fallback_basename=fallback_basename,
            )
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
            Key=f"{COMPLETE_PREFIX}{persistence_id}",
        )
        assert response["ResponseMetadata"]["HTTPStatusCode"] == 200
