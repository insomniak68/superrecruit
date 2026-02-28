"""Bulk resume processing pipeline.

Accepts a directory or zip of PDF resumes and runs each through the
parse → extract → score → select-tests pipeline, collecting results.
"""

import argparse
import csv
import json
import logging
import os
import shutil
import tempfile
import traceback
import uuid
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from .resume_parser import parse_resume
from .skill_extractor import extract_skills
from .confidence_scorer import score_confidence
from .test_selector import select_tests

logger = logging.getLogger(__name__)


@dataclass
class CandidateResult:
    filename: str
    candidate_name: str = ""
    email: str = ""
    skills: list = field(default_factory=list)
    tests: list = field(default_factory=list)
    parsed_data: dict = field(default_factory=dict)
    status: str = "pending"
    error: str = ""
    fit_score: float = 0.0
    fit_level: str = ""

    @property
    def skills_count(self) -> int:
        return len(self.skills)

    @property
    def avg_confidence(self) -> float:
        if not self.skills:
            return 0.0
        vals = [(s.final_confidence if s.final_confidence is not None else s.llm_confidence) for s in self.skills]
        return round(sum(vals) / len(vals), 3)

    @property
    def top_skills(self) -> str:
        high = [s.skill_name for s in self.skills
                if (s.final_confidence if s.final_confidence is not None else s.llm_confidence) >= 0.8]
        return ", ".join(high[:5]) if high else ""

    @property
    def tests_assigned(self) -> str:
        return ", ".join(t.name for t in self.tests)

    def to_dict(self) -> dict:
        return {
            "filename": self.filename,
            "candidate_name": self.candidate_name,
            "email": self.email,
            "skills_count": self.skills_count,
            "avg_confidence": self.avg_confidence,
            "top_skills": self.top_skills,
            "tests_assigned": self.tests_assigned,
            "fit_score": self.fit_score,
            "fit_level": self.fit_level,
            "status": self.status,
            "error": self.error,
            "skills": [s.model_dump() for s in self.skills],
            "tests": [t.model_dump() for t in self.tests],
        }

    def to_csv_row(self) -> dict:
        return {
            "filename": self.filename,
            "candidate_name": self.candidate_name,
            "email": self.email,
            "skills_count": self.skills_count,
            "avg_confidence": self.avg_confidence,
            "top_skills": self.top_skills,
            "tests_assigned": self.tests_assigned,
            "fit_score": self.fit_score,
            "fit_level": self.fit_level,
            "status": self.status,
            "error": self.error,
        }


@dataclass
class BulkProgress:
    total: int = 0
    processed: int = 0
    failed: int = 0
    results: list = field(default_factory=list)
    status: str = "pending"  # pending, processing, completed, failed

    def to_dict(self) -> dict:
        return {
            "total": self.total,
            "processed": self.processed,
            "failed": self.failed,
            "status": self.status,
            "results": [r.to_dict() for r in self.results],
        }


def _extract_contact_info(parsed: dict) -> tuple[str, str]:
    """Try to pull name and email from header/raw text."""
    import re
    header = parsed.get("header", "") or ""
    raw = parsed.get("raw_text", "")
    text = header + "\n" + raw

    # Email
    email_match = re.search(r'[\w.+-]+@[\w-]+\.[\w.-]+', text)
    email = email_match.group(0) if email_match else ""

    # Name: first non-empty line of header, or first line of raw text
    name = ""
    for line in (header or raw).split("\n"):
        stripped = line.strip()
        if stripped and not re.match(r'^[\w.+-]+@', stripped) and not re.match(r'^[\d(+]', stripped):
            name = stripped
            break

    return name, email


def process_single_resume(pdf_path: str) -> CandidateResult:
    """Process one PDF through the full pipeline."""
    result = CandidateResult(filename=os.path.basename(pdf_path))
    try:
        parsed = parse_resume(pdf_path)
        result.parsed_data = parsed
        result.candidate_name, result.email = _extract_contact_info(parsed)

        skills = extract_skills(parsed["raw_text"])
        skills = score_confidence(skills, parsed)
        result.skills = skills

        tests = select_tests(skills)
        result.tests = tests

        # Fit assessment
        try:
            from .fit_assessor import assess_fit
            skill_dicts = [{"skill_name": s.skill_name, "category": s.category,
                             "llm_confidence": s.llm_confidence,
                             "final_confidence": s.final_confidence} for s in skills]
            fit = assess_fit(skill_dicts)
            result.fit_score = fit.fit_score
            result.fit_level = fit.fit_level
        except Exception as e:
            logger.warning(f"Fit assessment failed for {pdf_path}: {e}")

        result.status = "success"
    except Exception as e:
        result.status = "error"
        result.error = f"{type(e).__name__}: {e}"
        logger.error(f"Failed to process {pdf_path}: {result.error}")
        logger.debug(traceback.format_exc())

    return result


def collect_pdfs(input_path: str) -> tuple[list[str], Optional[str]]:
    """Return list of PDF paths. If zip, extract to temp dir (returned for cleanup)."""
    input_path = os.path.abspath(input_path)
    temp_dir = None

    if zipfile.is_zipfile(input_path):
        temp_dir = tempfile.mkdtemp(prefix="bulk_resumes_")
        with zipfile.ZipFile(input_path, 'r') as zf:
            zf.extractall(temp_dir)
        search_dir = temp_dir
    elif os.path.isdir(input_path):
        search_dir = input_path
    else:
        raise ValueError(f"Input must be a directory or zip file: {input_path}")

    pdfs = []
    for root, _, files in os.walk(search_dir):
        for f in sorted(files):
            if f.lower().endswith('.pdf') and not f.startswith('.') and not f.startswith('__'):
                pdfs.append(os.path.join(root, f))

    return pdfs, temp_dir


def process_bulk(input_path: str, progress: Optional[BulkProgress] = None,
                 on_progress: Optional[callable] = None) -> BulkProgress:
    """Process all PDFs from input_path (dir or zip)."""
    if progress is None:
        progress = BulkProgress()

    pdfs, temp_dir = collect_pdfs(input_path)
    progress.total = len(pdfs)
    progress.status = "processing"

    if on_progress:
        on_progress(progress)

    try:
        for pdf_path in pdfs:
            result = process_single_resume(pdf_path)
            progress.results.append(result)
            if result.status == "success":
                progress.processed += 1
            else:
                progress.failed += 1
            if on_progress:
                on_progress(progress)
    finally:
        if temp_dir:
            shutil.rmtree(temp_dir, ignore_errors=True)

    progress.status = "completed"
    if on_progress:
        on_progress(progress)
    return progress


def write_output(progress: BulkProgress, output_dir: str) -> None:
    """Write summary.json, summary.csv, and per-candidate JSON files."""
    os.makedirs(output_dir, exist_ok=True)

    # summary.json
    with open(os.path.join(output_dir, "summary.json"), "w") as f:
        json.dump(progress.to_dict(), f, indent=2, default=str)

    # summary.csv
    csv_columns = ["filename", "candidate_name", "email", "skills_count",
                    "avg_confidence", "top_skills", "tests_assigned",
                    "fit_score", "fit_level", "status", "error"]
    with open(os.path.join(output_dir, "summary.csv"), "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=csv_columns)
        writer.writeheader()
        for r in progress.results:
            writer.writerow(r.to_csv_row())

    # Per-candidate JSON
    for i, r in enumerate(progress.results):
        safe_name = r.filename.replace(" ", "_").replace("/", "_")
        if safe_name.lower().endswith(".pdf"):
            safe_name = safe_name[:-4]
        with open(os.path.join(output_dir, f"{safe_name}.json"), "w") as f:
            json.dump(r.to_dict(), f, indent=2, default=str)


# ── CLI ──

def main():
    parser = argparse.ArgumentParser(description="Bulk resume processor")
    parser.add_argument("--input", required=True, help="Path to directory or zip of PDF resumes")
    parser.add_argument("--output", required=True, help="Output directory for results")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    def log_progress(p: BulkProgress):
        logger.info(f"Progress: {p.processed + p.failed}/{p.total} "
                     f"(success={p.processed}, failed={p.failed}, status={p.status})")

    progress = process_bulk(args.input, on_progress=log_progress)
    write_output(progress, args.output)
    logger.info(f"Done. Results in {args.output}")


if __name__ == "__main__":
    main()
