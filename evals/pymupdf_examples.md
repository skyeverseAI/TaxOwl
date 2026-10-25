# PyMuPDF tables without Gemini: 5 examples

What `uv run python -m taxowl.extract` gives today (from `data/extracted/`), next to the page image, so the two can be compared by eye. Each table is shown as stored: `headings` as the header row, then `rows`, with the page each row is on.

## 1. 179/11/2022 p.4

- PDF: `docs/circulars/2022/179-11-2022-GST.pdf`, page 4
- Page image: `evals/heldout_pages_2028/02-table-179-11-2022-GST-p4.png`
- What went wrong: Shaded boxes behind each line read as grid lines: 3 x 3 table became 5 columns x 6 rows.

**179/11/2022-GST:table-1**: 5 columns, 6 rows on these pages

| page | Column 1 | Entry and notification No. | Entry and notification | Description | GST Rate |
|---|---|---|---|---|---|
| 4 | S. No. 102 of notification No. 2/2017-Central Tax (Rate), dated the 28th June, 2017 | S. No. 102 of notification |  | Aquatic feed including shrimp feed and prawn feed, poultry feed & cattle feed, including grass, hay & straw, supplement & husk of pulses, concentrates & additives, wheat bran & de-oiled cake[other than rice bran] | Nil |
| 4 | S. No. 102 of notification No. 2/2017-Central Tax (Rate), dated the 28th June, 2017 | No. 2/2017-Central Tax |  | Aquatic feed including shrimp feed and prawn feed, poultry feed & cattle feed, including grass, hay & straw, supplement & husk of pulses, concentrates & additives, wheat bran & de-oiled cake[other than rice bran] | Nil |
| 4 | S. No. 102 of notification No. 2/2017-Central Tax (Rate), dated the 28th June, 2017 | (Rate), dated the 28th |  | Aquatic feed including shrimp feed and prawn feed, poultry feed & cattle feed, including grass, hay & straw, supplement & husk of pulses, concentrates & additives, wheat bran & de-oiled cake[other than rice bran] | Nil |
| 4 | S. No. 102 of notification No. 2/2017-Central Tax (Rate), dated the 28th June, 2017 | June, 2017 |  | Aquatic feed including shrimp feed and prawn feed, poultry feed & cattle feed, including grass, hay & straw, supplement & husk of pulses, concentrates & additives, wheat bran & de-oiled cake[other than rice bran] | Nil |
| 4 | S. No. 103A of Schedule- I of notification No. 1/2017-Central Tax (Rate), dated 28th June, 2017 | June, 2017 |  | Bran, sharps and other residues, whether or not in the form of pellets, derived from the sifting, milling or other working of cereals or of leguminous plants [other than aquatic feed including shrimp feed and prawn feed, poultry feed and cattle feed, including grass, hay and straw, supplement and husk of pulses, concentrates and additives, wheat bran and de-oiled cake] | 5% |
| 4 | S. No. 103B of Schedule- I of notification No. 1/2017-Central Tax (Rate), dated 28th June, 2017 | June, 2017 |  | Rice bran (other than de-oiled rice bran) | 5% |

## 2. 98/17/2019 p.2

- PDF: `docs/circulars/2019/98-17-2019-GST.pdf`, page 2
- Page image: `evals/heldout_pages_2031/04-table-98-17-2019-GST-p2.png`
- What went wrong: Coloured cells read as grid lines: 4- and 3-column tables became 9 and 12 columns.

**98/17/2019-GST:table-1**: 12 columns, 6 rows on these pages

| page | Column 1 | Input tax Credit on | Input tax | Input tax | Output liability on account of | Output liability | Output liability | Output liability on account of | Output liability | Output liability | Output liability on account of State tax / Union | Output liability on account |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 2 |  | account of |  |  | Integrated tax |  |  | Central tax |  |  | Territory tax |  |
| 2 | Integrated tax | account of |  |  | (I) |  |  | (II) – In any order and in any proportion |  |  | Territory tax |  |
| 2 | (III) Input tax Credit on account of Integrated tax to be completely exhausted mandatorily |  |  |  |  |  |  |  |  |  |  |  |
| 2 | Central tax |  |  |  | (V) |  |  | (IV) |  |  | Not permitted |  |
| 2 | State tax / Union Territory tax |  |  |  | (VII) |  |  | Not permitted |  |  | (VI) |  |
| 2 | State tax / Union Territory tax |  |  |  | (VII) |  |  | Not permitted |  |  | (VI) |  |

**98/17/2019-GST:table-2**: 9 columns, 4 rows on these pages

| page | Column 1 | Head | Head | Head | Output Liability | Output Liability | Output Liability | Input tax Credit | Input tax Credit |
|---|---|---|---|---|---|---|---|---|---|
| 2 | Integrated tax | Head |  |  | 1000 |  |  | 1300 |  |
| 2 | Central tax | Head |  |  | 300 |  |  | 200 |  |
| 2 | State tax / Union Territory tax | Head |  |  | 300 |  |  | 200 |  |
| 2 | Total | Head |  |  | 1600 |  |  | 1700 |  |

## 3. 170/02/2022 p.6-7

- PDF: `docs/circulars/2022/170-02-2022-GST.pdf`, page 6, 7
- Page image: `evals/heldout_pages_2031/03-table-170-02-2022-GST-p7.png`
- What went wrong: Table over a page break: all of p.7's rows glued into p.6's last row.

**170/02/2022-GST:table-2**: 5 columns, 7 rows on these pages

| page | 4. Eligible ITC Details | 4. Eligible ITC IGST | 4. Eligible ITC CGST | 4. Eligible ITC SGST/ UTGST | 4. Eligible ITC Explanation |
|---|---|---|---|---|---|
| 6 | (A) ITC Available (whether in full or part) | ---- | ---- | ---- |  |
| 6 | 1. Import of Goods | 1,00,000 | ---- | ---- |  |
| 6 | 2. Import of Services | 50,000 | ---- | ---- |  |
| 6 | 3. Inward Supplies liable to Reverse Charge (other than 1 & 2 above) | ---- | 25,000 | 25,000 |  |
| 6 | 4. Inward Supplies from ISD | 50,000 | ---- | ---- |  |
| 6 | 5. All other ITC | 2,00,000 | 1,50,000 | 1,50,000 |  |
| 6 | (B) ITC Reversed / Reduced 1. Reversal of ITC as per rule 42 and 43 of CGST Rules 2. Others (C) Net ITC Available (A)-(B) (D) Ineligible ITC 1. As per section 17(5) 2. Others | ---- 125,500 10,000 2,64,500 - | ---- 52,000 500 122500 - 10,000 | ---- 52,000 500 122500 - 10,000 | 1. Refer para 4.3 (B) of circular 2. Reversal of Rs. 75,500/- integrated tax, Rs. 52,000/- central tax and Rs. 52,000/- state tax under rule 42 and 43 [Note 2] 3. Ineligible ITC of Integrated tax of Rs. 50,000/- under section 17(5) [Note 1] 1. Refer para 4.3 (C) of circular 2. Reversal of integrated tax of Rs. 10,000/-, where supply is not received [Note 3] 3. Reversal of ITC of Rs 500/- central tax and Rs 500/- state tax on account of Rule 37 [Note 4] C=A1+A2+A3+A4+A5-B1-B2 1. Refer para 4.3 (E) of circular 2. Reversals under section 17(5) are not required to be shown in this row. The same are to be shown under 4(B)(1) 1. Refer para 4.3(F) of circular 2. Ineligible ITC on account of limitation of time period as delineated in sub-section (4) of section 16 of the CGST Act, which has not been auto-populated in Table 4(A) of GSTR-3B |

## 4. 72/46/2018 p.3

- PDF: `docs/circulars/2018/72-46-2018-GST.pdf`, page 3
- Page image: `evals/heldout_pages_2030/03-table-72-46-2018-GST-p3.png`
- What went wrong: Rows start with 'Case 1', 'Case 2' (no serial number): taken as headings, 0 data rows.

*No table on this page in the output.*

## 5. 147/03/2021 p.5

- PDF: `docs/circulars/2021/147-03-2021-GST.pdf`, page 5
- Page image: `evals/heldout_pages_2030/01-table-147-03-2021-GST-p5.png`
- What went wrong: For contrast: a plain bordered numeric table. PyMuPDF got it fully right (40/40).

**147/03//2021-GST:table-1**: 5 columns, 3 rows on these pages

| page | Outward Supply | Value per unit | No of units supplied | Turnover | Turnover as per amended definition |
|---|---|---|---|---|---|
| 5 | Local (Quantity 5) | 200 | 5 | 1000 | 1000 |
| 5 | Export (Quantity 5) | 350 | 5 | 1750 | 1500 (1.5*5*200) |
| 5 | Total |  |  | 2750 | 2500 |

---

# The same pages with Gemini (gemini-3.5-flash-lite)

From `data/extracted_vlm/google_gemini-3.5-flash-lite/`. Gemini gave the grid; every cell holds the PDF's own words (see `ingestion/vlm_tables.py`).

## 1. 179/11/2022 p.4 (Gemini)

*Not run with Gemini yet: this file is in held-out set 2028, which the Gemini runs didn't include.*

## 2. 98/17/2019 p.2 (Gemini)

Self-check: words_missing: 16 of 949 words, e.g. tax, of, to, 2, on, account, Integrated, be; words_left_in_table: 106 PDF word(s) inside a table that no cell took

**98/17/2019-GST:table-1**: 4 columns, 3 rows on these pages

| page | Input tax Credit on account of | Output liability on account of Integrated tax | Output liability on account of Central tax | Output liability on account of State tax / Union Territory tax |
|---|---|---|---|---|
| 2 | Integrated tax | (I) | (II) – In any order and in any proportion | (II) – In any order and in any proportion |
| 2 | Central tax | (V) | (IV) | Not permitted |
| 2 | State tax / Union Territory tax | (VII) | Not permitted | (VI) |

**98/17/2019-GST:table-2**: 3 columns, 4 rows on these pages

| page | Head | Output Liability | Input tax Credit |
|---|---|---|---|
| 2 | Integrated tax | 1000 | 1300 |
| 2 | Central tax | 300 | 200 |
| 2 | State tax / Union Territory tax | 300 | 200 |
| 2 | Total | 1600 | 1700 |

## 3. 170/02/2022 p.6-7 (Gemini)

Self-check: tables_without_headings: 170/02/2022-GST:table-2 (p.6); cells_not_in_pdf: 5 of 107 cells, e.g. p.6 heading col 1: 'Details'; p.6 heading col 2: 'IGST'; p.6 heading col 3: 'CGST'; words_left_in_table: 25 PDF word(s) inside a table that no cell took

**170/02/2022-GST:table-2**: 5 columns, 14 rows on these pages

| page | Column 1 | Column 2 | Column 3 | Column 4 | Column 5 |
|---|---|---|---|---|---|
| 6 | 4. Eligible ITC |  |  |  |  |
| 6 | (A) ITC Available (whether in full or part) | ---- | ---- | ---- |  |
| 6 | 1. Import of Goods | 1,00,000 | ---- | ---- |  |
| 6 | 2. Import of Services | 50,000 | ---- | ---- |  |
| 6 | 3. Inward Supplies liable to Reverse Charge (other than 1 & 2 above) | ---- | 25,000 | 25,000 |  |
| 6 | 4. Inward Supplies from ISD | 50,000 | ---- | ---- |  |
| 6 | 5. All other ITC | 2,00,000 | 1,50,000 | 1,50,000 |  |
| 6 | (B) ITC Reversed / Reduced | ---- | ---- | ---- |  |
| 7 | 1. Reversal of ITC as per rule 42 and 43 of CGST Rules | 125,500 | 52,000 | 52,000 | 1. Refer para 4.3 (B) of circular 2. Reversal of Rs. 75,500/- integrated tax, Rs. 52,000/- central tax and Rs. 52,000/- state tax under rule 42 and 43 [Note 2] 3. Ineligible ITC of Integrated tax of Rs. 50,000/- under section 17(5) [Note 1] |
| 7 | 2. Others | 10,000 | 500 | 500 | 1. Refer para 4.3 (C) of circular 2. Reversal of integrated tax of Rs. 10,000/-, where supply is not received [Note 3] 3. Reversal of ITC of Rs 500/- central tax and Rs 500/- state tax on account of Rule 37 [Note 4] |
| 7 | (C) Net ITC Available (A)-(B) | 2,64,500 | 122500 | 122500 | C=A1+A2+A3+A4+A5-B1-B2 |
| 7 | (D) Ineligible ITC |  |  |  |  |
| 7 | 1. As per section 17(5) | - | - | - | 1. Refer para 4.3 (E) of circular 2. Reversals under section 17(5) are not required to be shown in this row. The same are to be shown under 4(B)(1) |
| 7 | 2. Others |  | 10,000 | 10,000 | 1. Refer para 4.3(F) of circular 2. Ineligible ITC on account of limitation of time period as delineated in sub-section (4) of section 16 of the CGST Act, which has not been auto-populated in Table 4(A) of GSTR-3B |

## 4. 72/46/2018 p.3 (Gemini)

Self-check: words_left_in_table: 4 PDF word(s) inside a table that no cell took

**72/46/2018-GST:table-1**: 4 columns, 1 rows on these pages

| page | Column 1 | Date of Supply of goods from manufacturer/ wholesaler to wholesaler/ retailer | Date of return of time expired goods from retailer / wholesaler to wholesaler / manufacturer | Treatment in terms of tax liability & credit note |
|---|---|---|---|---|
| 3 | Case 1 | 1st July, 2017 | 20th September, 2018 | Credit note will be issued by the supplier (manufacturer / wholesaler) and the same to be uploaded by him on the common portal. Subsequently, tax liability can be adjusted by such supplier provided the recipient (wholesaler / retailer) has either not availed the ITC or if availed has reversed the ITC. |

## 5. 147/03/2021 p.5 (Gemini)

**147/03//2021-GST:table-1**: 5 columns, 3 rows on these pages

| page | Outward Supply | Value per unit | No of units supplied | Turnover | Turnover as per amended definition |
|---|---|---|---|---|---|
| 5 | Local (Quantity 5) | 200 | 5 | 1000 | 1000 |
| 5 | Export (Quantity 5) | 350 | 5 | 1750 | 1500 (1.5*5*200) |
| 5 | Total |  |  | 2750 | 2500 |
