"""DynamoDB operations for the Difference in Docs Lambda."""

import os
from typing import TYPE_CHECKING

import boto3
from boto3.dynamodb.conditions import Attr, Key

from did_lambda.utils import InfraError

from .models import EICRStorageRecord

if TYPE_CHECKING:
    from types_boto3_dynamodb import DynamoDBServiceResource

DYNAMODB_TABLE = os.environ.get("DYNAMODB_TABLE")

if not DYNAMODB_TABLE:
    raise InfraError("DYNAMODB_TABLE must be set")

dynamodb: "DynamoDBServiceResource" = boto3.resource("dynamodb")
db = dynamodb.Table(DYNAMODB_TABLE)


def get_before_actionable_record(
    set_id: str, version_number: int
) -> EICRStorageRecord | None:
    """Get the latest earlier actionable record for a set ID and version."""
    items = db.query(
        KeyConditionExpression=(
            Key("setId").eq(set_id) & Key("versionNumber").lt(version_number)
        ),
        FilterExpression=Attr("isActionable").eq(True),
        ScanIndexForward=False,
    )["Items"]

    return EICRStorageRecord.model_validate(items[0]) if items else None


def put_eicr_record(record: EICRStorageRecord) -> None:
    """Put an eICR record in DynamoDB."""
    db.put_item(Item=record.model_dump(mode="json"))
