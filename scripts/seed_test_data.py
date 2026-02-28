#!/usr/bin/env python3
"""Generate a sample resume PDF and seed it into the system."""
import os
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas


def create_sample_resume(path: str):
    c = canvas.Canvas(path, pagesize=letter)
    w, h = letter
    y = h - 50

    def write(text, size=11, bold=False):
        nonlocal y
        font = "Helvetica-Bold" if bold else "Helvetica"
        c.setFont(font, size)
        c.drawString(50, y, text)
        y -= size + 4

    write("Alex Johnson", 18, True)
    write("alex.johnson@email.com | (555) 123-4567 | San Francisco, CA")
    y -= 10

    write("SUMMARY", 13, True)
    write("Full-stack software engineer with 6 years of experience building scalable web")
    write("applications. Passionate about clean code, system design, and mentoring junior devs.")
    y -= 10

    write("EXPERIENCE", 13, True)
    write("Senior Software Engineer — TechCorp Inc.", 11, True)
    write("Jan 2021 – Present (3 years)")
    write("• Led migration of monolithic Python/Django app to microservices architecture")
    write("• Designed and implemented RESTful APIs serving 50M requests/day using FastAPI")
    write("• Built real-time data pipeline with Kafka processing 1M events/hour")
    write("• Mentored team of 4 junior engineers, conducting code reviews and design sessions")
    write("• Implemented CI/CD pipeline using GitHub Actions, Docker, and Kubernetes")
    write("• Reduced API response times by 40% through Redis caching and query optimization")
    y -= 8

    write("Software Engineer — StartupXYZ", 11, True)
    write("Jun 2018 – Dec 2020 (2.5 years)")
    write("• Built React frontend with TypeScript for B2B SaaS product (50K DAU)")
    write("• Developed PostgreSQL database schema and complex SQL queries for analytics")
    write("• Implemented OAuth2 authentication and role-based access control")
    write("• Wrote comprehensive unit and integration tests (90%+ coverage)")
    y -= 8

    write("Junior Developer — WebAgency", 11, True)
    write("Aug 2017 – May 2018 (10 months)")
    write("• Built WordPress sites and custom PHP plugins for small business clients")
    write("• Created landing pages with HTML, CSS, and JavaScript")
    y -= 10

    write("EDUCATION", 13, True)
    write("B.S. Computer Science — University of California, Berkeley, 2017")
    y -= 10

    write("CERTIFICATIONS", 13, True)
    write("• AWS Solutions Architect Associate (2022)")
    write("• Certified Kubernetes Administrator (CKA) (2023)")
    y -= 10

    write("SKILLS", 13, True)
    write("Languages: Python, JavaScript, TypeScript, SQL, Go, Rust, PHP")
    write("Frameworks: FastAPI, Django, React, Next.js, Node.js, Express")
    write("Databases: PostgreSQL, Redis, MongoDB, Elasticsearch")
    write("Cloud/DevOps: AWS, Docker, Kubernetes, Terraform, GitHub Actions")
    write("Other: System Design, Agile/Scrum, GraphQL, gRPC, Machine Learning")

    c.save()
    print(f"Created sample resume: {path}")


if __name__ == "__main__":
    os.makedirs(os.path.join(os.path.dirname(__file__), "..", "data"), exist_ok=True)
    path = os.path.join(os.path.dirname(__file__), "..", "data", "sample_resume.pdf")
    create_sample_resume(path)
    print("Done! Upload this via the web UI or use:")
    print(f"  curl -X POST http://localhost:8000/api/candidates/upload \\")
    print(f"    -F 'file=@{path}' -F 'name=Alex Johnson' -F 'email=alex@example.com'")
