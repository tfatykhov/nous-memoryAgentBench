"""Paper-faithful answer prompts, vendored from MemoryAgentBench.

Source: https://github.com/HUST-AI-HYZ/MemoryAgentBench  (utils/templates.py)
License: MIT (c) 2026 Yuanzhe Hu.

These are the paper's per-competency 'query' templates (the ``agentic_memory_agent``
variant, closest to nous — a memory system with retrieval). They differ sharply
from our DEFAULT_ANSWER_INSTRUCTION: the paper GIVES the conflict-resolution rule
(newest = larger serial number), forbids using real-world knowledge, includes a
few-shot example, and forbids abstention ("concise answer, no other words").
``{question}`` is substituted by frame_prompt (literal .replace).
"""

# factconsolidation -> Conflict Resolution (agentic_memory_agent)
PAPER_CR_PROMPT = (
    "Pretend you are a knowledge management system. Each fact in the  Archival "
    "Memory is provided with a serial number at the beginning, and the newer fact "
    "has larger serial number. \n You need to solve the conflicts of facts in the "
    "Archival Memory by finding the newest fact with larger serial number. You "
    "need to answer a question based on this rule. You should give a very concise "
    "answer without saying other words for the question **only** from the "
    "knowledge pool you have memorized rather than the real facts in real world. "
    "\n\nFor example:\n\n [Archival Memory] \n\n Question: Based on the Archival "
    "Memory, what is the name of the current president of Russia? \nAnswer: Donald "
    "Trump \n\n Now Answer the Question: Based on the  Archival Memory, {question} "
    "\nAnswer:"
)

# competency key -> (answer prompt, paper grader metric)
PAPER_PROMPTS = {
    "conflict_resolution": (PAPER_CR_PROMPT, "paper_substring_exact_match"),
}
