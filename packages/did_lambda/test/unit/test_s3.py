import traceback
from unittest.mock import Mock

import pytest
from did_lambda.utils import InfraError


def test_put_object_sanitizes_failure(s3_module, monkeypatch):
    sensitive_bucket = "sensitive-aphl-bucket"
    sensitive_key = "sensitive/eICR.xml"
    sensitive_failure = "some secret credentials or PII were rejected"

    # make the underlying S3 client fail with sensitive error text
    monkeypatch.setattr(
        s3_module.s3,
        "put_object",
        Mock(side_effect=RuntimeError(sensitive_failure)),
    )

    with pytest.raises(InfraError) as exc:
        s3_module.put_object(sensitive_bucket, sensitive_key, b"sensitive document")

    # join traceback list to a single string
    formatted_traceback = "".join(traceback.format_exception(exc.value))

    # verify that whatever caller caused the exception should NOT see PII in the exception
    assert str(exc.value) == "S3 put_object failed"

    # assert none of the sensitive values are a substring in the traceback text
    for val in (sensitive_bucket, sensitive_key, sensitive_failure):
        assert val not in formatted_traceback
