import uuid
from dataclasses import dataclass, field
from typing import Optional

from .checks.models import CheckItem, PageInfo

# Ordered check groups — must match route names
GROUPS: tuple[str, ...] = (
    "images",
    "fonts",
    "safe_zone",
)

GROUP_LABELS: dict[str, str] = {
    "images": "Image Resolution",
    "fonts": "Fonts",
    "safe_zone": "Safe Zone",
}

GROUP_ICONS: dict[str, str] = {
    "images": "🖼️",
    "fonts": "🔤",
    "safe_zone": "📏",
}


@dataclass
class Job:
    filename: str
    pdf_bytes: bytes
    page_count: int
    pages: list[PageInfo]
    detected_trim: dict = field(default_factory=dict)
    results: dict[str, list[CheckItem]] = field(default_factory=dict)

    def is_complete(self) -> bool:
        return all(g in self.results for g in GROUPS)

    def overall_pass(self) -> bool:
        all_checks = [c for group in self.results.values() for c in group]
        return all(c.passed for c in all_checks if c.severity == "error")


_store: dict[str, Job] = {}


def create_job(
    filename: str,
    pdf_bytes: bytes,
    page_count: int,
    pages: list[PageInfo],
    detected_trim: dict | None = None,
) -> str:
    job_id = str(uuid.uuid4())
    _store[job_id] = Job(
        filename=filename,
        pdf_bytes=pdf_bytes,
        page_count=page_count,
        pages=pages,
        detected_trim=detected_trim or {},
    )
    return job_id


def get_job(job_id: str) -> Optional[Job]:
    return _store.get(job_id)


def update_job_trim(job_id: str, trim_dict: dict) -> None:
    job = _store.get(job_id)
    if job:
        job.detected_trim = trim_dict


def store_results(job_id: str, group: str, checks: list[CheckItem]) -> None:
    job = _store.get(job_id)
    if job:
        job.results[group] = checks
