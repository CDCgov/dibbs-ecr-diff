#!/usr/bin/env python3

# this script is run as a localstack init hook (specified in compose.yml)
# see: https://docs.localstack.cloud/aws/customization/advanced/initialization-hooks/

import json
import os

import boto3

AWS_ENDPOINT_URL = os.getenv("AWS_ENDPOINT_URL", "http://localstack:4566")
AWS_ACCESS_KEY_ID = os.getenv("AWS_ACCESS_KEY_ID", "test")
AWS_SECRET_ACCESS_KEY = os.getenv("AWS_SECRET_ACCESS_KEY", "test")
AWS_DEFAULT_REGION = os.getenv("AWS_DEFAULT_REGION", "us-east-1")

INPUT_BUCKET = "did-eicr-bucket"
DIFF_BUCKET = "did-diff-bucket"
MANIFEST_PATH = "DIDInput"

QUEUE_NAME = "did-eicr-events"
TABLE_NAME = "did-eicr-record"

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

# enable cors on the input bucket to allow a local client to upload
# https://docs.localstack.cloud/aws/services/s3/#configuring-cross-origin-resource-sharing-on-s3
# https://docs.aws.amazon.com/boto3/latest/reference/services/s3/client/put_bucket_cors.html
s3.put_bucket_cors(
    Bucket=INPUT_BUCKET,
    CORSConfiguration={
        "CORSRules": [
            {
                "AllowedHeaders": ["*"],
                "AllowedMethods": ["GET", "POST", "PUT"],
                "AllowedOrigins": ["http://localhost:3000"],
                "ExposeHeaders": ["ETag"],
            }
        ]
    },
)

# create SQS queue for the eICR S3 bucket
# https://docs.aws.amazon.com/boto3/latest/guide/sqs.html#creating-a-queue
queue_url = sqs.create_queue(QueueName=QUEUE_NAME)["QueueUrl"]
queue_arn = sqs.get_queue_attributes(
    QueueUrl=queue_url,
    AttributeNames=["QueueArn"],
)["Attributes"]["QueueArn"]

# set up queue to allow the eICR S3 bucket to send messages
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

# set configuration that specifies: when .json files are PUT in the manifest path, send to SQS
# see: https://docs.aws.amazon.com/AmazonS3/latest/API/API_QueueConfiguration.html
s3.put_bucket_notification_configuration(
    Bucket=INPUT_BUCKET,
    NotificationConfiguration={
        "QueueConfigurations": [
            {
                "Id": "SendObjectCreatedEventsToSqs",
                "QueueArn": queue_arn,
                "Events": ["s3:ObjectCreated:Put"],
                "Filter": {
                    "Key": {
                        "FilterRules": [
                            {"Name": "prefix", "Value": f"{MANIFEST_PATH}/"},
                            {"Name": "suffix", "Value": ".json"},
                        ]
                    }
                },
            }
        ]
    },
)

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
