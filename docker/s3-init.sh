#!/usr/bin/env bash
set -euo pipefail

# this script is run as a LocalStack init hook (specified in compose.yml)
# see: https://docs.localstack.cloud/aws/customization/advanced/initialization-hooks/

INPUT_BUCKET="did-eicr-bucket"
DIFF_BUCKET="did-diff-bucket"
QUEUE_NAME="did-eicr-events"

export AWS_ACCESS_KEY_ID="${AWS_ACCESS_KEY_ID:-test}"
export AWS_SECRET_ACCESS_KEY="${AWS_SECRET_ACCESS_KEY:-test}"
export AWS_DEFAULT_REGION="${AWS_DEFAULT_REGION:-"us-east-1"}"

# create S3 buckets
# https://docs.aws.amazon.com/cli/latest/userguide/cli_s3_code_examples.html
for bucket in "${INPUT_BUCKET}" "${DIFF_BUCKET}"; do
  if ! awslocal s3api head-bucket --bucket "${bucket}" >/dev/null 2>&1; then
    awslocal s3api create-bucket --bucket "${bucket}"
  fi
done

# create SQS queue for "did-eicr-bucket"
# https://docs.aws.amazon.com/cli/latest/userguide/cli_sqs_code_examples.html

if awslocal sqs get-queue-url --queue-name "${QUEUE_NAME}" >/dev/null 2>&1; then
  # if the queue already exists, grab the queue url
  QUEUE_URL="$(
    awslocal sqs get-queue-url \
      --queue-name "${QUEUE_NAME}" \
      --query QueueUrl \
      --output text
  )"
else
  # else create it, and return queue url
  QUEUE_URL="$(
    awslocal sqs create-queue \
      --queue-name "${QUEUE_NAME}" \
      --query QueueUrl \
      --output text
  )"
fi

QUEUE_ARN="$(
  awslocal sqs get-queue-attributes \
    --queue-url "${QUEUE_URL}" \
    --attribute-names QueueArn \
    --query "Attributes.QueueArn" \
    --output text
)"

# set SQS policy allowing S3 to publish events:
# https://docs.aws.amazon.com/AmazonS3/latest/userguide/grant-destinations-permissions-to-s3.html
POLICY="$(
  cat <<EOF
{
  "Version": "2012-10-17",
  "Id": "S3NotificationQueuePolicy",
  "Statement": [
    {
      "Sid": "AllowS3ToSendMessages",
      "Effect": "Allow",
      "Principal": {
        "Service": "s3.amazonaws.com"
      },
      "Action": [
        "SQS:SendMessage"
      ],
      "Resource": "${QUEUE_ARN}",
      "Condition": {
        "ArnLike": {
          "aws:SourceArn": "arn:aws:s3:::${INPUT_BUCKET}"
        },
        "StringEquals": {
          "aws:SourceAccount": "000000000000"
        }
      }
    }
  ]
}
EOF
)"

# escape the policy JSON; localstack image includes python but not jq
# so we'll use python to read from standard input, and save the escaped JSON string
ESCAPED_POLICY="$(printf '%s' "${POLICY}" | python3 -c 'import json,sys; print(json.dumps(sys.stdin.read()))')"

ATTRIBUTES_FILE="/tmp/sqs-attributes.json"
cat >"${ATTRIBUTES_FILE}" <<EOF
{"Policy": ${ESCAPED_POLICY}}
EOF

awslocal sqs set-queue-attributes \
  --queue-url "${QUEUE_URL}" \
  --attributes "file://${ATTRIBUTES_FILE}"

# set configuration that specifies: when s3 objects are created, send to SQS
# https://docs.aws.amazon.com/AmazonS3/latest/API/API_QueueConfiguration.html
NOTIFICATION_CONFIGURATION="$(
  cat <<EOF
{
  "QueueConfigurations": [
    {
      "Id": "SendObjectCreatedEventsToSqs",
      "QueueArn": "${QUEUE_ARN}",
      "Events": [
        "s3:ObjectCreated:*"
      ]
    }
  ]
}
EOF
)"

awslocal s3api put-bucket-notification-configuration \
  --bucket "${INPUT_BUCKET}" \
  --notification-configuration "${NOTIFICATION_CONFIGURATION}"

echo "S3 + SQS Intitialization Complete."
