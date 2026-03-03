from pydantic import BaseModel
from typing import List


class CheckItem(BaseModel):
    name: str
    passed: bool
    detail: str
    severity: str  # "error" | "warning" | "info"


class PageInfo(BaseModel):
    page_number: int
    width_pt: float
    height_pt: float
    width_in: float
    height_in: float
    orientation: str


class CheckReport(BaseModel):
    filename: str
    page_count: int
    checks: List[CheckItem]
    pages: List[PageInfo]
    overall_pass: bool
