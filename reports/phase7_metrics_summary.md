# Phase 7 Poster Metrics

- Generated at: 2026-06-07 23:47:03
- Environment: Windows / local TestClient / Gemini key present; actual route may still use local fallback
- Chat sample count: 18
- Comparable chat rows: 18

## Chat Latency

| Metric | Median |
|--------|--------|
| iSafe analysis | 1 ms |
| MagicAI generation | 2 ms |
| Chat end-to-end | 2 ms |
| Simulated sequential | 3 ms |
| Parallel saved time | 1 ms |

## RAG Hit-Rate

- Overall: 2/9 (22%)

| Elder | Hits | Total | Hit-rate |
|-------|------|-------|----------|
| W001 | 2 | 3 | 67% |
| C001 | 0 | 3 | 0% |
| L001 | 0 | 3 | 0% |

## Notes

- Level 3 emergency fast-path rows should be reported separately if used; this run focuses on parallel iSafe/MagicAI responses.
- Chat metrics use a temporary elder profile to avoid modifying demo data.
- RAG metrics read existing demo memories without writing profile data.
