"""Re-grade persisted nous answers with the 2026 field's LLM-judge protocol.

Infini Memory (arXiv:2606.10677) grades every MemoryAgentBench task except
recsys/summarization with "an LLM-as-Judge protocol using gpt-5, where the
judge assigns a binary correctness judgment based on the question, reference
answer, and model output." The paper publishes NO prompt, so this is a
faithful RECONSTRUCTION of that described protocol (disclosed as such):
question + reference answer(s) + model output -> strict yes/no.

Pure post-processing: reads the committed results JSONLs (dedup, errors and
infbench_sum excluded), judges each answer with gpt-5, writes side-by-side
official-grader vs judge verdicts. No nous runs involved.

Usage: ./.venv/Scripts/python.exe scripts/judge_regrade.py <results.jsonl> [...more]
"""

from __future__ import annotations

import asyncio
import json
import os
import sys

import httpx

JUDGE_MODEL = "gpt-5"
# Reconstructed from the paper's protocol description (no prompt published).
JUDGE_PROMPT = """You are evaluating whether a model's output correctly answers a question, given the reference answer.

Question: {question}

Reference Answer: {reference}

Model Output: {output}

Does the model output contain the correct answer according to the reference? The output may be verbose or phrased differently; judge semantic correctness only. Respond with exactly one word: yes or no."""


def _openai_key() -> str:
    if os.environ.get("OPENAI_API_KEY"):
        return os.environ["OPENAI_API_KEY"]
    for line in open("../nous/.env", encoding="utf-8", errors="ignore"):
        if line.startswith("OPENAI_API_KEY"):
            return line.split("=", 1)[1].strip().strip('"').strip("'")
    raise RuntimeError("no OPENAI_API_KEY")


def _rows(path: str) -> list[dict]:
    """Dedup (keep last), drop errored rows and non-judge sources (infbench)."""
    seen: dict = {}
    for line in open(path, encoding="utf-8"):
        r = json.loads(line)
        seen[(r["source"], r["instance_id"], r.get("qa_pair_id") or r["prompt"][:80])] = r
    return [r for r in seen.values()
            if not r["error"] and "infbench_sum" not in r["source"]]


async def _judge(client: httpx.AsyncClient, key: str, sem: asyncio.Semaphore, r: dict) -> dict:
    prompt = JUDGE_PROMPT.format(
        question=r["prompt"], reference=" | ".join(r["golds"]), output=r["answer"][:4000]
    )
    async with sem:
        for attempt in range(4):
            try:
                resp = await client.post(
                    "https://api.openai.com/v1/chat/completions",
                    headers={"Authorization": f"Bearer {key}"},
                    json={"model": JUDGE_MODEL,
                          "messages": [{"role": "user", "content": prompt}]},
                    timeout=90.0,
                )
                if resp.status_code >= 429:
                    raise httpx.HTTPStatusError("retry", request=resp.request, response=resp)
                resp.raise_for_status()
                reply = resp.json()["choices"][0]["message"]["content"]
                return {**r, "judge_model": JUDGE_MODEL,
                        "judge_correct": "yes" in reply.strip().lower()[:8]}
            except (httpx.HTTPStatusError, httpx.TransportError):
                if attempt == 3:
                    return {**r, "judge_model": JUDGE_MODEL, "judge_correct": None,
                            "judge_error": "judge call failed after retries"}
                await asyncio.sleep(5 * (attempt + 1))


async def main() -> int:
    files = sys.argv[1:]
    if not files:
        print("usage: judge_regrade.py <results.jsonl> [...]", flush=True)
        return 2
    key = _openai_key()
    os.makedirs("reports/judge_regrade", exist_ok=True)
    sem = asyncio.Semaphore(4)
    async with httpx.AsyncClient() as client:
        for path in files:
            rows = _rows(path)
            print(f"[{os.path.basename(path)}] judging {len(rows)} answers with {JUDGE_MODEL}...", flush=True)
            judged = await asyncio.gather(*[_judge(client, key, sem, r) for r in rows])
            out = f"reports/judge_regrade/judge_{os.path.basename(path)}"
            with open(out, "w", encoding="utf-8") as f:
                for r in judged:
                    f.write(json.dumps(r) + "\n")
            by: dict[str, list[int]] = {}
            for r in judged:
                if r["judge_correct"] is None:
                    continue
                b = by.setdefault(r["source"], [0, 0, 0])
                b[0] += 1 if r["correct"] else 0          # official grader
                b[1] += 1 if r["judge_correct"] else 0    # gpt-5 judge
                b[2] += 1
            for s in sorted(by):
                o, j, n = by[s]
                print(f"  {s:<32} official {o}/{n}={o / n:.3f}  gpt5-judge {j}/{n}={j / n:.3f}  "
                      f"delta {100 * (j - o) / n:+.1f}pp", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
