"""Models for S3 manifest files."""

from pydantic import BaseModel, Field


class ManifestFile(BaseModel):
    """An eICR and its optional reportability response."""

    eicr: str
    rr: str | None = None
    setid: str
    version: int


class Manifest(BaseModel):
    """A manifest containing files to process."""

    files: list[ManifestFile] = Field(alias="Files")
