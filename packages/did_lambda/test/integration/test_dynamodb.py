SET_ID = "some-set-id"


def record(version_number, is_actionable):
    return {
        "setId": SET_ID,
        "versionNumber": version_number,
        "s3Key": f"eicr-{version_number}.xml",
        "s3KeyRR": f"rr-{version_number}.xml",
        "processedAt": "2026-01-01T00:00:00Z",
        "isActionable": is_actionable,
        "comparedToVersion": None,
    }


def test_get_before_actionable_record_returns_latest_earlier_actionable_record(
    dynamodb_table, dynamodb_module
):
    dynamodb_table.put_item(Item=record(1, True))
    dynamodb_table.put_item(Item=record(2, True))
    dynamodb_table.put_item(Item=record(3, False))

    result = dynamodb_module.get_before_actionable_record(SET_ID, 4)

    assert result is not None
    assert result.versionNumber == 2


def test_get_before_actionable_record_returns_none_when_none_exists(
    dynamodb_table, dynamodb_module
):
    result = dynamodb_module.get_before_actionable_record(SET_ID, 1)
    assert result is None
