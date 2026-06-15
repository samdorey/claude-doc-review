---
name: doc-review
description: Review a document with a human comment-by-comment. Two modes — (1) Markdown/text via a local browser GUI (select text to comment, edit inline, autosaves); (2) a real Google Doc via Google's native comment threads (a "Claude Review" account replies in-thread). Use when the user wants to review/comment on a doc or draft, mark up text, edit prose, asks to "set up doc review", "open the reviewer", "let me comment on this file", or to review a Google Doc / Google Docs URL.
---

# Doc review

This skill has two modes. Pick by what the user points you at:

- A **`.md`/`.txt` file or local path** → **Markdown mode** (local GUI, below).
- A **Google Doc / Google Docs URL** → **Google Docs mode** (jump to that section).

## Markdown mode

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

# Google Docs mode

When the user gives you a **Google Doc** (a Docs URL or document id), use `gdocs_review.py` instead. It works against Google's native comments: the user highlights text and comments in Google Docs, and **you reply inside those threads as the "Claude Review" account**.

Why replies (not new highlighted comments): the Drive API can read anchored comments but can't create them — anything you post fresh shows as un-anchored. Replies stay inside the thread the user anchored, so your feedback stays attached to their text. The Docs API also can't create native "suggested edits", so this mode is comment-driven. Make actual text changes only when the user asks; use the `replace` command and tell them in the thread.

**Setup gate.** This mode needs one-time setup (a "Claude Review" Google account + OAuth credentials). If `gdocs_review.py status` errors about missing `credentials.json` or auth, point the user to `SETUP_GOOGLE.md` and stop — don't try to work around it. To check sign-in: `python3 gdocs_review.py auth` (prints the authenticated account).

## The iteration loop

1. The user highlights text and comments in Google Docs, then says they've done a pass.
2. Read everything:
   ```
   python3 .../gdocs_review.py status "<doc url or id>"
   ```
   This prints every open comment thread — the highlighted text, the user's note, the comment id, and any prior replies — followed by the full doc body for context.
3. Address each thread. **Reply in-thread as Claude Review** with your proposed rewrite or answer; resolve threads you've handled:
   ```
   python3 .../gdocs_review.py reply <comment_id> "<message>" "<doc>"          # add --resolve to close it too
   python3 .../gdocs_review.py resolve <comment_id> "<doc>" [--note "<note>"]
   ```
   Propose rewrites in the reply text so the user can apply them. Edit the doc body directly only if the user asked you to "just fix it":
   ```
   python3 .../gdocs_review.py replace "<old text>" "<new text>" "<doc>"
   ```
4. The user reads your replies in the Google Docs comment sidebar and either resolves more or comments again. Repeat.

Scripts live in this skill's directory (`~/.claude/skills/doc-review/`). Use the user's `python3`; the Google libraries from `requirements.txt` must be installed (`pip install -r requirements.txt`).
