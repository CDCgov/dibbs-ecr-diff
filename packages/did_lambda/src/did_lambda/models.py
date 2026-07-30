"""Models for S3 manifest files."""

from pydantic import BaseModel, Field


class DIDInputRecord(BaseModel):
    """Input EICR and RR S3 keys, and their setId and versionNumber."""

    eicr: str
    rr: str
    setId: str
    versionNumber: int


class DIDOutputRecord(DIDInputRecord):
    """Output EICR, RR, DiffOutput S3 keys, and related metadata."""

    eicr_diff_output: str | None = None
    is_actionable: bool


class DIDInputManifest(BaseModel):
    """A manifest containing DIDInput files to process."""

    files: list[DIDInputRecord] = Field(alias="Files")


class DIDCompleteManifest(BaseModel):
    """A manifest containing DIDOutput files."""

    files: list[DIDOutputRecord] = Field(alias="Files")
