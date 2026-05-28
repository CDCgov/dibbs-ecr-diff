from pydantic import BaseModel


class DiffingOptions(BaseModel):
    """Diffing options model."""

    file1: str
    file2: str
