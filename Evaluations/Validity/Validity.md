# Validity — is the law in an answer still the law? (v1)

**Date:** 2026-11-11 to 2026-11-14 · **Commits:** 2b28c84, 0042cd5, 5cb64fe, 200d9ff, 8f619de, a61ceb0 · **Trap questions:** `eval_results/gold/validity_traps.jsonl` (4, dev)

A circular explains the law on its date. Three things can make it wrong today:

```
 1. another circular withdrew or changed it        → status labels        (corpus has the evidence)
 2. the Act/Rules it explains were amended later   → cited provisions + ⚠ note
 3. a rate changed by a rate notification          → web search            (corpus doesn't hold rate notifications)
```

## 1. Withdrawn / partly modified circulars

**How:** a regex finds sentences like "is hereby withdrawn" / "stands modified" in circular BODIES; an LLM (Jev) judges each hit; a person checks. CBIC's title notes ("withdrawn vide ...") are used only as an answer key, never as evidence (`src/taxowl/validity/detect.py`, `recall.py`).

| measure | value | how checked |
|---|---|---|
| precision (body rows) | **55/59 = 0.93** | every "y" row by Claude; the 4 "n" rows by the user in the PDFs; Codex blind review agreed on all 4 |
| recall (vs CBIC title notes) | **17/19 = 0.89** | withdrawn 13/13; the miss (64/38/2018 changing 41/15 and 49/23) is only in its "Subject:" line |

**Result** (`data/validity/status.json`, snapshot CSVs in `eval_results/validity/`): 36 circulars — 17 withdrawn, 19 partly modified. On chunks: 221 withdrawn, 371 partly modified, 4125 in force. Labels go into chunk metadata and Chroma; nothing is re-embedded.

**In answers:**
- meaning search skips withdrawn chunks; a circular the question NAMES is still returned
- labels: `(WITHDRAWN by Circular X)`, `(partly modified by Circular X)`, plus the document's date
- the prompt says: never present a withdrawn circular as current law

## 2. The Act/Rules changed after the circular

**The trap** (dev-006, dev-018): Circular 123/42/2019 explains rule 36(4)'s old limit (20%, then 10%, 5%); since 01.01.2022 ITC needs the invoice in GSTR-2B. The questions ask what the circular says, so the old circular is the right source, but the answer must say the rule changed.

**Scope:** 71 of 247 non-withdrawn circulars cite a CGST rule amended after their date (rule level, so an upper bound).

What we tried, in order:

| step | change | dev-006 / dev-018 result |
|---|---|---|
| 0 | nothing | current rule 36(4) not retrieved (not in the meaning top 300: "ITC limit" vs the rule's wording) |
| 1 | **cited provisions** (8f619de): the retriever reads the citations in returned circulars, follows the top 3 to their current text (4 chunks), label `(CURRENT TEXT of the provision explained by Circular X)` | rule 36(4) retrieved ([S19], [S11]); **model ignores it** |
| 2 | **AMENDED label** + "you must say" prompt rule (`validity/amended.py`): footnote dates on 751 of 1534 Act/Rules chunks, label `(AMENDED on 2022-01-01, AFTER Circular X dated ...)` | **model still silent** |
| 3 | **⚠ note by code** (a61ceb0, `pipeline.amended_note()`), like `rate_note` | note shown under both answers |

Cited provisions on the retriever dev set (`retriever_full_20261113_131523.json`): hit@5 0.875 (same), MRR 0.649 → 0.653, hit@all 0.875 → 0.906, recall@all 0.833 → 0.888.

**Amendment dates** come from the footnotes the splitter already keeps:
- CGST/IGST Rules, IGST/UTGST Acts (ICAI): the note gives the new words, so the date goes only on the chunk that holds them ("text" level; 352 chunks)
- CGST Act (India Code): no words, so every chunk of the section gets every date ("section" level; 399 chunks)
- date of a change = later of "w.e.f." and "dated" (a retrospective change still came after the circular)
- spot check: 6 random "text" chunks, all dates match their footnotes

**The note's filters** (so it doesn't cry wolf): only "text"-level dates; only circulars the ANSWER cites, and only dates after that circular; never a withdrawn circular.

## 3. Rates

Rates live in rate notifications, which the corpus doesn't hold (GST 2.0 changed many on 22 Sep 2025). A rate question also gets 4 web results (Tavily, past year only, no site list) as `WEB` sources; if the search fails, our code adds a note that the documents' rate may be old (`answer/web.py`). Free DuckDuckGo search was tried first and was rate-limited.

## Trap results (final run `eval_results/runs/traps_20261114_020711.json`)

Judged by Claude and Codex separately (Codex prompt: answer must be correct, faithful to the cited text, not stale, cited); disagreements settled below.

| id | trap | ok | why |
|---|---|---|---|
| dev-006 | rule 36(4) changed after 142/12/2020 | **y** | quote matches [S3] word for word; ⚠ note points to current rule 36(4) |
| dev-014 | (retrieval) | **n** | gold 159/15/2021 para 3.6 not retrieved; refusal honest (Codex: y on that ground) |
| dev-018 | rule 36(4) changed after 123/42/2019 | **n** | answer leads with present-tense "No, ... does not restrict" from the 2019 circular; the note warns but the headline stays old (caught by Codex) |
| dev-029 | rate changed in 2025 | **n** | gives circular 12% (2021) and web 5% now, but the question asks CGST and the answer never gives the CGST half; web 5% has no [S#]; answered in English |

**1 of 4.** The validity machinery works where code decides (labels, filters, notes); it fails where the model must reason about time.

## Limitations (v1)

- **The model doesn't reason about dates.** Given the old circular and the current rule side by side, gpt-4o-mini answers from the circular. The ⚠ note warns but doesn't rewrite the answer (dev-018).
- **Note noise:** a whole rule in one chunk (rule 21) gets every date, even if the clause a circular explains never changed. So the note says "may be out of date", not "is wrong".
- **CGST Act changes never get a note:** their dates are per section only.
- **5 footnotes** had no date the regex could read.
- **Detector miss:** changes stated only in a circular's "Subject:" line (64/38/2018).
- **Transitional provisions** (CGST 139–142, UTGST 18–20) are not tagged as historical (v1.1).
- **Web rates** are only as good as the sites; claims from them sometimes carry no [S#] (generator eval).
- 4 trap questions is a small set: these results show behaviour, not a rate.

## v1.1

Rewrite the answer itself when a cited circular is stale (a second model pass, or put the current rule first); clause-level dates for whole-rule chunks; transitional tag; "Subject:" line in the detector; a bigger trap set.
