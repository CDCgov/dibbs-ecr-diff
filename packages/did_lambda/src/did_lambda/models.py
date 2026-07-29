"""Models for S3 manifest files."""

from datetime import datetime

from pydantic import BaseModel, Field


class DIDInputRecord(BaseModel):
    """An eICR and its Reportability Response S3 keys."""

    eicr: str
    rr: str | None = None
    setId: str
    versionNumber: int


class DIDOutputRecord(DIDInputRecord):
    """An eICR and its Reportability Response DID output S3 keys."""

    eicr_diff_output: str | None = None
    is_actionable: bool


class DIDInputManifest(BaseModel):
    """A manifest containing files to process."""

    files: list[DIDInputRecord] = Field(alias="Files")


class DIDCompleteManifest(BaseModel):
    """A manifest containing DIDOutput files."""

    files: list[DIDOutputRecord] = Field(alias="Files")


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
