import os
import json
import shutil
import uuid
import tempfile
from fastapi import FastAPI, UploadFile, File, Form, Request, HTTPException, BackgroundTasks
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from .database import init_db, get_db
from .resume_parser import parse_resume, parse_sections
from .skill_extractor import extract_skills
from .confidence_scorer import score_confidence
from .test_selector import select_tests, load_test_bank
from .assessment import create_session, get_session_by_token, start_session, complete_session, save_submission, get_submissions
from .email_service import send_assessment_email
from .bulk_processor import process_bulk, write_output, BulkProgress

app = FastAPI(title="SuperRecruit", version="1.0.0")

# In-memory store for bulk jobs
_bulk_jobs: dict[str, BulkProgress] = {}

BASE_DIR = os.path.dirname(__file__)
UPLOAD_DIR = os.path.join(BASE_DIR, "..", "data", "uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)

templates = Jinja2Templates(directory=os.path.join(BASE_DIR, "templates"))
app.mount("/static", StaticFiles(directory=os.path.join(BASE_DIR, "static")), name="static")


@app.on_event("startup")
def startup():
    init_db()
    # Sync test bank to DB
    bank = load_test_bank()
    conn = get_db()
    for t in bank:
        conn.execute(
            "INSERT OR REPLACE INTO test_bank_meta (test_id, name, category, skill_tags) VALUES (?,?,?,?)",
            (t.id, t.name, t.category, json.dumps(t.skill_tags))
        )
    conn.commit()
    conn.close()


# ── Web Routes ──

@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


@app.get("/candidates", response_class=HTMLResponse)
async def candidates_page(request: Request):
    conn = get_db()
    candidates = conn.execute("SELECT * FROM candidates ORDER BY created_at DESC").fetchall()
    conn.close()
    return templates.TemplateResponse("candidates.html", {"request": request, "candidates": [dict(c) for c in candidates]})


@app.get("/candidates/{cid}", response_class=HTMLResponse)
async def candidate_detail(request: Request, cid: int):
    conn = get_db()
    candidate = conn.execute("SELECT * FROM candidates WHERE id=?", (cid,)).fetchone()
    if not candidate:
        raise HTTPException(404, "Candidate not found")
    skills = conn.execute("SELECT * FROM skill_assessments WHERE candidate_id=?", (cid,)).fetchall()
    sessions = conn.execute("SELECT * FROM assessment_sessions WHERE candidate_id=? ORDER BY sent_at DESC", (cid,)).fetchall()
    conn.close()
    return templates.TemplateResponse("candidate_detail.html", {
        "request": request, "candidate": dict(candidate),
        "skills": [dict(s) for s in skills],
        "sessions": [dict(s) for s in sessions],
    })


@app.get("/candidates/{cid}/assessment", response_class=HTMLResponse)
async def assessment_setup(request: Request, cid: int):
    conn = get_db()
    candidate = conn.execute("SELECT * FROM candidates WHERE id=?", (cid,)).fetchone()
    skills = conn.execute("SELECT * FROM skill_assessments WHERE candidate_id=?", (cid,)).fetchall()
    conn.close()
    if not candidate:
        raise HTTPException(404)
    from .models import SkillAssessment
    skill_objs = [SkillAssessment(
        skill_name=s["skill_name"], category=s["category"] or "other",
        evidence=s["evidence"] or "", llm_confidence=float(s["llm_confidence"]),
        final_confidence=float(s["final_confidence"]) if s["final_confidence"] else None,
        reasoning=s["reasoning"] or ""
    ) for s in skills]
    tests = select_tests(skill_objs)
    return templates.TemplateResponse("assessment_setup.html", {
        "request": request, "candidate": dict(candidate),
        "tests": [t.model_dump() for t in tests],
        "skills": [dict(s) for s in skills],
    })


# ── Candidate Assessment Portal ──

@app.get("/assess/{token}", response_class=HTMLResponse)
async def assess_portal(request: Request, token: str):
    session = get_session_by_token(token)
    if not session:
        raise HTTPException(404, "Assessment not found")
    if session["status"] == "completed":
        return templates.TemplateResponse("assess_complete.html", {"request": request, "session": session})
    if session["status"] == "pending":
        start_session(token)
    bank = {t.id: t for t in load_test_bank()}
    tests = [bank[tid].model_dump() for tid in session["tests"] if tid in bank]
    return templates.TemplateResponse("assess.html", {"request": request, "session": session, "tests": tests, "tests_json": json.dumps(tests)})


@app.get("/assess/{token}/results", response_class=HTMLResponse)
async def assess_results(request: Request, token: str):
    session = get_session_by_token(token)
    if not session:
        raise HTTPException(404)
    return templates.TemplateResponse("assess_complete.html", {"request": request, "session": session})


# ── API Routes ──

@app.post("/api/candidates/upload")
async def upload_resume(file: UploadFile = File(...), name: str = Form(...), email: str = Form(...), phone: str = Form("")):
    # Save file
    filename = f"{name.replace(' ', '_')}_{file.filename}"
    path = os.path.join(UPLOAD_DIR, filename)
    with open(path, "wb") as f:
        shutil.copyfileobj(file.file, f)

    # Parse
    parsed = parse_resume(path)
    resume_text = parsed["raw_text"]

    # Save candidate
    conn = get_db()
    cur = conn.execute(
        "INSERT INTO candidates (name, email, phone, resume_path, resume_text, parsed_data) VALUES (?,?,?,?,?,?)",
        (name, email, phone, path, resume_text, json.dumps(parsed))
    )
    cid = cur.lastrowid

    # Extract skills via LLM
    skills = extract_skills(resume_text)

    # Score confidence
    skills = score_confidence(skills, parsed)

    # Save skills
    for s in skills:
        conn.execute(
            "INSERT INTO skill_assessments (candidate_id, skill_name, category, evidence, llm_confidence, final_confidence, reasoning) VALUES (?,?,?,?,?,?,?)",
            (cid, s.skill_name, s.category, s.evidence, s.llm_confidence.value, (s.final_confidence or s.llm_confidence).value, s.reasoning)
        )
    conn.commit()
    conn.close()

    return RedirectResponse(f"/candidates/{cid}", status_code=303)


@app.get("/api/candidates")
async def list_candidates():
    conn = get_db()
    rows = conn.execute("SELECT id, name, email, created_at FROM candidates ORDER BY created_at DESC").fetchall()
    conn.close()
    return [dict(r) for r in rows]


@app.get("/api/candidates/{cid}")
async def get_candidate(cid: int):
    conn = get_db()
    c = conn.execute("SELECT * FROM candidates WHERE id=?", (cid,)).fetchone()
    skills = conn.execute("SELECT * FROM skill_assessments WHERE candidate_id=?", (cid,)).fetchall()
    conn.close()
    if not c:
        raise HTTPException(404)
    return {"candidate": dict(c), "skills": [dict(s) for s in skills]}


@app.post("/api/candidates/{cid}/send-assessment")
async def send_assessment(cid: int, request: Request):
    body = await request.json()
    test_ids = body.get("test_ids", [])
    conn = get_db()
    c = conn.execute("SELECT * FROM candidates WHERE id=?", (cid,)).fetchone()
    conn.close()
    if not c:
        raise HTTPException(404)
    token = create_session(cid, test_ids)
    base_url = body.get("base_url", "http://localhost:8000")
    link = send_assessment_email(c["name"], c["email"], token, base_url)
    return {"token": token, "link": link}


@app.post("/assess/{token}/submit")
async def submit_assessment(token: str, request: Request):
    session = get_session_by_token(token)
    if not session:
        raise HTTPException(404)
    body = await request.json()
    answers = body.get("answers", {})
    bank = {t.id: t for t in load_test_bank()}

    for test_id, questions in answers.items():
        test = bank.get(test_id)
        if not test:
            continue
        q_map = {q.id: q for q in test.questions}
        for qid, answer in questions.items():
            q = q_map.get(qid)
            is_correct = None
            score = 0
            graded_by = "pending"
            if q and q.type == "multiple_choice" and q.correct_answer:
                is_correct = answer.strip().upper() == q.correct_answer.strip().upper()
                score = q.points if is_correct else 0
                graded_by = "auto"
            save_submission(session["id"], test_id, qid, answer, is_correct, score, graded_by)

    complete_session(token)
    return {"status": "completed"}


# ── Bulk Upload ──

@app.get("/bulk", response_class=HTMLResponse)
async def bulk_upload_page(request: Request):
    return templates.TemplateResponse("bulk_upload.html", {"request": request})


def _run_bulk_job(job_id: str, zip_path: str, output_dir: str):
    """Background task for bulk processing."""
    progress = _bulk_jobs[job_id]
    try:
        process_bulk(zip_path, progress=progress)
        write_output(progress, output_dir)
    except Exception as e:
        progress.status = "failed"
    finally:
        # Clean up uploaded zip
        if os.path.exists(zip_path):
            os.unlink(zip_path)


@app.post("/api/bulk")
async def bulk_upload(background_tasks: BackgroundTasks, file: UploadFile = File(...)):
    if not file.filename or not file.filename.lower().endswith(".zip"):
        raise HTTPException(400, "Please upload a .zip file")

    job_id = str(uuid.uuid4())
    # Save zip
    zip_path = os.path.join(UPLOAD_DIR, f"bulk_{job_id}.zip")
    with open(zip_path, "wb") as f:
        shutil.copyfileobj(file.file, f)

    output_dir = os.path.join(UPLOAD_DIR, f"bulk_{job_id}_results")
    _bulk_jobs[job_id] = BulkProgress()
    background_tasks.add_task(_run_bulk_job, job_id, zip_path, output_dir)

    return {"job_id": job_id, "status": "processing"}


@app.get("/api/bulk/{job_id}")
async def bulk_status(job_id: str):
    progress = _bulk_jobs.get(job_id)
    if not progress:
        raise HTTPException(404, "Job not found")
    return progress.to_dict()


@app.get("/api/test-bank")
async def get_test_bank():
    bank = load_test_bank()
    return [{"id": t.id, "name": t.name, "category": t.category, "skill_tags": t.skill_tags,
             "time_limit_minutes": t.time_limit_minutes, "question_count": len(t.questions)} for t in bank]


# ── Workspace Routes ──

@app.get("/workspace/{cid}", response_class=HTMLResponse)
async def workspace(request: Request, cid: int):
    conn = get_db()
    candidate = conn.execute("SELECT * FROM candidates WHERE id=?", (cid,)).fetchone()
    if not candidate:
        conn.close()
        raise HTTPException(404, "Candidate not found")
    skills = conn.execute("SELECT * FROM skill_assessments WHERE candidate_id=?", (cid,)).fetchall()
    history = conn.execute(
        "SELECT role, content, actions_json, created_at FROM workspace_conversations WHERE candidate_id=? ORDER BY created_at ASC",
        (cid,)
    ).fetchall()
    conn.close()
    return templates.TemplateResponse("workspace.html", {
        "request": request,
        "candidate": dict(candidate),
        "skills": [dict(s) for s in skills],
        "history": [dict(h) for h in history],
    })


@app.post("/api/workspace/{cid}/chat")
async def workspace_chat(cid: int, request: Request):
    from .workspace_agent import chat as agent_chat
    body = await request.json()
    user_message = body.get("message", "").strip()
    if not user_message:
        raise HTTPException(400, "Empty message")

    conn = get_db()
    candidate = conn.execute("SELECT * FROM candidates WHERE id=?", (cid,)).fetchone()
    if not candidate:
        conn.close()
        raise HTTPException(404)
    skills = conn.execute("SELECT * FROM skill_assessments WHERE candidate_id=?", (cid,)).fetchall()
    history = conn.execute(
        "SELECT role, content FROM workspace_conversations WHERE candidate_id=? ORDER BY created_at ASC",
        (cid,)
    ).fetchall()

    display_text, actions = agent_chat(
        dict(candidate), [dict(s) for s in skills], [dict(h) for h in history], user_message
    )

    # Save conversation
    conn.execute(
        "INSERT INTO workspace_conversations (candidate_id, role, content) VALUES (?,?,?)",
        (cid, "user", user_message)
    )
    conn.execute(
        "INSERT INTO workspace_conversations (candidate_id, role, content, actions_json) VALUES (?,?,?,?)",
        (cid, "assistant", display_text, json.dumps(actions) if actions else None)
    )

    # Execute actions
    executed = []
    for act in actions:
        action_type = act.get("action")
        if action_type == "adjust_confidence":
            skill_name = act.get("skill_name")
            new_conf = act.get("confidence")
            if skill_name and new_conf is not None:
                row = conn.execute("SELECT id, final_confidence FROM skill_assessments WHERE candidate_id=? AND skill_name=?", (cid, skill_name)).fetchone()
                if row:
                    conn.execute("INSERT INTO skill_overrides (candidate_id, skill_id, field, old_value, new_value, source) VALUES (?,?,?,?,?,?)",
                                 (cid, row["id"], "final_confidence", str(row["final_confidence"]), str(new_conf), "ai"))
                    conn.execute("UPDATE skill_assessments SET final_confidence=? WHERE id=?", (new_conf, row["id"]))
                    executed.append(act)
        elif action_type == "add_skill":
            skill_name = act.get("skill_name")
            if skill_name:
                conn.execute(
                    "INSERT INTO skill_assessments (candidate_id, skill_name, category, evidence, llm_confidence, final_confidence, reasoning) VALUES (?,?,?,?,?,?,?)",
                    (cid, skill_name, act.get("category", "other"), act.get("evidence", ""), act.get("confidence", 0.5), act.get("confidence", 0.5), "Added via workspace chat")
                )
                executed.append(act)
        elif action_type == "remove_skill":
            skill_name = act.get("skill_name")
            if skill_name:
                conn.execute("DELETE FROM skill_assessments WHERE candidate_id=? AND skill_name=?", (cid, skill_name))
                executed.append(act)
        elif action_type == "set_note":
            skill_name = act.get("skill_name")
            note = act.get("note")
            if skill_name and note:
                conn.execute("UPDATE skill_assessments SET reasoning=? WHERE candidate_id=? AND skill_name=?", (note, cid, skill_name))
                executed.append(act)

    conn.commit()

    # Return updated skills
    skills = conn.execute("SELECT * FROM skill_assessments WHERE candidate_id=?", (cid,)).fetchall()
    conn.close()

    return {"message": display_text, "actions": executed, "skills": [dict(s) for s in skills]}


@app.patch("/api/workspace/{cid}/skills/{skill_id}")
async def patch_skill(cid: int, skill_id: int, request: Request):
    body = await request.json()
    conn = get_db()
    row = conn.execute("SELECT * FROM skill_assessments WHERE id=? AND candidate_id=?", (skill_id, cid)).fetchone()
    if not row:
        conn.close()
        raise HTTPException(404, "Skill not found")

    updates = {}
    if "confidence" in body:
        new_conf = max(0.0, min(1.0, float(body["confidence"])))
        conn.execute("INSERT INTO skill_overrides (candidate_id, skill_id, field, old_value, new_value, source) VALUES (?,?,?,?,?,?)",
                     (cid, skill_id, "final_confidence", str(row["final_confidence"]), str(new_conf), "human"))
        conn.execute("UPDATE skill_assessments SET final_confidence=? WHERE id=?", (new_conf, skill_id))
        updates["final_confidence"] = new_conf
    if "irrelevant" in body:
        conn.execute("INSERT INTO skill_overrides (candidate_id, skill_id, field, old_value, new_value, source) VALUES (?,?,?,?,?,?)",
                     (cid, skill_id, "category", row["category"], "irrelevant" if body["irrelevant"] else row["category"], "human"))
        conn.execute("UPDATE skill_assessments SET category=? WHERE id=?", ("irrelevant" if body["irrelevant"] else "other", skill_id))
        updates["category"] = "irrelevant" if body["irrelevant"] else "other"
    if "note" in body:
        conn.execute("UPDATE skill_assessments SET reasoning=? WHERE id=?", (body["note"], skill_id))
        updates["reasoning"] = body["note"]

    conn.commit()
    updated = conn.execute("SELECT * FROM skill_assessments WHERE id=?", (skill_id,)).fetchone()
    conn.close()
    return dict(updated)


@app.post("/api/workspace/{cid}/skills")
async def add_skill(cid: int, request: Request):
    body = await request.json()
    skill_name = body.get("skill_name", "").strip()
    if not skill_name:
        raise HTTPException(400, "skill_name required")
    conn = get_db()
    candidate = conn.execute("SELECT id FROM candidates WHERE id=?", (cid,)).fetchone()
    if not candidate:
        conn.close()
        raise HTTPException(404)
    cur = conn.execute(
        "INSERT INTO skill_assessments (candidate_id, skill_name, category, evidence, llm_confidence, final_confidence, reasoning) VALUES (?,?,?,?,?,?,?)",
        (cid, skill_name, body.get("category", "other"), body.get("evidence", ""), body.get("confidence", 0.5), body.get("confidence", 0.5), body.get("reasoning", "Manually added"))
    )
    conn.commit()
    row = conn.execute("SELECT * FROM skill_assessments WHERE id=?", (cur.lastrowid,)).fetchone()
    conn.close()
    return dict(row)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("src.main:app", host="0.0.0.0", port=8000, reload=True)
