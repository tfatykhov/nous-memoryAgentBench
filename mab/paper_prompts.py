"""Paper-faithful answer prompts, vendored from MemoryAgentBench.

Source: https://github.com/HUST-AI-HYZ/MemoryAgentBench  (utils/templates.py)
License: MIT (c) 2026 Yuanzhe Hu.

The paper's per-sub-dataset 'query' templates (``agentic_memory_agent`` variant,
closest to nous). ``{question}`` is substituted by frame_prompt (literal .replace);
the icl template's ``{label}`` is illustrative text the model should echo, not a
substitution. ``prompt_for_source`` maps a MAB source (e.g. 'eventqa_65536',
'icl_banking77_...', 'factconsolidation_sh_262k') to its template, mirroring the
paper's DATASET_MAPPING.
"""

# --- agentic_memory_agent 'query' templates, verbatim -------------------------
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

PAPER_RULER_QA_PROMPT = (
    "Search Archival Memory and answer my question. Only give me the answer and do "
    "not output any other words. \n\nQuestion: {question} \n\n Answer:"
)

PAPER_LONGMEMEVAL_PROMPT = (
    "Search Archival Memory and answer the question as concisely as you can, using "
    "a single phrase if possible.\n\n {question} \n\n Answer:"
)

PAPER_EVENTQA_PROMPT = (
    "Search Archival Memory, complete the task below:\n\n{question}\n\n The event "
    "that happens next is:"
)

PAPER_ICL_PROMPT = (
    "Search Archival Memory and use the provided mapping from the context to "
    'numerical label to assign a numerical label to the context. Only output '
    '"label: {label}" and nothing else. \n\n{question} \n\n label:'
)

PAPER_RECSYS_PROMPT = (
    "Pretend you are a movie recommender system. You need to recommend movies "
    "based on the dialogues you have memorized. Now I will give you a new "
    "conversation between a user and you (a recommender system). Search Archival "
    "Memory, you reply me with 20 recommendations without extra sentences. "
    "\n\nFor Example:\n\n[Conversation]\n\nThe recommendations are: \n1.movie1\n"
    "2.movie2\n...\n\n Here is the conversation: {question} \n\n The "
    "recommendations are: \n"
)

PAPER_INFBENCH_SUM_PROMPT = (
    "You are given a book above and you are tasked to summarize it. \n\n{question} "
    "\n\n Now summarize the book."
)

PAPER_DETECTIVE_QA_PROMPT = (
    "Search Archival Memory and answer the question below. You are required to "
    "answer the question based on the strict output format.\n\n {question} \n\n"
)

# sub-dataset key -> prompt (mirrors BASE_TEMPLATES)
PROMPT_BY_DATASET = {
    "factconsolidation": PAPER_CR_PROMPT,
    "ruler_qa": PAPER_RULER_QA_PROMPT,
    "longmemeval": PAPER_LONGMEMEVAL_PROMPT,
    "eventqa": PAPER_EVENTQA_PROMPT,
    "in_context_learning": PAPER_ICL_PROMPT,
    "recsys_redial": PAPER_RECSYS_PROMPT,
    "infbench_sum": PAPER_INFBENCH_SUM_PROMPT,
    "detective_qa": PAPER_DETECTIVE_QA_PROMPT,
}


def prompt_for_source(source: str) -> str:
    """Map a MAB source name to its paper answer prompt (mirrors DATASET_MAPPING)."""
    s = source.lower()
    if "icl" in s:
        return PAPER_ICL_PROMPT
    if "eventqa" in s:
        return PAPER_EVENTQA_PROMPT
    if "ruler" in s:
        return PAPER_RULER_QA_PROMPT
    if "longmemeval" in s:
        return PAPER_LONGMEMEVAL_PROMPT
    if "recsys" in s:
        return PAPER_RECSYS_PROMPT
    if "infbench" in s:
        return PAPER_INFBENCH_SUM_PROMPT
    if "detective" in s:
        return PAPER_DETECTIVE_QA_PROMPT
    if "factconsolidation" in s:
        return PAPER_CR_PROMPT
    raise KeyError(f"no paper prompt for source {source!r}")


# backward-compat: (prompt, grader metric) by competency for CR
PAPER_PROMPTS = {
    "conflict_resolution": (PAPER_CR_PROMPT, "paper_substring_exact_match"),
}
