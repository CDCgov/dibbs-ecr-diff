from pydantic import BaseModel


class DiffingOptions(BaseModel):
    """Diffing options model."""

    file1: str
    file2: str
    out1: str
    out2: str
    out3: str
    out5: str
    no_prefer_updates: bool
    debug_match: bool
    no_huge: bool
