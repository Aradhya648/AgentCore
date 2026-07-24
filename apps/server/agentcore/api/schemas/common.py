"""Generic / shared response schemas."""

from pydantic import BaseModel


class StatusResponse(BaseModel):
    status: str = "ok"
