"""FastAPI server for Difference in Docs."""

from core import diff_xml
from fastapi import FastAPI, HTTPException
from fastapi.responses import PlainTextResponse

app = FastAPI()


@app.get("/", response_class=PlainTextResponse)
def health_check() -> str:
    """Health check endpoint."""
    return "OK"


@app.get("/diff", response_class=PlainTextResponse)
async def diff_docs() -> str:
    """Diffing endpoint."""
    try:
        xml = diff_xml()
        return xml
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Error diffing files: {str(e)}"
        ) from e
