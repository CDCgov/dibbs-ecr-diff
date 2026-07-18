"""Ingest manifests delivered through S3 and SQS."""

# import re
# from importlib import import_module
# from typing import Any, Protocol, cast
from urllib.parse import unquote_plus

import boto3
from aws_lambda_powertools.utilities.data_classes import SQSEvent, event_source
from aws_lambda_powertools.utilities.typing import LambdaContext

# from .models import Manifest

# MANIFEST_KEY_PATTERN = re.compile(r"DIDInput/[^/]+/[^/]+\.json")


# class StreamingBody(Protocol):
#     """Readable body returned by S3."""

#     def read(self) -> bytes:
#         """Read the complete object body."""
#         ...


# class S3Client(Protocol):
#     """S3 operations needed by manifest ingestion."""

#     def get_object(self, *, Bucket: str, Key: str) -> dict[str, Any]:
#         """Get an object from S3."""
#         ...


# def _get_s3_client() -> S3Client:
#     return cast(S3Client, import_module("boto3").client("s3"))


# def _read_object(s3: S3Client, bucket: str, key: str) -> bytes:
#     response = s3.get_object(Bucket=bucket, Key=key)
#     body = cast(StreamingBody, response["Body"])
#     return body.read()


# def _process_manifest(s3: S3Client, bucket: str, key: str) -> int:
#     if MANIFEST_KEY_PATTERN.fullmatch(key) is None:
#         msg = f"Invalid manifest key: {key}"
#         raise ValueError(msg)

#     manifest = Manifest.model_validate_json(_read_object(s3, bucket, key))

#     for manifest_file in manifest.files:
#         _read_object(s3, bucket, manifest_file.eicr)
#         if manifest_file.rr is not None:
#             _read_object(s3, bucket, manifest_file.rr)

#     return len(manifest.files)

s3 = boto3.client("s3")


@event_source(data_class=SQSEvent)
def lambda_handler(event: SQSEvent, context: LambdaContext):
    """Download manifests and the XML objects they reference."""
    for sqs_record in event.records:
        message = sqs_record.json_body

        # skip processing any test events
        if isinstance(message, dict) and message.get("Event") == "s3:TestEvent":
            continue

        for s3_record in sqs_record.decoded_nested_s3_event.records:
            bucket = s3_record.s3.bucket.name
            key = unquote_plus(s3_record.s3.get_object.key)
            print(key)
            print(bucket)
            # processed_files += _process_manifest(s3, bucket, key)
            # processed_manifests += 1

    # return {
    #     "processedManifests": processed_manifests,
    #     "processedFiles": processed_files,
    # }
    return {
        "statusCode": 200,
        "message": "diff processed successfully",
    }
