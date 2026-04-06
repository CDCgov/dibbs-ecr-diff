from aws_lambda_powertools.utilities.typing import LambdaContext


# TODO: use event source data class for event here
# https://docs.aws.amazon.com/powertools/python/latest/utilities/data_classes/
def lambda_handler(event: dict, context: LambdaContext) -> dict:
    """Main Lambda handler function."""
    try:
        return {
            "statusCode": 200,
            "message": "diff processed successfully",
        }
    except Exception as e:
        raise e
