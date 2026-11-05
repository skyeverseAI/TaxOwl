"""A table -> Markdown pieces that fit the embedder (B5 in to-do-list.md).

Rows are added under the table's header until the next one wouldn't fit; then a new piece starts
with the header again. So a small table is one piece, and no row is ever cut if it can fit.
A row too long for a piece is cut inside its long cells, by sentence; each part repeats the row's
short cells ("S. no.", a short "Issue"), so it can be understood alone.
No overlap here: the repeated header and short cells do that work.
"""

import re
from dataclasses import dataclass

from taxowl.chunking.chunker import MAX_TOKENS, by_lines
from taxowl.tokens import count_tokens

MADE_UP = re.compile(r"^Column \d+$")  # Gemini's name for a column with no heading in the PDF
COLUMN_NUMBER = re.compile(r"^\(?(\d{1,2})[A-Z]?\)?\.?$")
REPEAT_MAX = 120  # a row's cell is repeated in each of its parts only if it's this short


@dataclass
class TablePiece:
    table_id: str
    unit_id: str
    page_start: int  # the pages of this piece's own rows, not of the whole table
    page_end: int
    first_row: int  # counted from 1, among the rows kept
    last_row: int
    text: str


def clean_cell(cell: str) -> str:
    """One line, and a "|" can't be read as the end of a cell."""
    return " ".join(str(cell).split()).replace("|", "/")


def md_row(cells: list[str]) -> str:
    return "| " + " | ".join(cells) + " |"


def is_column_numbers(row: list[str]) -> bool:
    """The printed row under a header: "(1) (1A) (2) (3)" or "1 2 3". Not data."""
    found = [COLUMN_NUMBER.match(c) for c in row]
    if len(row) < 2 or not all(found):
        return False
    numbers = [int(m.group(1)) for m in found]
    return numbers[0] <= 1 and numbers == sorted(numbers)


def header_lines(headings: list[str]) -> list[str]:
    """Markdown header. Made-up names say nothing, so they're left blank; all made-up: no header."""
    names = ["" if MADE_UP.match(h) else clean_cell(h) for h in headings]
    if not any(names):
        return []
    return [md_row(names), md_row(["---"] * len(names))]


def split_long_row(row: list[str], head: str, room: int) -> list[list[str]]:
    """A row too long for one piece -> rows that fit. Short cells repeat; each long cell goes by sentence."""
    used = count_tokens(head) + count_tokens(md_row([""] * len(row)))
    keep = set()
    for i, cell in enumerate(row):
        n = count_tokens(cell)
        if n <= REPEAT_MAX and used + n <= room // 2:
            keep.add(i)
            used += n
    out = []
    for i, cell in enumerate(row):
        if i in keep or not cell:
            continue
        for part in by_lines([cell], "", room - used, []):
            text = " ".join(part.text.split())  # a Markdown row must stay on one line
            out.append([text if j == i else (row[j] if j in keep else "") for j in range(len(row))])
    return out or [row]


def cut_table(table: dict, reserve: int = 0) -> list[TablePiece]:
    """One table from data/units/<file>.tables.jsonl -> its pieces, in order. [] if it has no data."""
    room = MAX_TOKENS - reserve
    head = "\n".join(header_lines(table["headings"]))
    cleaned = [[clean_cell(c) for c in r] for r in table["rows"]]
    row_pages = table.get("row_pages") or [min(table["pages"])] * len(cleaned)
    kept = [(r, p) for r, p in zip(cleaned, row_pages) if any(r) and not is_column_numbers(r)]
    rows = [r for r, _ in kept]
    # row_pages says where a row starts. It can run on to the page where the next row starts.
    ends = [p for _, p in kept[1:]] + [max(table["pages"])]

    pieces: list[TablePiece] = []
    now: list[str] = []
    first = 1

    def close(last: int) -> None:
        if now:
            text = "\n".join(([head] if head else []) + now)
            pieces.append(TablePiece(table["table_id"], table["unit_id"], kept[first - 1][1], ends[last - 1],
                                     first, last, text))

    for number, row in enumerate(rows, 1):
        line = md_row(row)
        whole = count_tokens(f"{head}\n{line}") <= room
        parts = [line] if whole else [md_row(r) for r in split_long_row(row, head, room)]
        for part in parts:
            if now and count_tokens("\n".join([head] + now + [part])) > room:
                close(number - 1 if part == parts[0] else number)
                now = []
                first = number
            now.append(part)
    close(len(rows))
    return pieces
