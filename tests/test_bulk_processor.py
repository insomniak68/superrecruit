"""Tests for the bulk resume processor."""

import json
import os
import shutil
import tempfile
import zipfile
from unittest.mock import patch

import pytest

from src.bulk_processor import (
    process_single_resume,
    process_bulk,
    write_output,
    collect_pdfs,
    BulkProgress,
    CandidateResult,
    _extract_contact_info,
)
from src.models import SkillAssessment


# ── Fixtures ──

MOCK_PARSED = {
    "raw_text": "John Doe\njohn@example.com\nExperience\nSenior Python Developer",
    "header": "John Doe\njohn@example.com",
    "sections": {"experience": "Senior Python Developer at Acme Corp"},
}

MOCK_SKILLS = [
    SkillAssessment(
        skill_name="Python",
        category="programming",
        evidence="Senior Python Developer",
        llm_confidence=0.9,
        final_confidence=0.95,
        reasoning="Direct job title match",
    ),
    SkillAssessment(
        skill_name="Django",
        category="framework",
        evidence="Used Django at Acme",
        llm_confidence=0.5,
        final_confidence=0.55,
        reasoning="Mentioned but brief",
    ),
]


def _create_fake_pdf(directory: str, name: str = "resume.pdf") -> str:
    path = os.path.join(directory, name)
    with open(path, "wb") as f:
        f.write(b"%PDF-1.4 fake pdf content")
    return path


def _create_test_zip(pdf_names: list[str]) -> str:
    tmp = tempfile.mkdtemp()
    zip_path = os.path.join(tmp, "resumes.zip")
    with zipfile.ZipFile(zip_path, "w") as zf:
        for name in pdf_names:
            zf.writestr(name, b"%PDF-1.4 fake pdf content")
    return zip_path


# ── Tests ──

class TestExtractContactInfo:
    def test_extracts_email(self):
        parsed = {"header": "Jane Doe\njane@test.com\n555-1234", "raw_text": ""}
        name, email = _extract_contact_info(parsed)
        assert email == "jane@test.com"
        assert name == "Jane Doe"

    def test_no_header_falls_back_to_raw(self):
        parsed = {"header": "", "raw_text": "Bob Smith\nbob@x.com"}
        name, email = _extract_contact_info(parsed)
        assert name == "Bob Smith"
        assert email == "bob@x.com"

    def test_empty(self):
        name, email = _extract_contact_info({"header": "", "raw_text": ""})
        assert name == ""
        assert email == ""


class TestCollectPdfs:
    def test_from_directory(self, tmp_path):
        _create_fake_pdf(str(tmp_path), "a.pdf")
        _create_fake_pdf(str(tmp_path), "b.pdf")
        (tmp_path / "readme.txt").write_text("hi")
        pdfs, temp = collect_pdfs(str(tmp_path))
        assert len(pdfs) == 2
        assert temp is None

    def test_from_zip(self):
        zip_path = _create_test_zip(["alice.pdf", "bob.pdf", "notes.txt"])
        try:
            pdfs, temp = collect_pdfs(zip_path)
            assert len(pdfs) == 2
            assert temp is not None
        finally:
            if temp:
                shutil.rmtree(temp, ignore_errors=True)
            os.unlink(zip_path)
            os.rmdir(os.path.dirname(zip_path))

    def test_invalid_path(self):
        with pytest.raises(ValueError):
            collect_pdfs("/nonexistent/file.txt")


class TestProcessSingleResume:
    @patch("src.bulk_processor.select_tests")
    @patch("src.bulk_processor.score_confidence")
    @patch("src.bulk_processor.extract_skills")
    @patch("src.bulk_processor.parse_resume")
    def test_success(self, mock_parse, mock_extract, mock_score, mock_select):
        mock_parse.return_value = MOCK_PARSED
        mock_extract.return_value = MOCK_SKILLS
        mock_score.return_value = MOCK_SKILLS
        mock_select.return_value = []

        result = process_single_resume("/fake/resume.pdf")
        assert result.status == "success"
        assert result.candidate_name == "John Doe"
        assert result.email == "john@example.com"
        assert result.skills_count == 2

    @patch("src.bulk_processor.parse_resume", side_effect=Exception("PDF corrupt"))
    def test_error_handling(self, mock_parse):
        result = process_single_resume("/fake/bad.pdf")
        assert result.status == "error"
        assert "PDF corrupt" in result.error


class TestProcessBulk:
    @patch("src.bulk_processor.process_single_resume")
    def test_processes_all_pdfs(self, mock_process, tmp_path):
        _create_fake_pdf(str(tmp_path), "a.pdf")
        _create_fake_pdf(str(tmp_path), "b.pdf")
        mock_process.return_value = CandidateResult(filename="test.pdf", status="success")

        progress = process_bulk(str(tmp_path))
        assert progress.total == 2
        assert progress.processed == 2
        assert progress.failed == 0
        assert progress.status == "completed"

    @patch("src.bulk_processor.process_single_resume")
    def test_tracks_failures(self, mock_process, tmp_path):
        _create_fake_pdf(str(tmp_path), "a.pdf")
        _create_fake_pdf(str(tmp_path), "b.pdf")
        results = [
            CandidateResult(filename="a.pdf", status="success"),
            CandidateResult(filename="b.pdf", status="error", error="fail"),
        ]
        mock_process.side_effect = results

        progress = process_bulk(str(tmp_path))
        assert progress.processed == 1
        assert progress.failed == 1

    @patch("src.bulk_processor.process_single_resume")
    def test_progress_callback(self, mock_process, tmp_path):
        _create_fake_pdf(str(tmp_path), "a.pdf")
        mock_process.return_value = CandidateResult(filename="a.pdf", status="success")

        calls = []
        progress = process_bulk(str(tmp_path), on_progress=lambda p: calls.append(p.status))
        assert len(calls) >= 2


class TestWriteOutput:
    def test_creates_files(self, tmp_path):
        progress = BulkProgress(total=1, processed=1, status="completed")
        result = CandidateResult(filename="test.pdf", status="success", candidate_name="Test")
        result.skills = MOCK_SKILLS
        result.tests = []
        progress.results = [result]

        output_dir = str(tmp_path / "output")
        write_output(progress, output_dir)

        assert os.path.exists(os.path.join(output_dir, "summary.json"))
        assert os.path.exists(os.path.join(output_dir, "summary.csv"))
        assert os.path.exists(os.path.join(output_dir, "test.json"))

        with open(os.path.join(output_dir, "summary.json")) as f:
            data = json.load(f)
        assert data["total"] == 1
        assert data["processed"] == 1

    def test_csv_columns(self, tmp_path):
        progress = BulkProgress(total=1, processed=1, status="completed")
        result = CandidateResult(filename="x.pdf", status="success")
        result.skills = []
        result.tests = []
        progress.results = [result]

        output_dir = str(tmp_path / "out")
        write_output(progress, output_dir)

        import csv
        with open(os.path.join(output_dir, "summary.csv")) as f:
            reader = csv.DictReader(f)
            row = next(reader)
        expected = {"filename", "candidate_name", "email", "skills_count",
                    "avg_confidence", "top_skills", "tests_assigned", "status", "error",
                    "fit_score", "fit_level"}
        assert set(row.keys()) == expected


class TestCandidateResult:
    def test_avg_confidence(self):
        r = CandidateResult(filename="t.pdf")
        r.skills = MOCK_SKILLS  # 0.95 + 0.55
        assert r.avg_confidence == 0.75

    def test_top_skills(self):
        r = CandidateResult(filename="t.pdf")
        r.skills = MOCK_SKILLS
        assert "Python" in r.top_skills

    def test_empty_skills(self):
        r = CandidateResult(filename="t.pdf")
        assert r.avg_confidence == 0.0
        assert r.top_skills == ""
