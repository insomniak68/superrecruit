import re
import pdfplumber


SECTION_HEADERS = [
    "experience", "work experience", "professional experience", "employment",
    "education", "academic", "skills", "technical skills", "core competencies",
    "certifications", "certificates", "projects", "summary", "objective",
    "profile", "about", "awards", "publications", "languages", "interests",
    "volunteer", "references",
]


def extract_text_from_pdf(pdf_path: str) -> str:
    text = ""
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            t = page.extract_text()
            if t:
                text += t + "\n"
    return text


def parse_sections(text: str) -> dict:
    sections = {"raw_text": text, "header": "", "sections": {}}
    lines = text.split("\n")
    current_section = "header"
    current_content = []

    for line in lines:
        stripped = line.strip()
        lower = stripped.lower().rstrip(":")
        if lower in SECTION_HEADERS or any(h in lower for h in SECTION_HEADERS):
            if current_content:
                sections["sections"][current_section] = "\n".join(current_content).strip()
            # Find best matching header
            matched = lower
            for h in SECTION_HEADERS:
                if h in lower:
                    matched = h
                    break
            current_section = matched
            current_content = []
        else:
            current_content.append(line)

    if current_content:
        sections["sections"][current_section] = "\n".join(current_content).strip()

    # Extract header info (name/email) from first few lines
    if "header" in sections["sections"]:
        sections["header"] = sections["sections"].pop("header")

    return sections


def parse_resume(pdf_path: str) -> dict:
    text = extract_text_from_pdf(pdf_path)
    return parse_sections(text)
