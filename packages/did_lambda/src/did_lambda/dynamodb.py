"""DynamoDB operations for the Difference in Docs Lambda."""

import os
from typing import TYPE_CHECKING

import boto3
from boto3.dynamodb.conditions import Attr, Key
from pydantic import ValidationError

from .models import EICRStorageRecord
from .utils import ApplicationError, InfraError

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
    try:
        items = db.query(
            KeyConditionExpression=(
                Key("setId").eq(set_id) & Key("versionNumber").lt(version_number)
            ),
            FilterExpression=Attr("isActionable").eq(True),
            ScanIndexForward=False,
        )["Items"]
    except Exception as exc:
        raise InfraError("Unable to retrieve actionable record from DynamoDB") from exc

    try:
        return EICRStorageRecord.model_validate(items[0]) if items else None
    except ValidationError as exc:
        raise ApplicationError("Invalid EICRStorageRecord") from exc


def put_eicr_record(record: EICRStorageRecord) -> None:
    """Put an eICR record in DynamoDB."""
    item = record.model_dump(mode="json")
    try:
        db.put_item(Item=item)
    except Exception as exc:
        raise InfraError("Unable to write record to DynamoDB") from exc
