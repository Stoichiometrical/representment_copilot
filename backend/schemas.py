from typing import Literal

from pydantic import BaseModel, Field


Action = Literal[
    "represent",
    "accept_liability",
    "request_more_evidence",
]


class AnalystOverride(BaseModel):
    action: Action
    rationale: str = Field(min_length=1)
    analyst_note: str = ""

