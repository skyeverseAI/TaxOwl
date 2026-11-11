"""Jev (TypeSafe's "System One" model): answers typed questions (yes/no, a choice, a score) with
probabilities, not text. Input tokens cost $0.042 per million; output is free.

Reached through OpenRouter with the usual key: DeepEval's TypeSafeModel -> typesafe_sdk ->
https://openrouter.ai/api/v1/systemone. Used by the retriever judge (evals/retriever_eval.py) and the
withdrawal detector (validity/detect.py). Checked 2026-11-08 (Evaluations/Retriever_Evals/Judge_comparison.md).
"""

JEV_MODEL = "typesafe/jev-1.14"      # pinned version; OpenRouter answers as jev-1.14-20261014
JEV_PRICE = 0.042 / 1e6              # $ per input token; DeepEval doesn't know 1.14's price
OPENROUTER_API = "https://openrouter.ai/api"


def make_jev():
    """DeepEval's TypeSafeModel, pointed at OpenRouter. Call .decide(state, questions)."""
    from deepeval.models import TypeSafeModel  # imported here: only callers that use Jev need deepeval

    from taxowl.ingestion.vlm import load_key  # taxowl's one way to read the OpenRouter key

    key = load_key()
    if not key:
        raise SystemExit("No OPENROUTER_API_KEY in the environment or .env")
    return TypeSafeModel(model=JEV_MODEL, api_key=key, base_url=OPENROUTER_API, cost_per_input_token=JEV_PRICE)
