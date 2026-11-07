"""
app.py: a small Streamlit UI to try the answer step and compare the two models side by side.

    uv run streamlit run app.py

Same shape as evals_project/app.py, cut down to what we need now: no chat history, no sidebar.
One question -> sources found once -> the cloud answer streams in, then the local one ->
time, cost and checks under each -> the sources, which you can open, at the bottom.

Both models get the same sources (retrieved once, with the local model's token budget), so the
comparison is fair. They run one after the other, not together: running them at once needs
threads, which makes this file much harder to read.
"""

import time

import streamlit as st

from taxowl.answer.check import check, cited_numbers
from taxowl.answer.generator import CLOUD_MODEL, LOCAL_MODEL, generate_stream
from taxowl.answer.pipeline import BUDGET, as_text, assumed, get_retriever, get_sources

MODELS = {"cloud": f"☁️ Cloud · {CLOUD_MODEL}", "local": f"💻 Local · {LOCAL_MODEL}"}

st.set_page_config(page_title="taxowl", page_icon="🦉", layout="wide")


# load the store and the embedding model once per server, not on every question
@st.cache_resource(show_spinner="Loading the store...")
def load():
    return get_retriever()


def show_model(which: str, question: str, sources: list[dict]) -> set[int]:
    """Stream one model's answer, then its time, cost and checks. Returns the sources it cited."""
    st.subheader(MODELS[which])
    stats, timing = {}, {}
    start = time.perf_counter()

    def timed_stream():
        for piece in generate_stream(question, as_text(sources), which, stats, assumed(sources)):
            timing.setdefault("first", time.perf_counter() - start)  # time to the first word
            yield piece

    try:
        st.write_stream(timed_stream())  # renders the Markdown as it arrives
    except Exception as error:  # noqa: BLE001 - any failure (Ollama off, no internet) shows, not crashes
        st.error(f"{which} model failed: {error}")
        return set()

    total = time.perf_counter() - start
    st.caption(f"⏱ {total:.1f} s (first word {timing.get('first', total):.1f} s) · "
               f"{stats.get('input_tokens', 0)} in / {stats.get('output_tokens', 0)} out tokens · "
               f"₹{stats.get('cost_inr', 0):.4f}")

    failed = [c for c in check(stats.get("text", ""), sources) if not c["passed"]]
    if failed:
        for c in failed:
            st.warning(f"Check failed, **{c['name']}**: {c['why']}")
    else:
        st.success("All checks passed")
    return cited_numbers(stats.get("text", ""))


def show_sources(sources: list[dict], cited_by: dict[str, set[int]]) -> None:
    """One closed box per source: its label and who cited it; open it for the link and the text."""
    st.subheader(f"📚 Sources ({len(sources)})")
    for s in sources:
        who = [which for which, numbers in cited_by.items() if s["number"] in numbers]
        tag = f" · cited by {', '.join(who)}" if who else ""
        with st.expander(f"[S{s['number']}] {s['label']}{tag}"):
            st.markdown(f"[Official PDF]({s['url']})")
            st.text(s["text"])


st.title("🦉 taxowl")
st.caption("GST law answers from official sources. Information, not legal advice.")

with st.form("ask"):
    question = st.text_input("Your question", placeholder="What does section 16(4) say about the time limit for ITC?")
    asked = st.form_submit_button("Ask")

if asked and question.strip():
    load()
    with st.spinner("Finding sources..."):
        start = time.perf_counter()
        sources = get_sources(question, BUDGET["local"])
        found_in = time.perf_counter() - start
    st.caption(f"🔎 {len(sources)} sources found in {found_in:.1f} s")

    cited_by = {}
    for column, which in zip(st.columns(2), MODELS):
        with column:
            cited_by[which] = show_model(which, question, sources)

    st.divider()
    show_sources(sources, cited_by)
