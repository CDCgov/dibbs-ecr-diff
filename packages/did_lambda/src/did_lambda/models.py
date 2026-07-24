"""Models for S3 manifest files."""

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

    eicr_diff_output: str
    rr_diff_output: str | None = None
