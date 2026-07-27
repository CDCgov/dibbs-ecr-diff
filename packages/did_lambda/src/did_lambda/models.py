"""Models for S3 manifest files."""

from datetime import datetime

from pydantic import BaseModel, Field


class ManifestRecord(BaseModel):
    """An eICR and its Reportability Response S3 keys."""

    eicr: str
    rr: str | None = None
    setId: str
    versionNumber: int


class Manifest(BaseModel):
    """A manifest containing files to process."""

    files: list[ManifestRecord] = Field(alias="Files")


class DIDOutputRecord(ManifestRecord):
    """An eICR and its Reportability Response DID output S3 keys."""

    eicr_diff_output: str | None = None
    rr_diff_output: str | None = None  # are we diffing the RR?


class EICRStorageRecord(BaseModel):
    """DynamoDB table record."""

    setId: str
    versionNumber: int
    s3Key: str
    s3KeyRR: str | None = None
    s3KeyDiffOutput: str | None = None
    processedAt: datetime
    isActionable: bool
    comparedToVersion: int | None = None
