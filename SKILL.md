---
name: doc-review
description: Spin up a local browser GUI to review a Markdown/text document — select text to leave comments, click any block to edit it inline (autosaves), and iterate with the user comment-by-comment. Use when the user wants to review/comment on a doc or draft, mark up text, edit prose with a nice live-preview editor, or asks to "set up doc review", "open the reviewer", or "let me comment on this file". Works on any .md/.txt file.
---

# Doc review

A two-part local tool for reviewing a Markdown document with a human, with no data leaving the machine.

- `reviewer.py` — a local web GUI. The user selects text to comment (no markup to type), and clicks any block to edit it as raw Markdown in place (it re-renders on blur). Edits autosave to the file. Comments are stored in a sidecar `<doc-dir>/.review/<doc>.comments.json`, so the document itself stays clean.
- `review.py` — the CLI **you** run to read the user's comments and edits, reply, and resolve.

Scripts live in this skill's directory: `~/.claude/skills/doc-review/`. They are relocatable — state always lives in a `.review/` folder beside the target doc, never beside the scripts. Use the user's `python3` (stdlib only; no installs needed). The rendered preview pulls a Markdown library from a CDN, so styling needs internet; offline it falls back to raw text and commenting still works.

## Start the GUI

```
python3 ~/.claude/skills/doc-review/reviewer.py --file "<absolute path to doc.md>" [--port 8042]
```

Run it in the background, then tell the user to open `http://localhost:<port>`. If the port is taken (`Address already in use`), free it first: `lsof -ti tcp:8042 | xargs kill -9`, or pick another `--port`.

On first use of a doc, initialise direct-edit tracking once:

```
python3 ~/.claude/skills/doc-review/review.py sync --file "<doc>"
```

## The iteration loop

1. The user comments and/or edits in the GUI (or in any editor — see below).
2. When the user says they've done a pass, run:
   ```
   python3 ~/.claude/skills/doc-review/review.py status --file "<doc>"
   ```
   This prints, in one place:
   - **GUI comments** — each with the exact text the user marked, its line, and any prior reply. A comment whose marked text no longer exists is flagged "TEXT CHANGED".
   - **Inline comments / proposed edits** — any CriticMarkup the user typed directly (`{>>…<<}`, `{++…++}`, `{--…--}`, `{~~a~>b~~}`).
   - **Direct edits** — prose the user changed by typing over it, word-diffed against the last baseline, to be treated as intentional.
3. Address each item. **Make your own edits as suggestions, not silent changes**, so the user can see and judge them: write CriticMarkup into the doc with the Edit tool — `{~~old~>new~~}` to reword, `{++added++}` to insert, `{--removed--}` to cut. The GUI renders these as tracked changes (green = added, struck red = removed) live, and the user can accept, reject, or comment on each. Respond to GUI comments with
   ```
   python3 ~/.claude/skills/doc-review/review.py reply <id> "<message>" --file "<doc>"
   python3 ~/.claude/skills/doc-review/review.py resolve <id> [<id>…] --file "<doc>"
   ```
   Replies show under the comment in the GUI; resolved comments drop out of the open list.
4. Reset the baseline so the next round's direct-edit diff is clean:
   ```
   python3 ~/.claude/skills/doc-review/review.py sync --file "<doc>"
   ```
5. Repeat until the user is done.

## Other commands

```
python3 .../review.py clean  --file "<doc>"   # print the doc with all CriticMarkup applied (clean export)
python3 .../review.py accept --file "<doc>"   # apply inline CriticMarkup to the file in place
```

## Working without the GUI

The user can also review in any text editor using CriticMarkup — `review.py status` reads it the same way: `{==text==}{>>comment<<}` (mark + comment), `{>>comment<<}` (quick comment), `{++add++}`, `{--cut--}`, `{~~old~>new~~}`. Direct prose rewrites are picked up by the baseline diff regardless.
