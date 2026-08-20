"""Models for S3 manifest files."""

from datetime import datetime

from pydantic import BaseModel, Field


class DIDInputFile(BaseModel):
    """Input EICR and RR S3 keys, and their setId and versionNumber."""

    eicr: str
    rr: str
    originalRr: str | None = None
    setId: str
    versionNumber: int
    jurisdictions: list[str]


class DIDOutputFile(BaseModel):
    """Output EICR, RR, DiffOutput S3 keys, and related metadata."""

    eicr: str | None = None
    rr: str
    setId: str
    versionNumber: int
    jurisdictions: list[str]
    eicr_diff_output: str | None = None
    is_actionable: bool


class DIDInputManifest(BaseModel):
    """A manifest containing DIDInput files to process."""

    files: list[DIDInputFile] = Field(alias="Files")


class DIDCompleteManifest(BaseModel):
    """A manifest containing DIDOutput files."""

    files: list[DIDOutputFile] = Field(alias="Files")


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
