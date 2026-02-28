# SuperRecruit Integration Specification

## Overview

The SuperRecruit Integration API allows external ATS platforms, job boards, and HR tools to submit candidates for automated resume analysis, skill extraction, and assessment selection.

**Base URL:** `https://your-instance.com/api/v1`

---

## Authentication

All `/api/v1/` endpoints require an API key passed in the `X-API-Key` header.

```
X-API-Key: sr_live_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
```

API keys are provisioned by a SuperRecruit admin via the admin API. Keys are shown once at creation and cannot be retrieved later.

**Error responses:**
- `401 Unauthorized` — Invalid or revoked API key
- `422 Unprocessable Entity` — Missing `X-API-Key` header

---

## Endpoints

### Submit a Candidate

**`POST /api/v1/submissions`**

Submit a candidate with resume for analysis. Processing happens asynchronously.

**Request body (JSON):**

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `name` | string | ✅ | Candidate full name |
| `email` | string | ✅ | Candidate email |
| `phone` | string | ❌ | Phone number |
| `resume` | string | ✅ | Base64-encoded PDF resume |
| `metadata` | object | ❌ | Arbitrary key-value data for your integration |
| `callback_url` | string | ❌ | Webhook URL for this submission (overrides integration default) |

**Response (200):**

```json
{
  "submission_id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "accepted",
  "estimated_completion": "30-60 seconds"
}
```

### Get Submission Status

**`GET /api/v1/submissions/{submission_id}`**

Poll for results. Returns full results when `status` is `"completed"`.

**Response (200):**

```json
{
  "submission_id": "550e8400-...",
  "status": "completed",
  "created_at": "2026-02-28T13:00:00",
  "updated_at": "2026-02-28T13:00:45",
  "results": {
    "candidate_id": 42,
    "skills": [
      {"name": "Python", "category": "language", "confidence": 0.92},
      {"name": "React", "category": "framework", "confidence": 0.78}
    ],
    "recommended_tests": [
      {"id": "python-advanced", "name": "Python Advanced", "category": "language"}
    ],
    "fit_score": 0.82,
    "fit_level": "strong",
    "fit_rationale": "Strong Python and SQL skills align well with backend requirements."
  }
}
```

**Status values:** `accepted` → `processing` → `completed` | `failed`

### List Submissions

**`GET /api/v1/submissions`**

**Query parameters:**

| Param | Type | Description |
|-------|------|-------------|
| `status` | string | Filter by status |
| `date_from` | string | ISO date, inclusive |
| `date_to` | string | ISO date, inclusive |
| `limit` | int | Max results (default 50) |
| `offset` | int | Pagination offset |

Results are scoped to your integration — you cannot see other integrations' submissions.

---

## Webhook Events

Webhooks are sent as `POST` requests with JSON payload when key events occur.

### Payload Format

```json
{
  "event": "submission.analyzed",
  "submission_id": "550e8400-...",
  "timestamp": "2026-02-28T13:00:45.123Z",
  "data": { ... }
}
```

### Events

| Event | Trigger | Data |
|-------|---------|------|
| `submission.analyzed` | Resume parsed, skills extracted, tests selected | `{ candidate_id, skills, recommended_tests, fit_score, fit_level, fit_rationale }` |
| `submission.failed` | Processing error | `{ error }` |
| `assessment.sent` | Assessment email sent to candidate | `{ candidate_id, token }` |
| `assessment.completed` | Candidate completed assessment | `{ candidate_id, session_id, scores }` |

### Webhook URL Resolution

1. Per-submission `callback_url` (if provided in the submission request)
2. Integration default `webhook_url` (set at integration creation)
3. If neither is set, no webhook is fired

### Retry Policy

- Up to **3 attempts** per event
- Exponential backoff: immediate → 5s → 25s
- A 2xx response is considered successful
- All attempts are logged in the system

---

## Error Codes

| Status | Meaning |
|--------|---------|
| 200 | Success |
| 400 | Bad request (missing/invalid fields) |
| 401 | Invalid or revoked API key |
| 403 | Admin auth required |
| 404 | Resource not found (or not accessible to your integration) |
| 422 | Validation error |
| 500 | Internal server error |

---

## Rate Limits

> **TODO:** Rate limiting is planned but not yet enforced. We recommend keeping submissions under 100/minute per integration.

---

## Example Integration Flow

1. **Admin creates integration:**
   ```
   POST /api/admin/integrations
   Authorization: Bearer <admin-secret>
   {"name": "AcmeATS", "webhook_url": "https://acme.com/hooks/superrecruit"}
   ```
   → Receives API key (store securely!)

2. **ATS submits candidate:**
   ```
   POST /api/v1/submissions
   X-API-Key: sr_live_xxxxx
   {"name": "Jane Doe", "email": "jane@example.com", "resume": "<base64>"}
   ```
   → Gets `submission_id`

3. **SuperRecruit processes in background** (~30-60s):
   - Parses resume PDF
   - Extracts skills via LLM
   - Scores confidence
   - Selects recommended assessments

4. **Webhook fires** to `https://acme.com/hooks/superrecruit`:
   ```json
   {
     "event": "submission.analyzed",
     "submission_id": "...",
     "timestamp": "...",
     "data": { "candidate_id": 42, "skills": [...], "recommended_tests": [...] }
   }
   ```

5. **Or poll for results:**
   ```
   GET /api/v1/submissions/{submission_id}
   X-API-Key: sr_live_xxxxx
   ```

---

## Admin API

Admin endpoints use `Authorization: Bearer <SR_ADMIN_SECRET>` header.

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/admin/integrations` | POST | Create integration (returns API key once) |
| `/api/admin/integrations` | GET | List all integrations |
| `/api/admin/integrations/{id}` | DELETE | Revoke an integration's access |
