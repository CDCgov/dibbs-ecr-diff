import json
from pathlib import Path
from typing import Any

from e2e.helpers import send_input_files

ASSETS_DIR = Path(__file__).resolve().parent / "assets"
BUCKET_NAME = "ecr-dev-data-repository"
COMPLETE_PREFIX = "DIDCompleteV2/"
OUTPUT_PREFIX = "DIDOutputV2/"
PAIRS = (
    ("1_eICR.xml", "1_RR.xml"),
    ("2_eICR.xml", "2_RR.xml"),
    ("3_eICR.xml", "3_RR.xml"),
)


# uses s3 fixture
def test_happy_path(s3) -> None:
    # should automatically wait for the ecr-dev-data-repository to exist without me specifying in this test case, maybe can be before hook
    send_next = load_inputs(
        "assets/happy-path"
    )  # should go through assets/happy-path, collect


# def test_happy_path(s3: Any) -> None:
#     """Process each eICR/RR pair completely before uploading the next pair."""
#     # Wait for bucket to exist
#     # https://docs.aws.amazon.com/boto3/latest/reference/services/s3/waiter/BucketExists.html
#     s3.get_waiter("bucket_exists").wait(
#         Bucket=BUCKET_NAME,
#         WaiterConfig={"Delay": 1, "MaxAttempts": 60},
#     )

#     for version_number, (eicr_name, rr_name) in enumerate(PAIRS, start=1):
#         _manifest_key, input_manifest, persistence_id = send_input_files(
#             s3,
#             BUCKET_NAME,
#             ASSETS_DIR / eicr_name,
#             ASSETS_DIR / rr_name,
#         )

#         complete_key = f"{COMPLETE_PREFIX}{persistence_id}"
#         s3.get_waiter("object_exists").wait(
#             Bucket=BUCKET_NAME,
#             Key=complete_key,
#             WaiterConfig={"Delay": 1, "MaxAttempts": 60},
#         )
#         complete_manifest = json.loads(
#             s3.get_object(Bucket=BUCKET_NAME, Key=complete_key)["Body"].read()
#         )

#         output_path = f"{OUTPUT_PREFIX}{persistence_id}/SDDH/COVID19"
#         eicr_output_key = f"{output_path}/{eicr_name}"
#         rr_output_key = f"{output_path}/{rr_name}"
#         diff_output_key = (
#             None
#             if version_number == 1
#             else f"{output_path}/diff_v{version_number - 1}_to_v{version_number}_0.json"
#         )
#         input_file = input_manifest["Files"][0]
#         assert complete_manifest == {
#             "Files": [
#                 {
#                     "eicr": eicr_output_key,
#                     "rr": rr_output_key,
#                     "setId": input_file["setId"],
#                     "versionNumber": version_number,
#                     "eicr_diff_output": diff_output_key,
#                     "is_actionable": version_number != 3,
#                 }
#             ]
#         }

#         output_keys = [eicr_output_key, rr_output_key]
#         if diff_output_key:
#             output_keys.append(diff_output_key)
#         for output_key in output_keys:
#             s3.head_object(Bucket=BUCKET_NAME, Key=output_key)
