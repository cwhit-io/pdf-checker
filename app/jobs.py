import uuid
from dataclasses import dataclass, field
from typing import Optional

from .checks.models import CheckItem, PageInfo

# Ordered check groups — must match route names
GROUPS: tuple[str, ...] = (
    "bleed_trim",
    "color",
    "images",
    "fonts",
    "safe_zone",
    "transparency",
    "overprint",
    "ink_density",
    "security",
    "metadata",
)

GROUP_LABELS: dict[str, str] = {
    "bleed_trim": "Trim / Bleed",
    "color": "Color",
    "images": "Image Resolution",
    "fonts": "Fonts",
    "safe_zone": "Safe Zone",
    "transparency": "Transparency",
    "overprint": "Overprint",
    "ink_density": "Ink Density",
    "security": "Security",
    "metadata": "Metadata",
}

GROUP_ICONS: dict[str, str] = {
    "bleed_trim": "✂️",
    "color": "🎨",
    "images": "🖼️",
    "fonts": "🔤",
    "safe_zone": "📏",
    "transparency": "🔍",
    "overprint": "🖨️",
    "ink_density": "💧",
    "security": "🔒",
    "metadata": "📋",
}


@dataclass
class Job:
    filename: str
    pdf_bytes: bytes
    page_count: int
    pages: list[PageInfo]
    detected_trim: dict = field(default_factory=dict)
    results: dict[str, list[CheckItem]] = field(default_factory=dict)
    quality_score: int = 100  # 0–100, updated after all checks complete

    def is_complete(self) -> bool:
        return all(g in self.results for g in GROUPS)

    def overall_pass(self) -> bool:
        all_checks = [c for group in self.results.values() for c in group]
        return all(c.passed for c in all_checks if c.severity == "error")

    def compute_quality_score(self) -> int:
        """Compute a 0–100 quality score based on completed checks."""
        all_checks = [c for group in self.results.values() for c in group]
        if not all_checks:
            return 100
        deductions = 0
        for c in all_checks:
            if c.passed:
                continue
            if c.severity == "error":
                deductions += 15
            elif c.severity == "warning":
                deductions += 5
            else:
                deductions += 1
        score = max(0, 100 - deductions)
        self.quality_score = score
        return score


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
        # Recompute quality score incrementally after each group
        job.compute_quality_score()
