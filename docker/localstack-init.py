#!/usr/bin/env python3

# This script is run as a localstack init hook (specified in compose.yml)
# This initializes localstack to resemble our Prod environment as closely as possible
# https://docs.localstack.cloud/aws/customization/advanced/initialization-hooks/

import json
import os

import boto3

AWS_ENDPOINT_URL = os.getenv("AWS_ENDPOINT_URL", "http://localstack:4566")
AWS_ACCESS_KEY_ID = os.getenv("AWS_ACCESS_KEY_ID", "test")
AWS_SECRET_ACCESS_KEY = os.getenv("AWS_SECRET_ACCESS_KEY", "test")
AWS_DEFAULT_REGION = os.getenv("AWS_DEFAULT_REGION", "us-east-1")

INPUT_BUCKET = "ecr-dev-data-repository"
DID_INPUT_PREFIX = "DIDInput/"

EVENT_RULE_NAME = "ecr-dev-did-input-event"
QUEUE_NAME = "ecr-dev-did-input"
TABLE_NAME = "did-eicr-record"

client_options = {
    "endpoint_url": AWS_ENDPOINT_URL,
    "region_name": AWS_DEFAULT_REGION,
    "aws_access_key_id": AWS_ACCESS_KEY_ID,
    "aws_secret_access_key": AWS_SECRET_ACCESS_KEY,
}

s3 = boto3.client("s3", **client_options)
sqs = boto3.client("sqs", **client_options)
event_bridge = boto3.client("events", **client_options)
dynamodb = boto3.client("dynamodb", **client_options)

# create S3 bucket
# https://docs.aws.amazon.com/boto3/latest/guide/s3-example-creating-buckets.html
existing_buckets = {bucket["Name"] for bucket in s3.list_buckets()["Buckets"]}

if INPUT_BUCKET not in existing_buckets:
    s3.create_bucket(Bucket=INPUT_BUCKET)

# create SQS queue that receives events from EventBridge
queue_url = sqs.create_queue(QueueName=QUEUE_NAME)["QueueUrl"]
queue_arn = sqs.get_queue_attributes(
    QueueUrl=queue_url,
    AttributeNames=["QueueArn"],
)["Attributes"]["QueueArn"]

# create EventBridge rule that matches PUTs in the S3 bucket under DIDInput/.
events_rule_arn = event_bridge.put_rule(
    Name=EVENT_RULE_NAME,
    EventPattern=json.dumps(
        {
            "source": ["aws.s3"],
            "detail-type": ["Object Created"],
            "detail": {
                "bucket": {"name": [INPUT_BUCKET]},
                "object": {"key": [{"prefix": DID_INPUT_PREFIX}]},
                "reason": ["PutObject"],
            },
        }
    ),
)

# allow our new EventBridge rule to place messages on the SQS queue
queue_policy = {
    "Version": "2012-10-17",
    "Id": "S3NotificationQueuePolicy",
    "Statement": [
        {
            "Sid": "AllowEventBridgeToSendMessages",
            "Effect": "Allow",
            "Principal": {"Service": "events.amazonaws.com"},
            "Action": ["SQS:SendMessage"],
            "Resource": queue_arn,
            "Condition": {"ArnEquals": {"aws:SourceArn": events_rule_arn}},
        }
    ],
}

# set the permission policy above on the SQS queue
sqs.set_queue_attributes(
    QueueUrl=queue_url,
    Attributes={"Policy": json.dumps(queue_policy)},
)

# set the SQS queue as our EventBridge rule's target
event_bridge.put_targets(
    Rule=EVENT_RULE_NAME, Targets=[{"Id": "SendToEcrDevDIDInput", "Arn": queue_arn}]
)

# configure our s3 bucket to send bucket events to EventBridge
# https://docs.aws.amazon.com/AmazonS3/latest/userguide/enable-event-notifications-eventbridge.html
s3.put_bucket_notification_configuration(
    Bucket=INPUT_BUCKET, NotificationConfiguration={"EventBridgeConfiguration": {}}
)

# configure cors to allow uploader to communicate with localstack
cors_configuration = {
    "CORSRules": [
        {
            "AllowedHeaders": ["*"],
            "AllowedMethods": ["GET", "PUT"],
            "AllowedOrigins": ["*"],
            "ExposeHeaders": ["ETag", "x-amz-request-id"],
            "MaxAgeSeconds": 3000,
        }
    ]
}
s3.put_bucket_cors(Bucket=INPUT_BUCKET, CORSConfiguration=cors_configuration)

# create DynamoDB table
# see: docs/Storage-Architecture.md
try:
    dynamodb.describe_table(TableName=TABLE_NAME)
except dynamodb.exceptions.ResourceNotFoundException:
    # if doesn't exist, create the table
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
        BillingMode="PAY_PER_REQUEST",
    )

print("localstack initialization complete")
