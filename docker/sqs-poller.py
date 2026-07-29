#!/usr/bin/env -S uv run
# /// script
# dependencies = ["boto3>=1.43.46", "httpx>=0.28.1"]
# ///

# This is a minimal SQS poller used in local dev environments to:
# 1. receive messages from the localstack SQS queue
# 2. invoke the lambda function
# 3. delete the message from the queue upon successful invocation of lambda

import os
import time

import boto3
import httpx

AWS_ENDPOINT_URL = os.getenv("AWS_ENDPOINT_URL", "http://localstack:4566")
AWS_ACCESS_KEY_ID = os.getenv("AWS_ACCESS_KEY_ID", "test")
AWS_SECRET_ACCESS_KEY = os.getenv("AWS_SECRET_ACCESS_KEY", "test")
AWS_DEFAULT_REGION = os.getenv("AWS_DEFAULT_REGION", "us-east-1")

QUEUE_URL = os.getenv("QUEUE_URL")
LAMBDA_URL = os.getenv("LAMBDA_URL")

# 1. wait until localstack is ready to receive requests
while True:
    try:
        response = httpx.get(f"{AWS_ENDPOINT_URL}/_localstack/init", timeout=2)
        completed = response.json().get("completed")

        if completed.get("READY") or completed.get("ready"):
            print("localstack ready for requests")
            break
    except (httpx.HTTPError, ValueError):
        pass

    print("waiting for localstack...", flush=True)
    time.sleep(2)

# 2. initiate sqs client
sqs = boto3.client(
    "sqs",
    endpoint_url=AWS_ENDPOINT_URL,
    region_name=AWS_DEFAULT_REGION,
    aws_access_key_id=AWS_ACCESS_KEY_ID,
    aws_secret_access_key=AWS_SECRET_ACCESS_KEY,
)

queue_attributes = sqs.get_queue_attributes(
    QueueUrl=QUEUE_URL,
    AttributeNames=["QueueArn"],
)

QUEUE_ARN = queue_attributes["Attributes"]["QueueArn"]

# 3. poll for sqs messages
while True:
    response = sqs.receive_message(
        QueueUrl=QUEUE_URL,
        MaxNumberOfMessages=1,
        WaitTimeSeconds=10,  # wait 10 seconds before returning
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
                    "eventSourceARN": QUEUE_ARN,
                    "awsRegion": AWS_DEFAULT_REGION,
                }
            ]
        }

        # invoke lambda & raise exception in case of non-200 response
        # raising prevents us from deleting the message in case the lambda failed
        httpx.post(LAMBDA_URL, json=event, timeout=30).raise_for_status()

        # delete message
        sqs.delete_message(
            QueueUrl=QUEUE_URL,
            ReceiptHandle=message["ReceiptHandle"],
        )

        print(f"processed {message['MessageId']}", flush=True)

    # sleep for 1 second, then check queue again
    time.sleep(1)
