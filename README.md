# claude-doc-review

A tiny, local, dependency-free system for reviewing a Markdown document with [Claude Code](https://claude.com/claude-code) — comment by selecting text, edit prose inline, and see Claude's edits as tracked-change suggestions you can accept, reject, or comment on. Everything stays on your machine.

Two parts:

- **`reviewer.py`** — a local web GUI (Python stdlib only). Select text to comment, click any block to edit it inline (autosaves), download the result. Claude's edits show as suggestions: green = added, ~~struck red~~ = removed.
- **`review.py`** — the CLI Claude runs to read your comments and edits, reply, and resolve.

Comments live in a sidecar file (`.review/<doc>.comments.json`) next to the document, so the Markdown itself stays clean. Suggestions live inline as [CriticMarkup](http://criticmarkup.com/) (`{++add++}`, `{--cut--}`, `{~~old~>new~~}`), which both the GUI and `review.py` understand.

## Requirements

- Python 3 (standard library only — no `pip install`).
- A browser. The rendered preview pulls a Markdown library from a CDN, so styling needs internet; offline it falls back to raw text and commenting still works.

## Quick start

```sh
python3 reviewer.py --file path/to/your-doc.md
# open http://localhost:8042   (Ctrl-C to stop)
```

In the browser:

- **Comment** — select any text → a box pops up → type → *Comment* (⌘/Ctrl-Enter). The marked text highlights; the comment appears in the side panel.
- **Edit** — click any paragraph/heading/table; it becomes raw Markdown in place; click away (or Esc) and it re-renders. Edits autosave to the file.
- **Suggestions** — Claude's edits render as green (added) / struck (removed). Click one to **Accept**, **Reject**, or **Comment**. They appear live without a reload.
- **Download .md** — saves the current document.

If the port is taken: `lsof -ti tcp:8042 | xargs kill -9`, or pass `--port N`.

## The review loop

1. You comment and/or edit in the GUI.
2. Tell Claude you've done a pass.
3. Claude runs `review.py status` to read every comment (with the marked text), proposed edits, and your direct prose edits since the last baseline.
4. Claude addresses them — editing the doc (as suggestions), replying to comments — then `review.py sync` to reset the baseline.
5. Repeat.

## `review.py` commands

```sh
python3 review.py status  --file DOC     # comments + proposed edits + your direct edits since baseline
python3 review.py sync    --file DOC     # snapshot current text as the new baseline
python3 review.py reply <id> "msg" --file DOC   # reply to a GUI comment (shows in the GUI)
python3 review.py resolve <id> [<id>…]  --file DOC
python3 review.py clean   --file DOC     # print the doc with all CriticMarkup applied (clean export)
python3 review.py accept  --file DOC     # apply all CriticMarkup to the file in place
```

State lives in a `.review/` folder beside the document (git-ignored).

## Install as a Claude Code skill

`SKILL.md` packages this as a user-level skill. Copy the three files into `~/.claude/skills/doc-review/`, and any Claude Code session can spin up the GUI and run the loop when you ask it to "set up doc review for <file>".

## Notes

- Without the GUI you can review in any editor using CriticMarkup directly; `review.py` reads it the same way, and picks up direct prose rewrites via the baseline diff.
- Nothing is sent anywhere — the server binds to `127.0.0.1` and only reads/writes the file you point it at.
