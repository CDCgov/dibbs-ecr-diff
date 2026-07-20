"""Models for S3 manifest files."""

from pydantic import BaseModel, Field


class ManifestRecord(BaseModel):
    """An eICR and its reportability response."""

    eicr: str
    rr: str | None = None
    setId: str
    versionNumber: int


class Manifest(BaseModel):
    """A manifest containing files to process."""

    files: list[ManifestRecord] = Field(alias="Files")
