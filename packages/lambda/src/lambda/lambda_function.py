from aws_lambda_powertools import Logger
from aws_lambda_powertools.utilities.typing import LambdaContext

logger = Logger(service="difference-in-docs")


# TODO: use event source data class for event here
# https://docs.aws.amazon.com/powertools/python/latest/utilities/data_classes/
def lambda_handler(event: dict, context: LambdaContext) -> dict:
    """Main Lambda handler function."""
    try:
        logger.info("hello world")
        return {
            "statusCode": 200,
            "message": "diff processed successfully",
        }
    except Exception as e:
        raise e
