#!/usr/bin/env -S uv run
# /// script
# dependencies = ["boto3>=1.43.46", "httpx>=0.28.1"]
# ///

import os
import time

import boto3
import httpx

AWS_ENDPOINT_URL = os.getenv("AWS_ENDPOINT_URL", "http://localstack:4566")
AWS_ACCESS_KEY_ID = os.getenv("AWS_ACCESS_KEY_ID", "test")
AWS_SECRET_ACCESS_KEY = os.getenv("AWS_SECRET_ACCESS_KEY", "test")
REGION = os.getenv("AWS_DEFAULT_REGION", "us-east-1")
QUEUE_URL = os.getenv(
    "QUEUE_URL", "http://localstack:4566/000000000000/did-eicr-events"
)
LAMBDA_URL = os.getenv(
    "LAMBDA_URL", "http://lambda:8080/2015-03-31/functions/function/invocations"
)

sqs = boto3.client(
    "sqs",
    endpoint_url=AWS_ENDPOINT_URL,
    region_name=REGION,
    aws_access_key_id=AWS_ACCESS_KEY_ID,
    aws_secret_access_key=AWS_SECRET_ACCESS_KEY,
)

while True:
    response = sqs.receive_message(
        QueueUrl=QUEUE_URL,
        MaxNumberOfMessages=1,
        WaitTimeSeconds=10,
        MessageAttributeNames=["All"],
        AttributeNames=["All"],
    )

    for message in response.get("Messages", []):
        event = {
            "Records": [
                {
                    "messageId": message["MessageId"],
                    "receiptHandle": message["ReceiptHandle"],
                    "body": message["Body"],
                    "attributes": message.get("Attributes", {}),
                    "messageAttributes": message.get("MessageAttributes", {}),
                    "md5OfBody": message.get("MD5OfBody"),
                    "eventSource": "aws:sqs",
                    "eventSourceARN": os.getenv("QUEUE_ARN", ""),
                    "awsRegion": REGION,
                }
            ]
        }

        httpx.post(LAMBDA_URL, json=event, timeout=30).raise_for_status()

        sqs.delete_message(
            QueueUrl=QUEUE_URL,
            ReceiptHandle=message["ReceiptHandle"],
        )

        print(f"processed {message['MessageId']}", flush=True)

    # sleep for 1 second, then check queue again
    time.sleep(1)
