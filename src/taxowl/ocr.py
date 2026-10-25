"""OCR one scanned page with Apple's built-in OCR (ocrmac), keeping the reading order.

Used by the ingestion pipeline for pages without a text layer, and by ingestion/ocr_scans.py
for the corpus' 8 scans. ocrmac runs only on a Mac: it is imported on first use, so the package
still loads elsewhere; a server would swap page_to_lines for Tesseract or a cloud OCR.

Per page:
  1. Turn the page into an image (300 dpi, sharp enough for small print).
  2. Apple's OCR returns pieces of text, each with a box saying where it was on the page.
  3. Put the pieces back in reading order: pieces at the same height form one line,
     lines go top to bottom, and pieces within a line go left to right.
"""

import io
import re

from PIL import Image

DPI = 300
LOW_CONFIDENCE = 0.5  # pieces the OCR itself is unsure about; counted so we know where to look
MARGIN_SHARE = 0.30   # the left part of the page where paragraph numbers sit (0.22 cut off some)
# "2.", "2.1", "2.2.4". A dot is required: bare digits ("1", "12") turned out to be fragments
# of other numbers, and inserting them put text on the page that isn't there.
PARA_NUMBER = re.compile(r"\d{1,2}(\.\d{1,2}){0,3}\.|\d{1,2}(\.\d{1,2}){1,3}")
BARE_NUMBER = re.compile(r"\d{1,2}")
MONTHS = "(January|February|March|April|May|June|July|August|September|October|November|December)"


def page_to_lines(page, state):
    """OCR one page and return (text, number of low-confidence pieces).
    `state` carries information from earlier pages of the same document (see add_margin_numbers)."""
    from ocrmac import ocrmac  # Mac only; see the module docstring

    pix = page.get_pixmap(dpi=DPI)
    image = Image.open(io.BytesIO(pix.tobytes("png")))
    pieces = ocrmac.OCR(image, recognition_level="accurate", language_preference=["en-US"]).recognize()

    # Each box is (x, y, width, height) as fractions of the page, measured from the BOTTOM-left
    # corner. Convert to "distance from the top" so sorting goes top to bottom.
    items = []
    for text, confidence, (x, y, w, h) in pieces:
        top = 1 - y - h
        items.append({"text": text, "conf": confidence, "x": x, "x2": x + w, "top": top, "mid": top + h / 2, "h": h})
    items.sort(key=lambda it: it["mid"])

    # Group pieces into lines: a piece joins the current line if its middle is within half a
    # line-height of the line's middle AND it sits beside the pieces already there. Pieces that
    # overlap left-to-right must be on different lines. Without this check, two neighbouring lines
    # on a tilted page were merged and put in the wrong order (instruction 01/2024, para 3.3).
    lines = []
    for it in items:
        if (lines and abs(it["mid"] - lines[-1]["mid"]) < it["h"] / 2
                and not any(it["x"] < other["x2"] and other["x"] < it["x2"] for other in lines[-1]["items"])):
            lines[-1]["items"].append(it)
        else:
            lines.append({"mid": it["mid"], "items": [it]})

    lines = join_number_only_lines(lines)
    add_margin_numbers(image, lines, state)

    text = "\n".join(" ".join(it["text"] for it in sorted(line["items"], key=lambda it: it["x"])) for line in lines)
    low = sum(1 for it in items if it["conf"] < LOW_CONFIDENCE)
    return clean(text), low


def join_number_only_lines(lines):
    """Sometimes the OCR puts a paragraph number on a line of its own, between two text lines
    ("13." near "The Zonal Principal..." and "closely monitor..."). Join it to the neighbouring
    line (within 1.5 line-heights) that starts a sentence: capital letter first, no number."""
    def is_number_only(line):
        return len(line["items"]) == 1 and PARA_NUMBER.fullmatch(line["items"][0]["text"].strip())

    def starts_sentence(line):
        return first_text(line)[:1].isupper()

    keep = []
    for i, line in enumerate(lines):
        if not is_number_only(line):
            keep.append(line)
            continue
        number = line["items"][0]
        near = [other for other in (lines[i - 1] if i > 0 else None, lines[i + 1] if i + 1 < len(lines) else None)
                if other and not is_number_only(other) and starts_sentence(other)
                and abs(other["mid"] - line["mid"]) < 1.5 * number["h"]]
        if near:
            target = min(near, key=lambda other: abs(other["mid"] - line["mid"]))
            target["items"].append({**number, "x": -1.0, "x2": -1.0})
        else:
            keep.append(line)  # no good home: leave it where the OCR put it
    return keep


def margin_numbers(image):
    """Find paragraph numbers at the left margin, as (number, middle-height, box-height).
    Apple has two OCR engines, and each one skips *different* short numbers (measured on our
    8 scans), so we combine three readings: both engines on the left strip, and LiveText on the
    full page (only pieces that start near the left edge)."""
    from ocrmac import ocrmac  # Mac only; see the module docstring

    width, height = image.size
    strip = image.crop((0, 0, int(width * MARGIN_SHARE), height))
    readings = [
        ocrmac.OCR(strip, recognition_level="accurate", language_preference=["en-US"]).recognize(),
        ocrmac.OCR(strip, framework="livetext", language_preference=["en-US"]).recognize(),
        [p for p in ocrmac.OCR(image, framework="livetext", language_preference=["en-US"]).recognize()
         if p[2][0] < MARGIN_SHARE],
    ]
    dotted, bare = [], []
    for pieces in readings:
        for text, _, (x, y, w, h) in pieces:
            words = text.split()
            if not words:
                continue
            if PARA_NUMBER.fullmatch(words[0]):
                dotted.append((words[0], 1 - y - h / 2, h))
            elif BARE_NUMBER.fullmatch(words[0]):
                bare.append((int(words[0]), 1 - y - h / 2, h))
    return dotted, bare


def first_text(line):
    return min(line["items"], key=lambda it: it["x"])["text"]


def nearest_line(lines, mid, h):
    """The line whose middle is within half a line-height of `mid`, or None.
    mid is on the same vertical scale as the full page, since the strip is full height."""
    nearest = min(lines, key=lambda line: abs(line["mid"] - mid), default=None)
    return nearest if nearest and abs(nearest["mid"] - mid) < h / 2 else None


def add_margin_numbers(image, lines, state):
    """Apple's OCR sometimes skips a short paragraph number ("2.", "4.2") sitting alone at the
    left margin. Measured on our 8 scans: 4 of 19 lost in circular 229/23/2024 alone. We look
    for them again (see margin_numbers) and put back any number missing from the start of its
    line. (The splitter cuts circulars at these numbers, so they matter.)

    A number is only ever added to the start of an existing line, never as a line of its own,
    so a stray number (e.g. from a table) can't create text that isn't on the page."""
    dotted, bare = margin_numbers(image)
    starts = {first_text(line).split()[0].rstrip(".") for line in lines if first_text(line).split()}

    # Walk the lines top to bottom, remembering the last top-level paragraph number
    # (state["last_top"], carried across pages of the same document). A found number is
    # added to a line only if all of these hold:
    #   - the line starts a sentence (capital letter first). Rejected "13. closely monitor..."
    #     and "96. (5A) of rule 96.";
    #   - the number fits the sequence: after 5 or 5.x, only 5.y or 6. Rejected "26." (a date
    #     "26.07.2023" cut short at the edge of the strip);
    #   - the number doesn't already start another line on this page.
    # Bare digits ("7" read without its dot) are riskier (fragments like "1" or "25" show up),
    # so they must be exactly the next top-level number, and at least 2.
    for line in sorted(lines, key=lambda line: line["mid"]):
        first = first_text(line)
        lead = first.split()[0] if first.split() else ""
        if PARA_NUMBER.fullmatch(lead):
            state["last_top"] = int(lead.split(".")[0])
            continue
        if not first[:1].isupper():
            continue
        last = state["last_top"]
        # Many circulars leave paragraph 1 unnumbered and start at "2.", so at the start allow 1 or 2.
        allowed = (last, last + 1) if last else (1, 2)
        for number, mid, h in dotted:
            top = int(number.split(".")[0])
            if (nearest_line(lines, mid, h) is line and top in allowed
                    and number.rstrip(".") not in starts):
                line["items"].append({"text": number, "x": -1.0, "x2": -1.0})
                state["last_top"] = top
                break
        else:
            for n, mid, h in bare:
                if n == last + 1 and n >= 2 and nearest_line(lines, mid, h) is line:
                    line["items"].append({"text": f"{n}.", "x": -1.0, "x2": -1.0})
                    state["last_top"] = n
                    break


def clean(text):
    """Fix the OCR's regular mistakes. Each rule comes from errors seen in our scans."""
    # Superscript ordinals in dates come out as junk: "15iẠạịỊiJuly", "28ại June", "12" July".
    # Drop the ordinal entirely ("15 July"); the date stays unambiguous.
    text = re.sub(rf"(\b\d{{1,2}})[^\s\d,.]{{0,8}}\s*(?={MONTHS})", r"\1 ", text)
    # "Sl. No." (serial number) is read with a capital I.
    text = re.sub(r"\bSI\.\s?No\b", "Sl. No", text)
    return text
