# Next-Stage Evaluation Plan

This document tracks the engineering hooks added for the next-stage features.

## Role-Based Admin Access

Implemented as optional HTTP Basic Auth:

- `viewer`: read profiles and personas.
- `caregiver`: update profiles, personas, notes, biography, and review monitoring data.
- `admin`: caregiver permissions plus session management.

Configure either the simple pair:

```env
ADMIN_USERNAME=admin
ADMIN_PASSWORD=change-me
ADMIN_ROLE=admin
```

or multiple users:

```env
ADMIN_USERS={"caregiver1":{"password":"change-me","role":"caregiver"},"supervisor":{"password":"change-me-too","role":"admin"}}
```

## Session Isolation and Cleanup

Available endpoints:

- `GET /api/admin/sessions`
- `POST /api/admin/sessions/clear`

These expose active `elder_id`, `session_id`, `persona_id`, `chat_count`, and `last_seen`.

## Long-Term Memory RAG Evaluation

Endpoint:

```text
POST /api/admin/rag/evaluate
```

Example request:

```json
{
  "elder_id": "W001",
  "queries": [
    {"query": "豆漿很好喝", "expected": ["豆漿"]},
    {"query": "我頭很暈快跌倒了", "expected": ["跌倒", "頭暈"]}
  ]
}
```

The response reports hit rate and retrieved memories.

## Taiwanese STT Corpus Evaluation

Endpoint:

```text
POST /api/admin/stt/evaluate-transcripts
```

Example request:

```json
{
  "samples": [
    {
      "id": "tai-001",
      "reference": "阿嬤今仔日有食飯無",
      "hypothesis": "阿嬤今仔日有食飯無"
    }
  ]
}
```

The response reports normalized transcripts and character error rate.
