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

You need **two credentials**, both kept locally and git-ignored:

1. **Google access** — a *service account* is the recommended identity (headless, no browser, its own non-human author). Create a Google Cloud project, enable the Drive + Docs APIs, create a service-account key, and save it next to the script as `credentials.json`. Full walkthrough (and the alternative OAuth-account route) in **[SETUP_GOOGLE.md](SETUP_GOOGLE.md)**.
2. **Anthropic API key** — only needed for `run` / `auto` (Claude-generated rewrites). Get one from the [Anthropic Console](https://console.anthropic.com) → **API Keys** → **Create Key**, then put it in a `.env` beside the script (the script loads it automatically). Copy **[.env.example](.env.example)** to `.env` and fill it in.

```sh
pip install -r requirements.txt          # google-api-python-client, google-auth-oauthlib, anthropic
# save the service-account key as credentials.json — see SETUP_GOOGLE.md
cp .env.example .env                      # then add your ANTHROPIC_API_KEY
python3 gdocs_review.py auth             # confirms which account you're authenticated as
```

Then **share** each doc you want reviewed with the service-account email (Editor). Its address is shown by `gdocs_review.py auth` and looks like `claude@<project>.iam.gserviceaccount.com`.

### The loop

1. In Google Docs, highlight text and add a comment that **@mentions the Claude account** — "@claude tighten this", "@claude delete this section", etc.
2. Claude generates a rewrite and posts it as a **proposal** reply in the thread.
3. You reply **👍** (or "yes") to approve — Claude then **applies** the edit to the highlighted text and leaves the thread open so its confirmation stays visible. (Reply anything else, or edit your instruction, to iterate.)

You can drive this manually (`run` then `apply`), or let the autonomous watcher do it for you (below).

### `gdocs_review.py` commands

```sh
python3 gdocs_review.py auth                                  # confirm identity (service account or OAuth)
python3 gdocs_review.py status   <doc>                        # open threads + doc body
python3 gdocs_review.py run      <doc> [--model ID]           # propose rewrites on @claude threads (Claude API)
python3 gdocs_review.py apply    <comment_id> "new" <doc>     # apply an approved rewrite (--resolve to close)
python3 gdocs_review.py auto     [--interval SECONDS] [-v]    # autonomous pass over ALL shared docs
python3 gdocs_review.py reply    <comment_id> "msg" <doc>     # reply in a thread (--resolve to close it)
python3 gdocs_review.py resolve  <comment_id> <doc>           # resolve a thread (--note "…")
python3 gdocs_review.py comment  "msg" <doc> [--quote "text"] # new (un-anchored) comment
python3 gdocs_review.py replace  "old" "new" <doc>            # edit the doc text directly (Docs API)
```

`<doc>` is a full Google Docs URL or a bare document id. The default model is `claude-opus-4-8` (override with `--model` or `ANTHROPIC_MODEL` in `.env`). Credentials and the cached token live next to the script and in `.review/` (both git-ignored).

### Autonomous mode (the "just works" loop)

`auto` reconciles **every doc shared with the account** in one pass: it applies any 👍-approved rewrites, then proposes on new `@claude` threads. With `--interval`, it loops forever, keeping the Google clients warm — the persistent-watcher mode meant to run under a scheduler.

To run it continuously on Linux, install it as a **systemd user service** so it survives logout and reboot:

```ini
# ~/.config/systemd/user/gdocs-review.service
[Unit]
Description=Claude Google Docs review watcher
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory=/path/to/claude-doc-review
ExecStart=/path/to/claude-doc-review/.venv/bin/python3 /path/to/claude-doc-review/gdocs_review.py auto --interval 15
Restart=always
RestartSec=10

[Install]
WantedBy=default.target
```

```sh
systemctl --user daemon-reload
systemctl --user enable --now gdocs-review.service
loginctl enable-linger "$USER"     # start at boot without an interactive login
```

Inspect it with `journalctl _SYSTEMD_USER_UNIT=gdocs-review.service` (idle passes are silent). After editing `gdocs_review.py`, run `systemctl --user restart gdocs-review.service` to pick up the change.

> ⚠️ The watcher writes to docs **autonomously once you 👍** — the 👍 is the only gate — and it acts on *every* doc shared with the service account. Share deliberately.

## Notes

- Without the GUI you can review in any editor using CriticMarkup directly; `review.py` reads it the same way, and picks up direct prose rewrites via the baseline diff.
- Markdown mode sends nothing anywhere — the server binds to `127.0.0.1` and only reads/writes the file you point it at. Google Docs mode necessarily talks to Google's API (it's your doc, on Google's servers); it talks only to Google and your local Claude.
