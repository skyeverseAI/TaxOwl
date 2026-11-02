## Before Ingestion

✅ Add the Act and Rules to the manifest (5 minutes), so all 314 files are listed in one place.

Text extractor (src/extract.py): turn the PDFs into clean text, and find out how many are scans.

3. Splitters: the Act into sections, the Rules into rules, circulars into paragraphs.

4. Chunker + 02_parse.py: save all chunks to chunks.jsonl, then you check some by eye.

5. Vectors + database (03_ingest.py): mostly reused from LERAGS.

6. Checks (04_check.py): all sections present, a test search works.