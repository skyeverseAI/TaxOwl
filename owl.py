"""
owl.py: the loading animations in app.py. Plain HTML + CSS: no JavaScript, no threads.

Two of them:
- wake_up(steps, now): page open on a cold server. The REAL steps (store, model), each ticked when
  it's done. app.py redraws it between steps.
- thinking(): while the sources are found. A bobbing owl, and words that change by themselves every
  1.5 s (a CSS animation), so Python only shows it, waits, and clears it. The words are general on
  purpose: the search is one call, so they don't claim a step that isn't happening right then.

Shown with st.markdown(..., unsafe_allow_html=True). The text here is ours, never the user's, so
there's nothing to escape.
"""

WORDS = ["Searching the law...", "Reading the CGST Act...", "Checking circulars...",
         "Looking up the Rules...", "Matching sections...", "Gathering sources..."]
EVERY = 1.5  # seconds each word stays


def _word_keyframes() -> str:
    """One word's turn is 1/len(WORDS) of the loop: fade in from below, stay, fade out upwards."""
    turn = 100 / len(WORDS)
    return (f"@keyframes owl-word {{0% {{opacity:0; transform:translateY(.45em)}} "
            f"{turn * .15:.2f}% {{opacity:1; transform:none}} {turn * .85:.2f}% {{opacity:1; transform:none}} "
            f"{turn:.2f}% {{opacity:0; transform:translateY(-.45em)}} 100% {{opacity:0}}}}")


# Amber (an owl's eyes) on a soft box; the grey and amber read on both light and dark themes.
CSS = """<style>
.owl-box {display:flex; align-items:center; gap:1rem; padding:.9rem 1.2rem; margin:.4rem 0 .8rem;
  border-radius:.9rem; border:1px solid rgba(245,158,11,.35); background:rgba(245,158,11,.07);}
.owl {font-size:2.2rem; line-height:1; position:relative; display:inline-block;
  animation:owl-bob 1.6s ease-in-out infinite;}
.owl::after {content:"✨"; position:absolute; top:-.35rem; right:-.8rem; font-size:.95rem;
  animation:owl-spark 1.6s ease-in-out infinite;}
@keyframes owl-bob {0%,100% {transform:translateY(0) rotate(-5deg)} 50% {transform:translateY(-5px) rotate(5deg)}}
@keyframes owl-spark {0%,100% {opacity:.15; transform:scale(.6) rotate(0)}
  50% {opacity:1; transform:scale(1.15) rotate(30deg)}}
.owl-shine {font-weight:600; color:transparent; -webkit-background-clip:text; background-clip:text;
  background-image:linear-gradient(90deg,#9ca3af 0%,#9ca3af 38%,#f59e0b 50%,#9ca3af 62%,#9ca3af 100%);
  background-size:250% 100%; animation:owl-shine 2.2s linear infinite;}
@keyframes owl-shine {from {background-position:100% 0} to {background-position:0% 0}}
.owl-words {position:relative; height:1.6em; min-width:15rem;}
.owl-words > span {position:absolute; left:0; top:0; white-space:nowrap; opacity:0;
  animation:owl-word var(--loop) infinite;}
.owl-steps {font-size:.9rem; line-height:1.7; margin-top:.25rem; opacity:.85;}
.owl-todo {opacity:.45;}
.owl-spin {display:inline-block; width:.75em; height:.75em; margin-right:.15em; vertical-align:-.05em;
  border:2px solid #f59e0b; border-right-color:transparent; border-radius:50%;
  animation:owl-turn .8s linear infinite;}
@keyframes owl-turn {to {transform:rotate(360deg)}}
""" + _word_keyframes() + "\n</style>"


def wake_up(steps: list[str], now: int) -> str:
    """steps[:now] are done (✓), steps[now] is running (spinner), the rest are still to come."""
    lines = []
    for i, step in enumerate(steps):
        if i < now:
            lines.append(f"<div>✅ {step}</div>")
        elif i == now:
            lines.append(f'<div><span class="owl-spin"></span> {step}...</div>')
        else:
            lines.append(f'<div class="owl-todo">○ {step}</div>')
    return (f'{CSS}<div class="owl-box"><span class="owl">🦉</span><div>'
            f'<div class="owl-shine">Waking up the owl</div>'
            f'<div class="owl-steps">{"".join(lines)}</div></div></div>')


def thinking() -> str:
    words = "".join(f'<span style="animation-delay:{i * EVERY}s"><span class="owl-shine">{w}</span></span>'
                    for i, w in enumerate(WORDS))
    return (f'{CSS}<div class="owl-box"><span class="owl">🦉</span>'
            f'<div class="owl-words" style="--loop:{len(WORDS) * EVERY}s">{words}</div></div>')
