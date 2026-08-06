import pytest
from did_lambda.utils import InfraError


def test_get_object(s3_client, s3_module, bucket_name):
    s3_client.put_object(Bucket=bucket_name, Key="foo.txt", Body=b"hello")

    assert s3_module.get_object(bucket_name, "foo.txt") == b"hello"


def test_get_object_raises_with_nonexistent_object(s3_module, bucket_name):
    with pytest.raises(InfraError):
        s3_module.get_object(bucket_name, "does_not_exist.txt")
