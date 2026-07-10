#!/usr/bin/env bash
set -euo pipefail

# this script is run as a LocalStack init hook (specified in compose.yml)
# see: https://docs.localstack.cloud/aws/customization/advanced/initialization-hooks/

TABLE_NAME="did-eicr-record"

export AWS_ACCESS_KEY_ID="${AWS_ACCESS_KEY_ID:-test}"
export AWS_SECRET_ACCESS_KEY="${AWS_SECRET_ACCESS_KEY:-test}"
export AWS_DEFAULT_REGION="${AWS_DEFAULT_REGION:-us-east-1}"

# DynamoDB table creation
# https://docs.aws.amazon.com/cli/latest/userguide/cli_dynamodb_code_examples.html
if ! awslocal dynamodb describe-table --table-name "${TABLE_NAME}" >/dev/null 2>&1; then
  awslocal dynamodb create-table \
    --table-name "${TABLE_NAME}" \
    --attribute-definitions \
    AttributeName=setId,AttributeType=S \
    AttributeName=versionNumber,AttributeType=N \
    --key-schema \
    AttributeName=setId,KeyType=HASH \
    AttributeName=versionNumber,KeyType=RANGE \
    --billing-mode PAY_PER_REQUEST \
    >/dev/null
fi

echo "DynamoDB Intitialization Complete."
