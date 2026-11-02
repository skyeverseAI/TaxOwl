# GST PDF Table Extraction — Short Recommendation

## Recommended approach

- **Default:** PyMuPDF + deterministic post-processing.
- **Fallback:** Sirf flagged pages/tables par Docling; poori file dobara process na karein.
- **Source of truth:** PDF ka original text layer. Parser ko legal numbers rewrite karne na dein.
- **Mandatory:** Har row/cell ke saath document, page number, bounding box, aur source text span rakhein.

## Quality checks

- Source ke har token ka output mein exactly one match.
- Output ka har token source PDF se map ho.
- Numbers, dates, percentages, section numbers aur currency values exact match.
- Missing/extra rows, shifted columns, missing headers aur duplicate headings flag karein.
- Multi-page tables ke column count aur headers consistent hon.
- Validation fail ho to **abstain/review** karein—silently output accept na karein.

## VLM parsers

Scans aur phone photos ke liye useful hain, lekin born-digital legal PDFs mein authoritative source na banayein. VLM se structure suggest karwa sakte hain; text aur numbers PDF text layer se verify karein.

## Retrieval format

`Heading: value` rows achhe hain, lekin canonical storage structured JSON/HTML mein rakhein. Har row mein caption, section heading, hierarchical headers, values, page aur citation coordinates hon. Retrieval ke liye row view + raw table view dono banayein, aur exact legal terms/numbers ke liye hybrid lexical + vector search use karein.

**Bottom line:** exact text preserve karo, table structure derive karo, aur difficult cases ko automatically route karo.
