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
from .integrations import (
    init_integration_tables, authenticate_api_key,
    create_integration, list_integrations, revoke_integration,
    create_submission as create_submission_record, update_submission,
    get_submission as get_submission_record, list_submissions as list_submission_records,
)
from .webhooks import dispatch_webhook
from .fit_assessor import assess_fit
from .position_profiles import (
    create_position, get_position, list_positions, update_position,
    delete_position, activate_position, get_active_position, parse_job_posting,
)
from .skill_equivalencies import (
    create_equivalency_group, get_equivalency_group, list_equivalency_groups,
    update_equivalency_group, delete_equivalency_group, seed_equivalency_groups,
    record_cooccurrences, suggest_equivalency_groups, get_weight_suggestions,
    record_equivalency_feedback,
)
from .models import (
    PositionProfileCreate, PositionProfileUpdate, JobPostingInput,
    EquivalencyGroupCreate, EquivalencyGroupUpdate,
)

app = FastAPI(title="SuperRecruit", version="1.0.0")


@app.get("/health")
async def health():
    return {"status": "ok"}

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
    init_integration_tables()
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
    fit_row = conn.execute(
        "SELECT * FROM fit_assessments WHERE candidate_id=? ORDER BY created_at DESC LIMIT 1", (cid,)
    ).fetchone()
    conn.close()
    return templates.TemplateResponse("candidate_detail.html", {
        "request": request, "candidate": dict(candidate),
        "skills": [dict(s) for s in skills],
        "sessions": [dict(s) for s in sessions],
        "fit": dict(fit_row) if fit_row else None,
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

    # Track skill co-occurrences for equivalency suggestions
    try:
        record_cooccurrences([s.skill_name for s in skills])
    except Exception:
        pass  # Non-fatal

    # Run fit assessment
    skill_dicts = [{"skill_name": s.skill_name, "category": s.category,
                     "llm_confidence": s.llm_confidence.value,
                     "final_confidence": (s.final_confidence or s.llm_confidence).value} for s in skills]
    try:
        # Use active position profile if available
        active_pos = get_active_position()
        position_profile = None
        if active_pos:
            position_profile = {
                "name": active_pos.title,
                "position_id": active_pos.id,
                "core_skills": [{"name": s.skill_name, "weight": s.weight} for s in active_pos.required_skills],
                "adjacent_skills": [{"name": s.skill_name, "weight": s.weight} for s in active_pos.preferred_skills],
            }
        fit = assess_fit(skill_dicts, position_profile=position_profile)
        conn.execute(
            "INSERT INTO fit_assessments (candidate_id, fit_score, fit_level, rationale, breakdown_json, assessed_by) VALUES (?,?,?,?,?,?)",
            (cid, fit.fit_score, fit.fit_level, fit.rationale, json.dumps(fit.breakdown), "system")
        )
        conn.commit()
    except Exception:
        pass  # Non-fatal — fit assessment is best-effort
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


# ── Position Profiles ──

@app.get("/positions", response_class=HTMLResponse)
async def positions_page(request: Request):
    positions = list_positions()
    return templates.TemplateResponse("positions.html", {"request": request, "positions": [p.model_dump() for p in positions]})


@app.post("/api/positions")
async def api_create_position(request: Request):
    body = await request.json()
    data = PositionProfileCreate(**body)
    position = create_position(data)
    return position.model_dump()


@app.post("/api/positions/from-posting")
async def api_create_from_posting(request: Request):
    body = await request.json()
    text = body.get("text", "").strip()
    if not text:
        raise HTTPException(400, "Job posting text is required")
    parsed = parse_job_posting(text)
    position = create_position(parsed, created_by="job_parser")
    return position.model_dump()


@app.get("/api/positions")
async def api_list_positions():
    return [p.model_dump() for p in list_positions()]


@app.get("/api/positions/{pid}")
async def api_get_position(pid: int):
    p = get_position(pid)
    if not p:
        raise HTTPException(404, "Position not found")
    return p.model_dump()


@app.put("/api/positions/{pid}")
async def api_update_position(pid: int, request: Request):
    body = await request.json()
    data = PositionProfileUpdate(**body)
    p = update_position(pid, data)
    if not p:
        raise HTTPException(404, "Position not found")
    return p.model_dump()


@app.delete("/api/positions/{pid}")
async def api_delete_position(pid: int):
    if not delete_position(pid):
        raise HTTPException(404, "Position not found")
    return {"ok": True}


@app.post("/api/positions/{pid}/activate")
async def api_activate_position(pid: int):
    p = activate_position(pid)
    if not p:
        raise HTTPException(404, "Position not found")
    return p.model_dump()


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
    fit_row = conn.execute(
        "SELECT * FROM fit_assessments WHERE candidate_id=? ORDER BY created_at DESC LIMIT 1", (cid,)
    ).fetchone()
    conn.close()
    fit = dict(fit_row) if fit_row else None
    fit_breakdown = None
    if fit and fit.get("breakdown_json"):
        try:
            fit_breakdown = json.loads(fit["breakdown_json"])
        except (json.JSONDecodeError, TypeError):
            pass
    return templates.TemplateResponse("workspace.html", {
        "request": request,
        "candidate": dict(candidate),
        "skills": [dict(s) for s in skills],
        "history": [dict(h) for h in history],
        "fit": fit,
        "fit_breakdown": fit_breakdown,
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

    fit_row = conn.execute(
        "SELECT * FROM fit_assessments WHERE candidate_id=? ORDER BY created_at DESC LIMIT 1", (cid,)
    ).fetchone()

    display_text, actions = agent_chat(
        dict(candidate), [dict(s) for s in skills], [dict(h) for h in history], user_message,
        fit=dict(fit_row) if fit_row else None
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
        elif action_type == "learn_skill_concept":
            from .knowledge_base import SkillConcept, create_skill_concept, get_skill_by_canonical
            sk_name = act.get("name", "")
            if sk_name and not get_skill_by_canonical(sk_name.lower().strip()):
                create_skill_concept(SkillConcept(
                    name=sk_name, category=act.get("category", "other"),
                    description=act.get("description", "")
                ))
                executed.append(act)
        elif action_type == "learn_equivalency":
            from .knowledge_base import SkillRelation, create_skill_relation, get_skill_by_canonical
            src = get_skill_by_canonical(act.get("skill_name", "").lower().strip())
            tgt = get_skill_by_canonical(act.get("equivalent_to", "").lower().strip())
            if src and tgt:
                create_skill_relation(SkillRelation(
                    source_skill_id=src.id, target_skill_id=tgt.id,
                    relation_type="equivalent", strength=float(act.get("strength", 1.0)), source="ai"
                ))
                executed.append(act)
        elif action_type == "override_fit":
            fit_level = act.get("level", "").strip()
            fit_rationale = act.get("rationale", "").strip()
            fit_score = act.get("score")
            if fit_level:
                if fit_score is None:
                    level_scores = {"strong": 0.85, "good": 0.6, "weak": 0.35, "poor": 0.15}
                    fit_score = level_scores.get(fit_level, 0.5)
                conn.execute(
                    "INSERT INTO fit_assessments (candidate_id, fit_score, fit_level, rationale, breakdown_json, assessed_by) VALUES (?,?,?,?,?,?)",
                    (cid, fit_score, fit_level, fit_rationale, json.dumps({"override": True}), "ai")
                )
                executed.append(act)
        elif action_type == "set_note":
            skill_name = act.get("skill_name")
            note = act.get("note")
            if skill_name and note:
                conn.execute("UPDATE skill_assessments SET reasoning=? WHERE candidate_id=? AND skill_name=?", (note, cid, skill_name))
                executed.append(act)

    conn.commit()

    # Return updated skills and fit
    skills = conn.execute("SELECT * FROM skill_assessments WHERE candidate_id=?", (cid,)).fetchall()
    fit_row = conn.execute(
        "SELECT * FROM fit_assessments WHERE candidate_id=? ORDER BY created_at DESC LIMIT 1", (cid,)
    ).fetchone()
    conn.close()

    result = {"message": display_text, "actions": executed, "skills": [dict(s) for s in skills]}
    if fit_row:
        result["fit"] = dict(fit_row)
    return result


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


@app.patch("/api/workspace/{cid}/fit")
async def patch_fit(cid: int, request: Request):
    body = await request.json()
    conn = get_db()
    candidate = conn.execute("SELECT id FROM candidates WHERE id=?", (cid,)).fetchone()
    if not candidate:
        conn.close()
        raise HTTPException(404, "Candidate not found")

    fit_level = body.get("fit_level", "").strip()
    rationale = body.get("rationale", "").strip()
    fit_score = body.get("fit_score")
    assessed_by = body.get("assessed_by", "human")

    if not fit_level:
        conn.close()
        raise HTTPException(400, "fit_level required")

    # Map level to score if not provided
    if fit_score is None:
        level_scores = {"strong": 0.85, "good": 0.6, "weak": 0.35, "poor": 0.15}
        fit_score = level_scores.get(fit_level, 0.5)
    fit_score = max(0.0, min(1.0, float(fit_score)))

    conn.execute(
        "INSERT INTO fit_assessments (candidate_id, fit_score, fit_level, rationale, breakdown_json, assessed_by) VALUES (?,?,?,?,?,?)",
        (cid, fit_score, fit_level, rationale, json.dumps({"override": True}), assessed_by)
    )
    conn.commit()
    row = conn.execute(
        "SELECT * FROM fit_assessments WHERE candidate_id=? ORDER BY created_at DESC LIMIT 1", (cid,)
    ).fetchone()
    conn.close()
    return dict(row)


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


# ── Equivalencies Routes ──

@app.get("/equivalencies", response_class=HTMLResponse)
async def equivalencies_page(request: Request):
    groups = list_equivalency_groups()
    return templates.TemplateResponse("equivalencies.html", {"request": request, "groups": [g.model_dump() for g in groups]})


@app.post("/api/equivalencies")
async def api_create_equivalency(request: Request):
    body = await request.json()
    data = EquivalencyGroupCreate(**body)
    return create_equivalency_group(data).model_dump()


@app.get("/api/equivalencies")
async def api_list_equivalencies():
    return [g.model_dump() for g in list_equivalency_groups()]


@app.get("/api/equivalencies/{gid}")
async def api_get_equivalency(gid: int):
    g = get_equivalency_group(gid)
    if not g:
        raise HTTPException(404, "Equivalency group not found")
    return g.model_dump()


@app.put("/api/equivalencies/{gid}")
async def api_update_equivalency(gid: int, request: Request):
    body = await request.json()
    data = EquivalencyGroupUpdate(**body)
    g = update_equivalency_group(gid, data)
    if not g:
        raise HTTPException(404, "Equivalency group not found")
    return g.model_dump()


@app.delete("/api/equivalencies/{gid}")
async def api_delete_equivalency(gid: int):
    if not delete_equivalency_group(gid):
        raise HTTPException(404, "Equivalency group not found")
    return {"ok": True}


@app.post("/api/equivalencies/seed")
async def api_seed_equivalencies():
    created = seed_equivalency_groups()
    return {"seeded": len(created), "groups": [g.model_dump() for g in created]}


@app.get("/api/equivalencies/suggestions")
async def api_equivalency_suggestions(min_cooccurrences: int = 5, min_skills: int = 3):
    """Suggest new equivalency groups based on skill co-occurrence patterns."""
    return suggest_equivalency_groups(min_cooccurrences=min_cooccurrences, min_skills=min_skills)


@app.get("/api/equivalencies/weight-suggestions")
async def api_weight_suggestions(min_feedback: int = 3):
    """Suggest weight adjustments based on screener feedback."""
    return get_weight_suggestions(min_feedback=min_feedback)


@app.post("/api/equivalencies/feedback")
async def api_record_feedback(request: Request):
    """Record screener feedback on an equivalency match."""
    body = await request.json()
    record_equivalency_feedback(
        required_skill=body["required_skill"],
        candidate_skill=body["candidate_skill"],
        original_weight=body["original_weight"],
        screener_action=body.get("screener_action", "override"),
        group_id=body.get("group_id"),
        adjusted_score=body.get("adjusted_score"),
        context=body.get("context"),
    )
    return {"ok": True}


# ── Knowledge Base Routes ──

from .knowledge_base import (
    SkillConcept, SkillRelation, RoleArchetype, EmployerInterpretation,
    create_skill_concept, get_skill_concept, list_skill_concepts, update_skill_concept, delete_skill_concept,
    create_skill_relation, get_skill_relations, delete_skill_relation,
    create_role_archetype, get_role_archetype, list_role_archetypes, update_role_archetype, delete_role_archetype,
    create_employer_interpretation, get_employer_interpretation, list_employer_interpretations,
    update_employer_interpretation, delete_employer_interpretation,
    search_knowledge_base, export_knowledge_base, import_knowledge_base,
)


@app.get("/knowledge-base", response_class=HTMLResponse)
async def knowledge_base_page(request: Request):
    return templates.TemplateResponse("knowledge_base.html", {"request": request})


# Skills CRUD
@app.get("/api/kb/skills")
async def kb_list_skills():
    return [s.model_dump() for s in list_skill_concepts()]


@app.post("/api/kb/skills")
async def kb_create_skill(request: Request):
    body = await request.json()
    skill = SkillConcept(**body)
    return create_skill_concept(skill).model_dump()


@app.get("/api/kb/skills/{skill_id}")
async def kb_get_skill(skill_id: int):
    s = get_skill_concept(skill_id)
    if not s:
        raise HTTPException(404, "Skill concept not found")
    s_dict = s.model_dump()
    s_dict["relations"] = [r.model_dump() for r in get_skill_relations(skill_id)]
    return s_dict


@app.patch("/api/kb/skills/{skill_id}")
async def kb_update_skill(skill_id: int, request: Request):
    body = await request.json()
    s = update_skill_concept(skill_id, body)
    if not s:
        raise HTTPException(404, "Skill concept not found")
    return s.model_dump()


@app.delete("/api/kb/skills/{skill_id}")
async def kb_delete_skill(skill_id: int):
    if not delete_skill_concept(skill_id):
        raise HTTPException(404, "Skill concept not found")
    return {"ok": True}


# Skill Relations
@app.post("/api/kb/skills/{skill_id}/relations")
async def kb_create_relation(skill_id: int, request: Request):
    body = await request.json()
    body["source_skill_id"] = skill_id
    rel = SkillRelation(**body)
    return create_skill_relation(rel).model_dump()


@app.delete("/api/kb/relations/{relation_id}")
async def kb_delete_relation(relation_id: int):
    if not delete_skill_relation(relation_id):
        raise HTTPException(404)
    return {"ok": True}


# Roles CRUD
@app.get("/api/kb/roles")
async def kb_list_roles():
    return [r.model_dump() for r in list_role_archetypes()]


@app.post("/api/kb/roles")
async def kb_create_role(request: Request):
    body = await request.json()
    role = RoleArchetype(**body)
    return create_role_archetype(role).model_dump()


@app.get("/api/kb/roles/{role_id}")
async def kb_get_role(role_id: int):
    r = get_role_archetype(role_id)
    if not r:
        raise HTTPException(404, "Role archetype not found")
    return r.model_dump()


@app.patch("/api/kb/roles/{role_id}")
async def kb_update_role(role_id: int, request: Request):
    body = await request.json()
    r = update_role_archetype(role_id, body)
    if not r:
        raise HTTPException(404)
    return r.model_dump()


@app.delete("/api/kb/roles/{role_id}")
async def kb_delete_role(role_id: int):
    if not delete_role_archetype(role_id):
        raise HTTPException(404)
    return {"ok": True}


# Employer Interpretations
@app.get("/api/kb/roles/{role_id}/employers")
async def kb_list_employers(role_id: int):
    return [e.model_dump() for e in list_employer_interpretations(role_id)]


@app.post("/api/kb/roles/{role_id}/employers")
async def kb_create_employer(role_id: int, request: Request):
    body = await request.json()
    body["role_archetype_id"] = role_id
    ei = EmployerInterpretation(**body)
    return create_employer_interpretation(ei).model_dump()


@app.get("/api/kb/roles/{role_id}/employers/{ei_id}")
async def kb_get_employer(role_id: int, ei_id: int):
    e = get_employer_interpretation(ei_id)
    if not e or e.role_archetype_id != role_id:
        raise HTTPException(404)
    return e.model_dump()


@app.patch("/api/kb/roles/{role_id}/employers/{ei_id}")
async def kb_update_employer(role_id: int, ei_id: int, request: Request):
    body = await request.json()
    e = update_employer_interpretation(ei_id, body)
    if not e:
        raise HTTPException(404)
    return e.model_dump()


@app.delete("/api/kb/roles/{role_id}/employers/{ei_id}")
async def kb_delete_employer(role_id: int, ei_id: int):
    if not delete_employer_interpretation(ei_id):
        raise HTTPException(404)
    return {"ok": True}


# Search
@app.get("/api/kb/search")
async def kb_search(q: str = ""):
    if not q:
        return {"skills": [], "roles": []}
    results = search_knowledge_base(q)
    return {"skills": [s.model_dump() for s in results["skills"]],
            "roles": [r.model_dump() for r in results["roles"]]}


# Export/Import
@app.get("/api/kb/export")
async def kb_export():
    return export_knowledge_base()


@app.post("/api/kb/import")
async def kb_import(request: Request):
    body = await request.json()
    stats = import_knowledge_base(body)
    return stats


# ── API Key Auth Dependency ──

from fastapi import Depends, Header
from pydantic import BaseModel
from typing import Optional
import base64


async def require_api_key(x_api_key: str = Header(..., alias="X-API-Key")) -> dict:
    integration = authenticate_api_key(x_api_key)
    if not integration:
        raise HTTPException(401, "Invalid or revoked API key")
    return integration


# ── V1 Submission API (external integration surface) ──

class SubmissionCreate(BaseModel):
    name: str
    email: str
    phone: Optional[str] = None
    resume: Optional[str] = None  # base64-encoded PDF
    metadata: Optional[dict] = None
    callback_url: Optional[str] = None


@app.post("/api/v1/submissions")
async def v1_create_submission(
    body: SubmissionCreate,
    background_tasks: BackgroundTasks,
    integration: dict = Depends(require_api_key),
):
    submission_id = str(uuid.uuid4())
    create_submission_record(
        submission_id, integration["id"],
        callback_url=body.callback_url, metadata=body.metadata
    )

    background_tasks.add_task(
        _process_submission, submission_id, integration, body
    )

    return {
        "submission_id": submission_id,
        "status": "accepted",
        "estimated_completion": "30-60 seconds",
    }


def _process_submission(submission_id: str, integration: dict, body: SubmissionCreate):
    """Background: parse resume → extract skills → score → select tests → webhook."""
    try:
        # Decode resume
        if body.resume:
            pdf_bytes = base64.b64decode(body.resume)
            path = os.path.join(UPLOAD_DIR, f"sub_{submission_id}.pdf")
            with open(path, "wb") as f:
                f.write(pdf_bytes)
        else:
            update_submission(submission_id, status="failed", error="No resume provided")
            dispatch_webhook(submission_id, "submission.failed", {"error": "No resume provided"})
            return

        update_submission(submission_id, status="processing")

        # Parse
        parsed = parse_resume(path)
        resume_text = parsed["raw_text"]

        # Save candidate
        conn = get_db()
        cur = conn.execute(
            "INSERT INTO candidates (name, email, phone, resume_path, resume_text, parsed_data) VALUES (?,?,?,?,?,?)",
            (body.name, body.email, body.phone or "", path, resume_text, json.dumps(parsed))
        )
        cid = cur.lastrowid

        # Extract & score skills
        skills = extract_skills(resume_text)
        skills = score_confidence(skills, parsed)
        for s in skills:
            conn.execute(
                "INSERT INTO skill_assessments (candidate_id, skill_name, category, evidence, llm_confidence, final_confidence, reasoning) VALUES (?,?,?,?,?,?,?)",
                (cid, s.skill_name, s.category, s.evidence, s.llm_confidence.value, (s.final_confidence or s.llm_confidence).value, s.reasoning)
            )
        conn.commit()

        # Select tests
        tests = select_tests(skills)

        # Run fit assessment
        fit_data = {}
        try:
            skill_dicts = [{"skill_name": s.skill_name, "category": s.category,
                             "llm_confidence": (s.llm_confidence).value,
                             "final_confidence": (s.final_confidence or s.llm_confidence).value} for s in skills]
            active_pos = get_active_position()
            position_profile = None
            if active_pos:
                position_profile = {
                    "name": active_pos.title,
                    "position_id": active_pos.id,
                    "core_skills": [{"name": s.skill_name, "weight": s.weight} for s in active_pos.required_skills],
                    "adjacent_skills": [{"name": s.skill_name, "weight": s.weight} for s in active_pos.preferred_skills],
                }
            fit = assess_fit(skill_dicts, position_profile=position_profile)
            conn.execute(
                "INSERT INTO fit_assessments (candidate_id, fit_score, fit_level, rationale, breakdown_json, assessed_by) VALUES (?,?,?,?,?,?)",
                (cid, fit.fit_score, fit.fit_level, fit.rationale, json.dumps(fit.breakdown), "system")
            )
            conn.commit()
            fit_data = {"fit_score": fit.fit_score, "fit_level": fit.fit_level, "fit_rationale": fit.rationale}
        except Exception:
            pass

        # Build results
        results = {
            "candidate_id": cid,
            "skills": [{"name": s.skill_name, "category": s.category, "confidence": (s.final_confidence or s.llm_confidence).value} for s in skills],
            "recommended_tests": [{"id": t.id, "name": t.name, "category": t.category} for t in tests],
            **fit_data,
        }

        update_submission(submission_id, status="completed", candidate_id=cid, results=json.dumps(results))
        conn.close()

        # Fire webhook
        dispatch_webhook(submission_id, "submission.analyzed", results)

    except Exception as e:
        update_submission(submission_id, status="failed", error=str(e))
        dispatch_webhook(submission_id, "submission.failed", {"error": str(e)})


@app.get("/api/v1/submissions/{submission_id}")
async def v1_get_submission(submission_id: str, integration: dict = Depends(require_api_key)):
    sub = get_submission_record(submission_id)
    if not sub or sub["integration_id"] != integration["id"]:
        raise HTTPException(404, "Submission not found")
    result = {
        "submission_id": sub["id"],
        "status": sub["status"],
        "created_at": sub["created_at"],
        "updated_at": sub["updated_at"],
    }
    if sub["status"] == "completed" and sub["results"]:
        result["results"] = json.loads(sub["results"])
    if sub["status"] == "failed" and sub["error"]:
        result["error"] = sub["error"]
    return result


@app.get("/api/v1/submissions")
async def v1_list_submissions(
    integration: dict = Depends(require_api_key),
    status: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
):
    return list_submission_records(
        integration_id=integration["id"], status=status,
        date_from=date_from, date_to=date_to, limit=limit, offset=offset
    )


# ── Admin Endpoints ──

ADMIN_SECRET = os.environ.get("SR_ADMIN_SECRET", "superrecruit-admin-secret")


async def require_admin(authorization: str = Header(...)):
    # Simple bearer token auth for admin
    if authorization != f"Bearer {ADMIN_SECRET}":
        raise HTTPException(403, "Admin access required")


@app.post("/api/admin/integrations", dependencies=[Depends(require_admin)])
async def admin_create_integration(request: Request):
    body = await request.json()
    name = body.get("name")
    if not name:
        raise HTTPException(400, "name required")
    webhook_url = body.get("webhook_url")
    integration, api_key = create_integration(name, webhook_url)
    return {
        "integration": {k: v for k, v in integration.items() if k != "api_key_hash"},
        "api_key": api_key,
        "warning": "Store this API key securely — it will not be shown again.",
    }


@app.get("/api/admin/integrations", dependencies=[Depends(require_admin)])
async def admin_list_integrations():
    return list_integrations()


@app.delete("/api/admin/integrations/{integration_id}", dependencies=[Depends(require_admin)])
async def admin_revoke_integration(integration_id: int):
    if not revoke_integration(integration_id):
        raise HTTPException(404, "Integration not found")
    return {"ok": True, "message": "Integration revoked"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("src.main:app", host="0.0.0.0", port=8000, reload=True)
