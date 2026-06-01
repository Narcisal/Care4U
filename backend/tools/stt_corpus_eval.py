import re


_PUNCT = re.compile(r"[\s，。！？、,.!?;；：:\"'「」『』（）()]+")


def normalize_transcript(text: str) -> str:
    """Normalize Mandarin/Taiwanese transcripts for rough comparison."""
    value = str(text or "").lower()
    value = value.replace("台語", "臺語")
    value = _PUNCT.sub("", value)
    return value.strip()


def char_error_rate(reference: str, hypothesis: str) -> float:
    ref = normalize_transcript(reference)
    hyp = normalize_transcript(hypothesis)
    if not ref:
        return 0.0 if not hyp else 1.0

    prev = list(range(len(hyp) + 1))
    for i, rc in enumerate(ref, start=1):
        curr = [i]
        for j, hc in enumerate(hyp, start=1):
            cost = 0 if rc == hc else 1
            curr.append(min(
                prev[j] + 1,
                curr[j - 1] + 1,
                prev[j - 1] + cost,
            ))
        prev = curr
    return round(prev[-1] / len(ref), 3)


def evaluate_transcripts(samples: list[dict]) -> dict:
    """Evaluate prepared STT transcript samples.

    Sample format:
    {
      "id": "tai-001",
      "reference": "阿嬤今仔日有食飯無",
      "hypothesis": "阿嬤今仔日有食飯無"
    }
    """
    rows = []
    total_cer = 0.0
    for sample in samples:
        cer = char_error_rate(sample.get("reference", ""), sample.get("hypothesis", ""))
        total_cer += cer
        rows.append({
            "id": sample.get("id", ""),
            "reference": sample.get("reference", ""),
            "hypothesis": sample.get("hypothesis", ""),
            "normalized_reference": normalize_transcript(sample.get("reference", "")),
            "normalized_hypothesis": normalize_transcript(sample.get("hypothesis", "")),
            "cer": cer,
        })

    total = len(rows)
    return {
        "total": total,
        "average_cer": round(total_cer / total, 3) if total else 0.0,
        "rows": rows,
    }
