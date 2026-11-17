# Codex prompt: claims for the generator golden set

Written 2026-11-17. Why: the generator eval's Completeness checks the gold claims against the answer.
In the first run (generator_cloud_20261117_103803), some claims of retriever_dev.jsonl asked for more
than the question did (codex-004: registered recipients; claude-015: capital goods), so a correct,
focused answer lost points. Same 40 questions and gold chunks, so the pipeline eval can compare
retriever (ContextualRecall) and generator (Completeness) on the same rows.

```text
TASK: Rewrite the "claims" of a golden set for a GENERATOR eval (taxowl, a GST-law RAG).

INPUT
- eval_results/gold/retriever_dev.jsonl : 40 rows {id, category, question, gold_chunks, claims, note, source, split}
- data/chunks.jsonl : every chunk {chunk_id, text, ...}. Look up each gold_chunks id here.

OUTPUT
- eval_results/gold/generator_dev.jsonl : the same 40 rows, same order, same id/category/
  question/gold_chunks/note/source/split. Only these change or are added:
    "claims"         : the new claims (list of strings)
    "claim_quotes"   : one list per claim: the exact words from the gold chunk text that
                       support it (copied character for character, so code can find them)
    "claims_dropped" : old claims you removed, each {"claim": ..., "why": ...}
- Do not edit any other file.

WHAT A CLAIM IS
The generator gets ONLY the gold chunks and must answer the question. A claim is one fact a
correct, short answer (about 150 words) MUST contain. A judge will check each claim against the answer.

RULES
1. Answer only what the question asks. If the question asks about unregistered customers, do
   not add the rule for registered ones. If it asks about inputs, not capital goods, leave capital goods out.
2. Every claim must be stated in the gold chunk text. Nothing from outside knowledge.
3. Keep a condition, proviso or exception only if leaving it out would make the answer to THIS
   question wrong or misleading.
4. One fact per claim. Short, plain English, even when the question is in Hinglish.
5. No section/rule numbers inside a claim, unless the question asks which provision applies.
   (Citations are checked separately: [S#] labels and check.py.)
6. Usually 1-4 claims. Fewer is fine. Don't pad.
7. Category "none" rows: claims stay [], claim_quotes [], claims_dropped [].
8. If the gold chunks do NOT answer the question at all, keep the old claims and put
   "PROBLEM: <why>" in claims_dropped. Don't guess.

EXAMPLE 1 (rule 1)
 question: "What place of supply does section 12(8) of the IGST Act set for goods transport to an
            unregistered customer?"
 old claims: ["For a registered recipient, the place of supply is that recipient's location.",
              "For an unregistered recipient, it is where the goods are handed over for transportation."]
 new claims: ["For an unregistered recipient, the place of supply is the location where the goods
              are handed over for transportation."]
 claims_dropped: [{"claim": "For a registered recipient...", "why": "question asks only about unregistered"}]

EXAMPLE 2 (rule 3)
 question: "Main doosre state mein ek mahine ki exhibition mein stall laga raha hoon. Wahan ka temporary
            registration kitne din chalega, aur kya pehle se tax jama karna padega?"
 keep: validity = period in the application or 90 days, whichever is earlier; extendable by up to 90 days;
       advance deposit of estimated tax at the time of applying.
 "taxable supplies only after the certificate is issued": your call under rule 3, write why.

When done, print a table: id | old claim count | new claim count | dropped count | any PROBLEM.
```

## After Codex

1. `git diff --stat eval_results/gold/retriever_dev.jsonl` must be empty.
2. Claude checks every claim_quotes entry is an exact substring of its gold chunk (code, no LLM),
   then reads each row blind: in the chunk? asked by the question? Disagreements go to the user.
3. Rerun: `generator_eval --gold eval_results/gold/generator_dev.jsonl --which cloud --judge`.

Later (v1.1): a free code check "does the answer text name the provision?", kept apart from Completeness.
