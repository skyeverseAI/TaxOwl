# PaddleOCR-VL 1.6: results sheet (tested and dropped, 2026-10-29)

We tried PaddleOCR-VL 1.6 as a free, local alternative to Gemini for reading table *grids*.
**Verdict: dropped.** It scored 87.8% on the 5 held-out sets, against Gemini's 94.4% and PyMuPDF's
85.6%, and it is slower. The code and the install were removed after this sheet was written. The
raw output of the 6 example pages is in the appendix at the end.

Revisit only if user uploads need a model that runs on our own machine for privacy
(plans/table_gate_feasibility.md). Even then, fix the conversion issues listed under
"Why it lost points" first.

## What it is

- **Model**: PaddleOCR-VL 1.6 (Baidu), a 0.9B vision-language model, Apache 2.0. In the 2026
  rankings it was at or near the top for tables (OmniDocBench).
- **Pipeline**: the PP-DocLayoutV3 layout model (123 MB) finds blocks on the page: text, title,
  table, header, page number and so on. The VL model then reads each block. Tables come back as
  HTML, with colspan and rowspan.
- **Used as Gemini was**: the model gives only the grid. Every cell is snapped to the PDF's own
  words (`ingestion/vlm_tables.py`), so a misread digit can never reach a cell.

## Setup that worked (M5 Mac, 16 GB)

| Piece | Version / place |
|---|---|
| venv | Python 3.12.14 at `~/Documents/paddleocr-venv`. The project is on 3.14, which Paddle doesn't support. |
| paddlepaddle | 3.2.1, CPU build, from `https://www.paddlepaddle.org.cn/packages/stable/cpu/` |
| paddleocr / paddlex | 3.7.0 / 3.7.2, `paddleocr[doc-parser]` |
| mlx / mlx-vlm | 0.32.4 / 0.7.11 |
| models | `~/.paddlex/official_models/` (PaddleOCR-VL-1.6 1.8 GB, PP-DocLayoutV3 126 MB) |

Steps:

```
uv venv --python 3.12 ~/Documents/paddleocr-venv
uv pip install --python ~/Documents/paddleocr-venv/bin/python \
  --extra-index-url https://www.paddlepaddle.org.cn/packages/stable/cpu/ "paddlepaddle==3.2.1"
uv pip install --python ~/Documents/paddleocr-venv/bin/python setuptools   # uv venvs lack it; paddle imports it
uv pip install --python ~/Documents/paddleocr-venv/bin/python "paddleocr[doc-parser]" pymupdf "mlx-vlm>=0.3.11"
~/Documents/paddleocr-venv/bin/mlx_vlm.server --port 8111                  # terminal 1: the model on the GPU
```

Then in Python:

```python
PaddleOCRVL(pipeline_version="v1.6", vl_rec_backend="mlx-vlm-server",
            vl_rec_server_url="http://localhost:8111/",
            vl_rec_api_model_name=str(Path.home() / ".paddlex/official_models/PaddleOCR-VL-1.6"))
```

Lessons from the setup:
- **Native mode (Paddle on the CPU) hung the Mac.** It ran the 0.9B model in full precision on
  every core. Use the MLX server, which runs the model on the GPU; this is also the official Apple
  Silicon guide's route.
- **The model was downloaded twice.** Paddle keeps models in `~/.paddlex`, while the MLX server
  looks only in the Hugging Face cache. Giving the server the `~/.paddlex` folder path, instead of
  the Hugging Face name, avoided a second 1.9 GB download.
- **The first request takes ~5 minutes**, because the server loads the model then. After that a
  page takes ~5-7 s.
- **Every block on a page is a separate model request**, paragraphs too. That is most of the time,
  and we only needed the tables.

## Results

### 6 example pages: the model's own text, before snapping

Pages: 179 p4, 98 p2, 170 p6-7, 72 p3, 147 p5. The PyMuPDF and Gemini results for the same pages
are in `evals/pymupdf_examples.md`.

| Page | PyMuPDF | Gemini | PaddleOCR-VL |
|---|---|---|---|
| 179 p4 (shaded) | wrong (5x6 instead of 3x3) | not run | right, 3x3 |
| 98 p2 table 1 | wrong (9 columns) | missed row (III) | right, with row (III) and the merged cell |
| 98 p2 table 2 (coloured) | wrong | right | **failed**: plain text, not a table |
| 170 p6 | rows glued | headings lost (our snapping bug) | right, including headings and the column-number row |
| 170 p7 | rows glued | right | right, all numbers |
| 72 p3 ("Case 1") | wrong | right | right |
| 147 p5 | right | right | right |

The model got 6 of 7 tables right and **misread no number**. The words it wrote that aren't in the
PDF are formatting only:
- LaTeX superscripts: `$ 28^{th} $` where the PDF has "28th";
- a literal `\n` inside cells;
- "SGST/UTGST" as one word, where the PDF has two.

It also tagged the notes paragraph on 170 p6 as a "table".

### Held-out runs #1-#5: the same 125 pages, same snapping and checker as Gemini

| Run | PyMuPDF | Gemini 3.5 Flash Lite | PaddleOCR-VL 1.6 |
|---|---|---|---|
| #1 2029 | 92.5% | 97.3% | 91.2% (156/171) |
| #2 2030 | 88.1% | 98.7% | 89.3% (201/225) |
| #3 2031 | 65.7% | 94.0% | 93.4% (199/213) |
| #4 2032 | 96.9% | 93.4% | 82.9% (131/158) |
| #5 2033 | 90.2% | 86.1% | 78.2% (111/142) |
| **Pooled** | **85.6%** | **94.4%** | **87.8% (798/909)** |

| | PyMuPDF | Gemini | PaddleOCR-VL |
|---|---|---|---|
| Time per page | ~0.1 s | 4.4 s, 8 pages at a time | 6.8 s, one at a time (853 s for 125 pages; two pages took 39 s) |
| Cost for 125 pages | 0 | $0.15 | 0 (electricity; the Mac runs hot) |
| Cells found word for word in the PDF | - | 1113/1214 (91.7%) | 1014/1145 (88.6%) |
| Table blocks dropped as not HTML | - | - | 2 (98 p2 table 2; 170 p6 notes) |

### Why it lost points

Most of the loss came from our conversion and snapping code, not from the model's reading.

| Cause | Where (failed checks) | Fix, if ever revisited |
|---|---|---|
| A table's box swallowed the page text. The box is the outline of the words its cells took, so one cell snapped far away stretches it. **Gemini has the same exposure.** | 24/24 p2 (0/12), Corrigendum 76 (1/17), 106 p7 (5) | Build the box from the model's own bbox, or drop outlier cells |
| LaTeX in cells (`$ 1^{{st}} $`), so the cell doesn't snap and dates are lost | 72 p3 (4) | Strip `$`, `^{}` and braces before snapping |
| Heading rows guessed wrong. Paddle doesn't mark headings, so we guessed: a row is a heading only below a spanning cell. | 26 p10 (16): a third level without spans became data. 199, 181, 31 (3 each, 9 for 31): Q&A headings shifted one column. | Ask the layout or table model for header rows, or detect from bold/fill |
| The model returned plain text instead of a table | 98 p2 table 2 (11) | Fall back to Gemini or PyMuPDF for that table |
| Table not matched (continuation or heading rules) | 94 p3 (6), 36 p7 (2) | - |
| Same as every reader: Rules chapter running header, OCR noise | all runs (2 each) | Shared fix, not Paddle's |

## How the HTML was turned into Gemini's answer shape (rules from the deleted `ingestion/paddle_tables.py`)

- A block whose content isn't an HTML table is dropped and reported.
- Rows at the top that are one cell across the full width are a title, not a heading.
- Heading rows: the first row, plus the next one while the row above has a cell spanning several
  columns. At most 3.
- Heading levels are joined top to bottom. A level copied down by a rowspan is used once.
  A colspan heading is repeated in each column it covers.
- Data rows: a rowspan's text goes in every row, a colspan's in the first column only (the same
  rules we gave Gemini). Empty rows are dropped.
- A row of only column numbers ("1 2 3", "(1) (2)") directly under the headings is dropped.
- A table continues the previous page's table when all three hold: it is the first content block
  on the page (running header and page number aside), the previous page ended with a table, and
  the column counts match. Its first row counts as a heading only if it repeats the first page's
  heading row.
- `first_row_continues`: a continued table whose first row has an empty first (serial) cell.

## Removed on 2026-10-29

These files were never committed to git, so they can't be recovered from it:
- `ingestion/paddle_tables.py`
- the local-model branch in `ingestion/vlm_tables.py`, which read answers only from the cache when
  a model name had no "/"
- `evals/paddle_examples.md`, now the appendix below
- `data/extracted_paddle/` and `data/extracted_vlm/paddleocr-vl-1.6/`, the raw blocks, cache and
  extracted docs
- outside the repo: `~/Documents/paddleocr-venv` (1.7 GB), `~/.paddlex` (1.9 GB), and the empty
  Paddle folders in `~/.cache/huggingface/hub`

---

## Appendix: raw output of the 6 example pages

What `paddle_tables.py` wrote then, before snapping. "not in PDF" lists words the model wrote that
the PDF doesn't have. "left over" lists PDF words inside the table's box that no cell has.

### 179-11-2022-GST-p4

- PDF: `docs/circulars/2022/179-11-2022-GST.pdf`, page 4
- Time: 315.0 s

#### Table 1: 4 rows x 3 columns

- not in PDF (11): $, 28^{th}, $, Schedule-I, $, 28^{th}, $, Schedule-I, $, 28^{th}, $
- left over (7 of 157): 28th, 28th, 28th, schedule-, schedule-, i, i

| Entry and notification No. | Description | GST Rate |
|---|---|---|
| S. No. 102 of notification No. 2/2017-Central Tax (Rate), dated the $ 28^{th} $ June, 2017 | Aquatic feed including shrimp feed and prawn feed, poultry feed & cattle feed, including grass, hay & straw, supplement & husk of pulses, concentrates & additives, wheat bran & de-oiled cake[other than rice bran] | Nil |
| S. No. 103A of Schedule-I of notification No. 1/2017-Central Tax (Rate), dated $ 28^{th} $ June, 2017 | Bran, sharps and other residues, whether or not in the form of pellets, derived from the sifting, milling or other working of cereals or of leguminous plants [other than aquatic feed including shrimp feed and prawn feed, poultry feed and cattle feed, including grass, hay and straw, supplement and husk of pulses, concentrates and additives, wheat bran and de-oiled cake] | 5% |
| S. No. 103B of Schedule-I of notification No. 1/2017-Central Tax (Rate), dated $ 28^{th} $ June, 2017 | Rice bran (other than de-oiled rice bran) | 5% |

<details><summary>HTML as the model gave it (merged cells kept)</summary>

<table><tr><td>Entry and notification No.</td><td>Description</td><td>GST Rate</td></tr><tr><td>S. No. 102 of notification No. 2/2017-Central Tax (Rate), dated the  $ 28^{th} $ June, 2017</td><td>Aquatic feed including shrimp feed and prawn feed, poultry feed &amp; cattle feed, including grass, hay &amp; straw, supplement &amp; husk of pulses, concentrates &amp; additives, wheat bran &amp; de-oiled cake[other than rice bran]</td><td>Nil</td></tr><tr><td>S. No. 103A of Schedule-I of notification No. 1/2017-Central Tax (Rate), dated  $ 28^{th} $ June, 2017</td><td>Bran, sharps and other residues, whether or not in the form of pellets, derived from the sifting, milling or other working of cereals or of leguminous plants [other than aquatic feed including shrimp feed and prawn feed, poultry feed and cattle feed, including grass, hay and straw, supplement and husk of pulses, concentrates and additives, wheat bran and de-oiled cake]</td><td>5%</td></tr><tr><td>S. No. 103B of Schedule-I of notification No. 1/2017-Central Tax (Rate), dated  $ 28^{th} $ June, 2017</td><td>Rice bran (other than de-oiled rice bran)</td><td>5%</td></tr></table>

</details>

### 98-17-2019-GST-p2

- PDF: `docs/circulars/2019/98-17-2019-GST.pdf`, page 2
- Time: 5.6 s

#### Table 1: 6 rows x 4 columns

- not in PDF (1): tax\nCredit
- left over (2 of 73): tax, credit

| Input tax\nCredit on account of | Output liability on account of Integrated tax | Output liability on account of Central tax | Output liability on account of State tax / Union Territory tax |
|---|---|---|---|
| Integrated tax | (I) | (II) – In any order and in any proportion |   |
| (III) Input tax Credit on account of Integrated tax to be completely exhausted mandatorily |   |   |   |
| Central tax | (V) | (IV) | Not permitted |
| State tax / Union Territory tax | (VII) | Not permitted | (VI) |
|   |   |   |   |

<details><summary>HTML as the model gave it (merged cells kept)</summary>

<table><tr><td>Input tax\nCredit on account of</td><td>Output liability on account of Integrated tax</td><td>Output liability on account of Central tax</td><td>Output liability on account of State tax / Union Territory tax</td></tr><tr><td>Integrated tax</td><td>(I)</td><td colspan="2">(II) – In any order and in any proportion</td></tr><tr><td colspan="4">(III) Input tax Credit on account of Integrated tax to be completely exhausted mandatorily</td></tr><tr><td>Central tax</td><td>(V)</td><td>(IV)</td><td>Not permitted</td></tr><tr><td>State tax / Union Territory tax</td><td>(VII)</td><td>Not permitted</td><td>(VI)</td></tr><tr><td></td><td></td><td></td><td></td></tr></table>

</details>

#### Table 2: 0 rows x 0 columns

- not in PDF (0): -
- left over (25 of 25): head, output, liability, input, tax, tax, tax, tax, tax, credit, integrated, 1000, 1300, central, 300, 300, 200, 200, state, /

(empty)

<details><summary>HTML as the model gave it (merged cells kept)</summary>

i
Head
Output Liability
Input tax Credit
Integrated tax
1000
300
200
State tax / Union Territory tax
300
1600
Total
1300<nl>

</details>

### 170-02-2022-GST-p6

- PDF: `docs/circulars/2022/170-02-2022-GST.pdf`, page 6
- Time: 5.7 s

#### Table 1: 0 rows x 0 columns

- not in PDF (0): -
- left over (114 of 114): note, note, note, 3:, m/s, m/s, abc, abc, had, not, not, not, received, the, the, the, supply, supply, during, april,

(empty)

<details><summary>HTML as the model gave it (merged cells kept)</summary>

Note 3: M/s ABC had not received the supply during April, 2022 in respect of an invoice for an inwards supply auto-populated in row (5) having integrated tax of Rs. 10,000/-.
Note 4: M/s ABC has reversed ITC of Rs. 500/- central tax and Rs. 500/- state tax on account of Rule 37 i.e. where consideration was not paid to the supplier within 180 days.
Note 5: An amount of ITC of Rs 10,000/ central Tax and Rs 10,000/- state tax, ineligible on account of limitation of time period as delineated in sub-section (4) of section 16 of the CGST Act, has not been auto-populated in Table 4(A) of FORM GSTR-3B from GSTR-2B.

</details>

#### Table 2: 10 rows x 5 columns

- not in PDF (1): SGST/UTGST
- left over (2 of 77): sgst/, utgst

| 4. Eligible ITC |   |   |   |   |
|---|---|---|---|---|
| Details | IGST | CGST | SGST/UTGST | Explanation |
| 1 | 2 | 3 | 4 |   |
| (A) ITC Available (whether in full or part) | ---- | ---- | ---- |   |
| 1. Import of Goods | 1,00,000 | ---- | ---- |   |
| 2. Import of Services | 50,000 | ---- | ---- |   |
| 3. Inward Supplies liable to Reverse Charge (other than 1 & 2 above) | ---- | 25,000 | 25,000 |   |
| 4. Inward Supplies from ISD | 50,000 | ---- | ---- |   |
| 5. All other ITC | 2,00,000 | 1,50,000 | 1,50,000 |   |
| (B) ITC Reversed / Reduced | ---- | ---- | ---- |   |

<details><summary>HTML as the model gave it (merged cells kept)</summary>

<table><tr><td colspan="5">4. Eligible ITC</td></tr><tr><td>Details</td><td>IGST</td><td>CGST</td><td>SGST/UTGST</td><td>Explanation</td></tr><tr><td>1</td><td>2</td><td>3</td><td>4</td><td></td></tr><tr><td>(A) ITC Available (whether in full or part)</td><td>----</td><td>----</td><td>----</td><td></td></tr><tr><td>1. Import of Goods</td><td>1,00,000</td><td>----</td><td>----</td><td></td></tr><tr><td>2. Import of Services</td><td>50,000</td><td>----</td><td>----</td><td></td></tr><tr><td>3. Inward Supplies liable to Reverse Charge (other than 1 &amp; 2 above)</td><td>----</td><td>25,000</td><td>25,000</td><td></td></tr><tr><td>4. Inward Supplies from ISD</td><td>50,000</td><td>----</td><td>----</td><td></td></tr><tr><td>5. All other ITC</td><td>2,00,000</td><td>1,50,000</td><td>1,50,000</td><td></td></tr><tr><td>(B) ITC Reversed / Reduced</td><td>----</td><td>----</td><td>----</td><td></td></tr></table>

</details>

### 170-02-2022-GST-p7

- PDF: `docs/circulars/2022/170-02-2022-GST.pdf`, page 7
- Time: 6.8 s

#### Table 1: 6 rows x 5 columns

- not in PDF (6): circular\n2., 2]\n3., circular\n2., 3]\n3., circular\n2., circular\n2.
- left over (12 of 199): circular, circular, circular, circular, 2., 2., 2., 2., 2], 3., 3., 3]

| 1. Reversal of ITC as per rule 42 and 43 of CGST Rules | 125,500 | 52,000 | 52,000 | 1. Refer para 4.3 (B) of circular\n2. Reversal of Rs. 75,500/- integrated tax, Rs. 52,000/- central tax and Rs. 52,000/- state tax under rule 42 and 43 [Note 2]\n3. Ineligible ITC of Integrated tax of Rs. 50,000/- under section 17(5) [Note 1] |
|---|---|---|---|---|
| 2. Others | 10,000 | 500 | 500 | 1. Refer para 4.3 (C) of circular\n2. Reversal of integrated tax of Rs. 10,000/-, where supply is not received [Note 3]\n3. Reversal of ITC of Rs 500/- central tax and Rs 500/- state tax on account of Rule 37 [Note 4] |
| (C) Net ITC Available (A)-(B) | 2,64,500 | 122500 | 122500 | C=A1+A2+A3+A4+A5-B1-B2 |
| (D) Ineligible ITC |   |   |   |   |
| 1. As per section 17(5) | - | - | - | 1. Refer para 4.3 (E) of circular\n2. Reversals under section 17(5) are not required to be shown in this row. The same are to be shown under 4(B)(1) |
| 2. Others |   | 10,000 | 10,000 | 1. Refer para 4.3(F) of circular\n2. Ineligible ITC on account of limitation of time period as delineated in sub-section (4) of section 16 of the CGST Act, which has not been auto-populated in Table 4(A) of GSTR-3B |

<details><summary>HTML as the model gave it (merged cells kept)</summary>

<table><tr><td>1. Reversal of ITC as per rule 42 and 43 of CGST Rules</td><td>125,500</td><td>52,000</td><td>52,000</td><td>1. Refer para 4.3 (B) of circular\n2. Reversal of Rs. 75,500/- integrated tax, Rs. 52,000/- central tax and Rs. 52,000/- state tax under rule 42 and 43 [Note 2]\n3. Ineligible ITC of Integrated tax of Rs. 50,000/- under section 17(5) [Note 1]</td></tr><tr><td>2. Others</td><td>10,000</td><td>500</td><td>500</td><td>1. Refer para 4.3 (C) of circular\n2. Reversal of integrated tax of Rs. 10,000/-, where supply is not received [Note 3]\n3. Reversal of ITC of Rs 500/- central tax and Rs 500/- state tax on account of Rule 37 [Note 4]</td></tr><tr><td>(C) Net ITC Available (A)-(B)</td><td>2,64,500</td><td>122500</td><td>122500</td><td>C=A1+A2+A3+A4+A5-B1-B2</td></tr><tr><td>(D) Ineligible ITC</td><td></td><td></td><td></td><td></td></tr><tr><td>1. As per section 17(5)</td><td>-</td><td>-</td><td>-</td><td>1. Refer para 4.3 (E) of circular\n2. Reversals under section 17(5) are not required to be shown in this row. The same are to be shown under 4(B)(1)</td></tr><tr><td>2. Others</td><td></td><td>10,000</td><td>10,000</td><td>1. Refer para 4.3(F) of circular\n2. Ineligible ITC on account of limitation of time period as delineated in sub-section (4) of section 16 of the CGST Act, which has not been auto-populated in Table 4(A) of GSTR-3B</td></tr></table>

</details>

### 72-46-2018-GST-p3

- PDF: `docs/circulars/2018/72-46-2018-GST.pdf`, page 3
- Time: 5.3 s

#### Table 1: 2 rows x 4 columns

- not in PDF (6): $, 1^{{st}}, $, $, 20^{{th}}, $
- left over (2 of 66): 1st, 20th

|   | Date of Supply of goods from manufacturer/ wholesaler to wholesaler/ retailer | Date of return of time expired goods from retailer / wholesaler to wholesaler / manufacturer | Treatment in terms of tax liability & credit note |
|---|---|---|---|
| Case 1 | $ 1^{{st}} $ July, 2017 | $ 20^{{th}} $ September, 2018 | Credit note will be issued by the supplier (manufacturer / wholesaler) and the same to be uploaded by him on the common portal. |

<details><summary>HTML as the model gave it (merged cells kept)</summary>

<table><tr><td></td><td>Date of Supply of goods from manufacturer/ wholesaler to wholesaler/ retailer</td><td>Date of return of time expired goods from retailer / wholesaler to wholesaler / manufacturer</td><td>Treatment in terms of tax liability &amp; credit note</td></tr><tr><td>Case 1</td><td>$ 1^{{st}} $ July, 2017</td><td>$ 20^{{th}} $ September, 2018</td><td>Credit note will be issued by the supplier (manufacturer / wholesaler) and the same to be uploaded by him on the common portal.</td></tr></table>

</details>

### 147-03-2021-GST-p5

- PDF: `docs/circulars/2021/147-03-2021-GST.pdf`, page 5
- Time: 4.6 s

#### Table 1: 4 rows x 5 columns

- not in PDF (0): -
- left over (0 of 33): -

| Outward Supply | Value per unit | No of units supplied | Turnover | Turnover as per amended definition |
|---|---|---|---|---|
| Local (Quantity 5) | 200 | 5 | 1000 | 1000 |
| Export (Quantity 5) | 350 | 5 | 1750 | 1500 (1.5*5*200) |
| Total |   |   | 2750 | 2500 |

<details><summary>HTML as the model gave it (merged cells kept)</summary>

<table><tr><td>Outward Supply</td><td>Value per unit</td><td>No of units supplied</td><td>Turnover</td><td>Turnover as per amended definition</td></tr><tr><td>Local (Quantity 5)</td><td>200</td><td>5</td><td>1000</td><td>1000</td></tr><tr><td>Export (Quantity 5)</td><td>350</td><td>5</td><td>1750</td><td>1500 (1.5*5*200)</td></tr><tr><td>Total</td><td></td><td></td><td>2750</td><td>2500</td></tr></table>

</details>
