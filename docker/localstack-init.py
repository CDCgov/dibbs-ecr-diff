#!/usr/bin/env python3

# this script is run as a LocalStack init hook (specified in compose.yml)
# see: https://docs.localstack.cloud/aws/customization/advanced/initialization-hooks/

import json
import os

import boto3

INPUT_BUCKET = "did-eicr-bucket"
DIFF_BUCKET = "did-diff-bucket"

QUEUE_NAME = "did-eicr-events"
TABLE_NAME = "did-eicr-record"

AWS_ENDPOINT_URL = os.getenv("AWS_ENDPOINT_URL")
AWS_DEFAULT_REGION = os.getenv("AWS_DEFAULT_REGION")
AWS_ACCESS_KEY_ID = os.getenv("AWS_ACCESS_KEY_ID")
AWS_SECRET_ACCESS_KEY = os.getenv("AWS_SECRET_ACCESS_KEY")

client_options = {
    "endpoint_url": AWS_ENDPOINT_URL,
    "region_name": AWS_DEFAULT_REGION,
    "aws_access_key_id": AWS_ACCESS_KEY_ID,
    "aws_secret_access_key": AWS_SECRET_ACCESS_KEY,
}

s3 = boto3.client("s3", **client_options)
sqs = boto3.client("sqs", **client_options)
dynamodb = boto3.client("dynamodb", **client_options)

# create S3 buckets
# https://docs.aws.amazon.com/boto3/latest/guide/s3-example-creating-buckets.html
existing_buckets = {bucket["Name"] for bucket in s3.list_buckets()["Buckets"]}

for bucket in (INPUT_BUCKET, DIFF_BUCKET):
    if bucket not in existing_buckets:
        s3.create_bucket(Bucket=bucket)

# create SQS queue for "did-eicr-bucket"
# https://docs.aws.amazon.com/boto3/latest/guide/sqs.html#creating-a-queue
queue_url = sqs.create_queue(QueueName=QUEUE_NAME)["QueueUrl"]
queue_arn = sqs.get_queue_attributes(
    QueueUrl=queue_url,
    AttributeNames=["QueueArn"],
)["Attributes"]["QueueArn"]

# set up queue to allow `did-eicr-bucket` to send messages
queue_policy = {
    "Version": "2012-10-17",
    "Id": "S3NotificationQueuePolicy",
    "Statement": [
        {
            "Sid": "AllowS3ToSendMessages",
            "Effect": "Allow",
            "Principal": {"Service": "s3.amazonaws.com"},
            "Action": ["SQS:SendMessage"],
            "Resource": queue_arn,
            "Condition": {
                "ArnLike": {
                    "aws:SourceArn": f"arn:aws:s3:::{INPUT_BUCKET}",
                },
                "StringEquals": {"aws:SourceAccount": "000000000000"},
            },
        }
    ],
}

sqs.set_queue_attributes(
    QueueUrl=queue_url,
    Attributes={"Policy": json.dumps(queue_policy)},
)

# set configuration that specifies: when s3 objects are created, send to SQS
# https://docs.aws.amazon.com/AmazonS3/latest/API/API_QueueConfiguration.html
s3.put_bucket_notification_configuration(
    Bucket=INPUT_BUCKET,
    NotificationConfiguration={
        "QueueConfigurations": [
            {
                "Id": "SendObjectCreatedEventsToSqs",
                "QueueArn": queue_arn,
                "Events": ["s3:ObjectCreated:*"],
            }
        ]
    },
)

# create `did-eicr-record` table
try:
    dynamodb.describe_table(TableName=TABLE_NAME)
except dynamodb.exceptions.ResourceNotFoundException:
    dynamodb.create_table(
        TableName=TABLE_NAME,
        AttributeDefinitions=[
            {"AttributeName": "setId", "AttributeType": "S"},
            {"AttributeName": "versionNumber", "AttributeType": "N"},
        ],
        KeySchema=[
            {"AttributeName": "setId", "KeyType": "HASH"},
            {"AttributeName": "versionNumber", "KeyType": "RANGE"},
        ],
        # set to PAY_PER_REQUEST to avoid setting read/write capacity for local environment/testing
        # see: https://docs.aws.amazon.com/amazondynamodb/latest/APIReference/API_BillingModeSummary.html
        BillingMode="PAY_PER_REQUEST",
    )

print("localstack initialization complete")
