from types_boto3_s3 import S3Client

from e2e.helpers import Pair, Uploader


def test_happy_path(uploader: Uploader, s3: S3Client) -> None:
    """Happy path test case."""
    manifest = uploader.send_manifest("happy-path", [Pair(1), Pair(2), Pair(3)])

    did_complete_key = f"DIDCompleteV2/{manifest.persistence_id}"

    s3.get_waiter("object_exists").wait(
        Bucket=uploader.bucket_name,
        Key=did_complete_key,
        WaiterConfig={"Delay": 1, "MaxAttempts": 30},
    )

    response = s3.get_object(Bucket=uploader.bucket_name, Key=did_complete_key)

    assert response["ResponseMetadata"]["HTTPStatusCode"] == 200
