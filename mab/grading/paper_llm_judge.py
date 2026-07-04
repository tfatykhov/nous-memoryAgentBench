"""Paper-faithful LLM judge, vendored from MemoryAgentBench.

Source: https://github.com/HUST-AI-HYZ/MemoryAgentBench  (llm_based_eval/longmem_qa_evaluate.py)
License: MIT (c) 2026 Yuanzhe Hu.

longmemeval (AR) is scored by a yes/no LLM judge (paper default model: gpt-4o),
NOT by string matching: given (question, gold, model_response, task-type), a judge
LLM answers "yes"/"no" and correct == "yes" in the reply. ``get_anscheck_prompt``
is the paper's exact per-task template. The OpenAI call is made via httpx (no
extra deps); the completer is injectable so tests run offline.

(infbench_sum summarization uses a heavier 3-call fluency/recall/precision judge —
not yet vendored here; see NEEDS in the module docstring of paper_grader.)
"""

from __future__ import annotations

from typing import Awaitable, Callable

import httpx

from mab.grading.graders import GradeResult

Completer = Callable[[str, str], Awaitable[str]]  # (prompt, model) -> reply text


# --- verbatim from longmem_qa_evaluate.py -------------------------------------
def get_anscheck_prompt(task: str, question: str, answer: str, response: str, abstention: bool = False) -> str:
    if not abstention:
        if task in ["single-session-user", "single-session-assistant", "multi-session"]:
            template = "I will give you a question, a correct answer, and a response from a model. Please answer yes if the response contains the correct answer. Otherwise, answer no. If the response is equivalent to the correct answer or contains all the intermediate steps to get the correct answer, you should also answer yes. If the response only contains a subset of the information required by the answer, answer no. \n\nQuestion: {}\n\nCorrect Answer: {}\n\nModel Response: {}\n\nIs the model response correct? Answer yes or no only."
        elif task == "temporal-reasoning":
            template = "I will give you a question, a correct answer, and a response from a model. Please answer yes if the response contains the correct answer. Otherwise, answer no. If the response is equivalent to the correct answer or contains all the intermediate steps to get the correct answer, you should also answer yes. If the response only contains a subset of the information required by the answer, answer no. In addition, do not penalize off-by-one errors for the number of days. If the question asks for the number of days/weeks/months, etc., and the model makes off-by-one errors (e.g., predicting 19 days when the answer is 18), the model's response is still correct. \n\nQuestion: {}\n\nCorrect Answer: {}\n\nModel Response: {}\n\nIs the model response correct? Answer yes or no only."
        elif task == "knowledge-update":
            template = "I will give you a question, a correct answer, and a response from a model. Please answer yes if the response contains the correct answer. Otherwise, answer no. If the response contains some previous information along with an updated answer, the response should be considered as correct as long as the updated answer is the required answer.\n\nQuestion: {}\n\nCorrect Answer: {}\n\nModel Response: {}\n\nIs the model response correct? Answer yes or no only."
        elif task == "single-session-preference":
            template = "I will give you a question, a rubric for desired personalized response, and a response from a model. Please answer yes if the response satisfies the desired response. Otherwise, answer no. The model does not need to reflect all the points in the rubric. The response is correct as long as it recalls and utilizes the user's personal information correctly.\n\nQuestion: {}\n\nRubric: {}\n\nModel Response: {}\n\nIs the model response correct? Answer yes or no only."
        else:
            raise NotImplementedError(f"unknown longmemeval task {task!r}")
    else:
        template = "I will give you an unanswerable question, an explanation, and a response from a model. Please answer yes if the model correctly identifies the question as unanswerable. The model could say that the information is incomplete, or some other information is given but the asked information is not.\n\nQuestion: {}\n\nExplanation: {}\n\nModel Response: {}\n\nDoes the model correctly identify the question as unanswerable? Answer yes or no only."
    return template.format(question, answer, response)


class LongmemJudge:
    """longmemeval yes/no judge. ``completer`` is an async (prompt, model)->reply."""

    metric = "paper_longmem_llm_judge"

    def __init__(self, completer: Completer, model: str = "gpt-4o"):
        self._complete = completer
        self.model = model

    async def judge(
        self, question: str, gold: str, answer: str, task: str, abstention: bool = False
    ) -> GradeResult:
        prompt = get_anscheck_prompt(task, question, gold, answer, abstention)
        reply = await self._complete(prompt, self.model)
        correct = "yes" in reply.lower()
        return GradeResult(correct, gold if correct else None, f"llm judge[{task}]: {reply.strip()[:16]}")


def openai_completer(api_key: str, client: httpx.AsyncClient) -> Completer:
    """Build a Completer that calls the OpenAI chat API (temperature 0)."""

    async def _complete(prompt: str, model: str) -> str:
        r = await client.post(
            "https://api.openai.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {api_key}"},
            json={"model": model, "messages": [{"role": "user", "content": prompt}], "temperature": 0},
            timeout=60.0,
        )
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"]

    return _complete
