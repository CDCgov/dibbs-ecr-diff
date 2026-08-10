import pytest
from did_lambda.utils import InfraError
from lxml import etree


def test_get_object(s3_client, s3_module, bucket_name):
    s3_client.put_object(Bucket=bucket_name, Key="foo.txt", Body=b"hello")

    assert s3_module.get_object(bucket_name, "foo.txt") == b"hello"


def test_get_object_raises_with_nonexistent_object(s3_module, bucket_name):
    with pytest.raises(InfraError):
        s3_module.get_object(bucket_name, "does_not_exist.txt")


def test_put_object(s3_client, s3_module, bucket_name):
    s3_module.put_object(bucket_name, "foo.txt", b"hello")

    body = s3_client.get_object(Bucket=bucket_name, Key="foo.txt")["Body"]
    assert body.read() == b"hello"


def test_put_object_raises_for_nonexistent_bucket(s3_module):
    with pytest.raises(InfraError):
        s3_module.put_object("nonexistent-bucket", "foo.txt", b"hello")


def test_get_object_xml_tree_returns_etree(s3_client, s3_module, bucket_name):
    key = "DIDInput/eicr.xml"

    s3_client.put_object(
        Bucket=bucket_name,
        Key=key,
        Body=b"<ClinicalDocument>foobar</ClinicalDocument>",
    )

    tree = s3_module.get_object_xml_tree(bucket_name, key)

    assert isinstance(tree, etree._ElementTree)
    assert tree.getroot().tag == "ClinicalDocument"
    assert tree.getroot().text == "foobar"
