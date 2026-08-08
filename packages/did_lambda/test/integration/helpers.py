import json
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import uuid4

from aws_lambda_powertools.utilities.data_classes import SQSRecord
from did_lambda.models import DIDInputFile, DIDInputManifest


@dataclass
class MockS3InputFile:
    eicr_body: bytes
    rr_body: bytes
    set_id: str
    version_number: int


def build_persistence_id() -> str:
    return f"{datetime.now(UTC):%Y/%m/%d}/{uuid4()}"


def build_doc(version_number: int, set_id: str, body: str = "") -> bytes:
    return f"""
      <ClinicalDocument xmlns="urn:hl7-org:v3">
        <id root="{uuid4()}"/>
        <effectiveTime value="20201107094421-0500" />
        <setId root="{set_id}"/>
        <versionNumber value="{version_number}"/>
        {body}
      </ClinicalDocument>
    """.encode()


def build_sqs_record(bucket_name: str, manifest_key: str) -> SQSRecord:
    return SQSRecord(
        {
            "body": json.dumps(
                {
                    "detail": {
                        "bucket": {"name": bucket_name},
                        "object": {"key": manifest_key},
                    }
                }
            )
        }
    )


def send_input_files(
    s3_client,
    bucket_name: str,
    input_files: list[MockS3InputFile],
) -> tuple[str, DIDInputManifest, str]:
    persistence_id = build_persistence_id()
    manifest_files = []

    for index, input_file in enumerate(input_files):
        base_key = f"RefinerOutputV2/{persistence_id}/SDDH/CONDITION-{index}"
        eicr_key = f"{base_key}/{index}-eicr.xml"
        rr_key = f"{base_key}/{index}-rr.xml"

        s3_client.put_object(
            Bucket=bucket_name, Key=eicr_key, Body=input_file.eicr_body
        )
        s3_client.put_object(Bucket=bucket_name, Key=rr_key, Body=input_file.rr_body)

        manifest_files.append(
            DIDInputFile(
                eicr=eicr_key,
                rr=rr_key,
                setId=input_file.set_id,
                versionNumber=input_file.version_number,
                jurisdictions=["SDDH"],
            )
        )

    manifest = DIDInputManifest(Files=manifest_files)
    manifest_key = f"DIDInput/{persistence_id}"
    s3_client.put_object(
        Bucket=bucket_name,
        Key=manifest_key,
        Body=manifest.model_dump_json(by_alias=True).encode(),
    )

    return manifest_key, manifest, persistence_id
