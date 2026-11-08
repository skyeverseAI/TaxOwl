# Cross-check: Codex's pool, checked by Claude

File checked: `eval_results/gold/retriever_dev.jsonl` (Codex, 40 rows, written with the first version of Prompt A:
exact 8 / plain 16 / hinglish 8 / none 8, ids `dev-…`). Treated as Codex's pool; at merge time `plain` becomes `scenario`.
Checked 2026-11-08 against `data/chunks.jsonl`: gold ids, claims vs gold text, completeness, category, "none" rows
searched in the corpus. Not checked here: the PDFs (Codex's PDF check runs on Claude's pool only).

Mechanical checks: 40 rows, every gold id exists, no section/rule/circular in more than 2 rows, 8 table golds.

## Per row

| id | verdict | what | suggested fix |
|---|---|---|---|
| dev-001 | OK | duplicate of claude-001 (same chunk, same question) | keep one at merge |
| dev-002 | OK | duplicate of claude-006; misses the transporter proviso (minor) | keep one at merge |
| dev-003 | OK | | |
| dev-004 | OK | | |
| dev-005 | PROBLEM | completeness: rule 3 applies only to advertisement services to the Central/State Government, a statutory body or a local authority, and only when no contract fixes the State-wise value. The claims miss this condition, which a CA would quote | add a claim with that condition |
| dev-006 | PROBLEM | validity: Circular 142/12/2020 shows the old cumulative rule 36(4) calculation (the 10% extra credit, Feb–Aug 2020). That version of rule 36(4) no longer exists. The table text is also scrambled (2,695 sits in the Feb row) | drop, or keep aside for the validity-trap set |
| dev-007 | OK | | |
| dev-008 | WEAK | question copies the chunk's words ("personal consumption"); a one-word lookup, tests little | rephrase as a situation, or drop |
| dev-009 | OK | | |
| dev-010 | OK | | |
| dev-011 | OK | | |
| dev-012 | OK | | |
| dev-013 | OK | | |
| dev-014 | PROBLEM | validity: Circular 159/15/2021 explains intermediary services under section 13(8)(b) of the IGST Act, which was omitted by the Finance Act, 2026 w.e.f. 30.03.2026 (user saw the footnote in the ICAI PDF, 2026-11-08) | drop, or keep aside for the validity-trap set |
| dev-015 | OK | | |
| dev-016 | OK | duplicate of claude-019 (same table row, same situation) | keep one at merge |
| dev-017 | OK | | |
| dev-018 | PROBLEM | validity: Circular 123/42/2019 explains the old rule 36(4) (the 20% limit, credit after 09.10.2019). The idea that import IGST, RCM and ISD credit fall outside 36(4) may still hold under today's rule, but the source is for a version that's gone | drop, or keep aside for the validity-trap set |
| dev-019 | PROBLEM | category: the question is in Hinglish but labelled `plain` | relabel `hinglish` |
| dev-020 | OK | | |
| dev-021 | OK | completeness, minor: the same para also says no adjustment/withholding of a provisional amount, and no provisional refund when an earlier claim's issue is pending | optional: add one claim |
| dev-022 | OK | | |
| dev-023 | OK | | |
| dev-024 | OK | | |
| dev-025 | OK | | |
| dev-026 | OK | | |
| dev-027 | OK | | |
| dev-028 | OK | | |
| dev-029 | PROBLEM | (1) the question says "Table mein…", which needs the reader to already know the document; (2) source is Circular 130/2019, the copy with no date and no full number that may not be a final version (noted on 2026-11-06) | drop, or rephrase without "table" and add a note |
| dev-030 | OK | the table text of 251/08/2025 is scrambled in the chunk, but this claim's words are there | |
| dev-031 | OK | | |
| dev-032 | OK | | |
| dev-033 | OK | none: nothing in the corpus on a search's constitutional validity | |
| dev-034 | PROBLEM | none, but the corpus touches it: 113/32/2019 (namkeen classification, 2106 90), 235/29/2024 (snack pellets as namkeens), 247/04/2025 ("12% GST if sold as packaged and labelled" for namkeen-like popcorn). A model could half-answer from these | replace with a rate question the corpus never touches |
| dev-035 | OK | none | |
| dev-036 | OK | none (Maharashtra appears only inside an illustration in 133/03/2020) | |
| dev-037 | OK | none | |
| dev-038 | PROBLEM | none, but the corpus has the Compensation Cess schedule (cgst-rules-2017-table-16:2): motor cars, 8703, maximum cess 25% ad valorem. Not the actual rate, but close enough to mislead | replace, or turn into an answerable row about the maximum rate |
| dev-039 | OK | none | |
| dev-040 | OK, note | none for the AAR ruling, but 164/20/2021 para 3.4 covers cloud kitchens (restaurant service, 5% without ITC). A good test: the answer should say the AAR ruling isn't held, then may cite the circular | keep |

## Summary

- OK: 31 (3 of them duplicates of Claude's rows: dev-001, 002, 016) · weak: 1 (dev-008) · problem: 8 (dev-005, 006, 014, 018, 019, 029, 034, 038)
- Validity traps found: dev-006 and dev-018 (old rule 36(4)), dev-014 (section 13(8)(b) omitted from 30.03.2026). Same as Claude's own note on 123/42/2019. Keep them for the validity-status step.
- Codex has no `multi` category (old prompt), so all multi rows come from Claude's pool.
