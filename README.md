# claude-doc-review

Review a document with [Claude Code](https://claude.com/claude-code) — comment by selecting text and let Claude respond comment-by-comment. Comes in two modes:

- **Markdown mode** — a tiny, local, dependency-free GUI over a `.md` file. Everything stays on your machine; Claude's edits show as tracked-change suggestions you can accept, reject, or comment on.
- **Google Docs mode** — do it directly in a real Google Doc, using Google's own comment threads. You highlight and comment natively; a dedicated **"Claude Review"** account replies inside your threads. See [Google Docs mode](#google-docs-mode) below.

## Markdown mode

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

## Google Docs mode

Same idea, but the document is a real Google Doc and the comments are Google's own — so you review on any device, in the tool you already use, and a dedicated **"Claude Review"** account answers right inside your comment sidebar.

**Why replies, not new highlighted comments?** The Drive API can *read* anchored comments but can't *create* them — comments it posts always show as un-anchored. Replies, though, land inside the thread you anchored. So you do the highlighting (one selection, "Add comment") and Claude replies in-thread, keeping its feedback attached to your text. (The Docs API also can't create native "suggested edits" at all — only browser automation can — which is why this mode is comment-driven rather than suggestion-driven.)

### One-time setup

Create a "Claude Review" Google account + OAuth credentials, then sign in. Full walkthrough in **[SETUP_GOOGLE.md](SETUP_GOOGLE.md)**. Short version:

```sh
pip install -r requirements.txt          # google-api-python-client, google-auth-oauthlib
# (save OAuth desktop credentials as credentials.json — see SETUP_GOOGLE.md)
python3 gdocs_review.py auth             # sign in as the Claude Review account
```

Then **share** each doc you want reviewed with the Claude Review account (Editor).

### The loop

1. In Google Docs, highlight text and add a comment (natively anchored) — "tighten this", "is this accurate?", etc.
2. Tell Claude: *"do a review pass on `<doc url>`"*.
3. Claude reads every open thread and the doc body, then replies in each thread as **Claude Review** and resolves what it has handled.
4. You read the replies in the Google Docs comment sidebar. Repeat.

### `gdocs_review.py` commands

```sh
python3 gdocs_review.py auth                                  # one-time sign-in
python3 gdocs_review.py status   <doc>                        # open threads + doc body
python3 gdocs_review.py reply    <comment_id> "msg" <doc>     # reply in a thread (--resolve to close it)
python3 gdocs_review.py resolve  <comment_id> <doc>           # resolve a thread (--note "…")
python3 gdocs_review.py comment  "msg" <doc> [--quote "text"] # new (un-anchored) comment
python3 gdocs_review.py replace  "old" "new" <doc>            # edit the doc text directly (Docs API)
```

`<doc>` is a full Google Docs URL or a bare document id. Credentials and the cached token live next to the script and in `.review/` (both git-ignored).

## Notes

- Without the GUI you can review in any editor using CriticMarkup directly; `review.py` reads it the same way, and picks up direct prose rewrites via the baseline diff.
- Markdown mode sends nothing anywhere — the server binds to `127.0.0.1` and only reads/writes the file you point it at. Google Docs mode necessarily talks to Google's API (it's your doc, on Google's servers); it talks only to Google and your local Claude.
