#!/usr/bin/env python3
"""Review a Google Doc with Claude through the native comment system.

This is the Google Docs counterpart to review.py. Instead of a local Markdown
file with CriticMarkup, it works against a real Google Doc using Google's own
comments — the ones you get by highlighting text and hitting "Add comment".

The loop:
  1. You highlight text and comment in Google Docs (natively anchored).
  2. You tell Claude: "do a review pass on <doc url>".
  3. Claude runs `gdocs_review.py status <url>` to read every open thread
     (the highlighted text, your note, any prior replies) plus the doc body.
  4. Claude replies in each thread as the "Claude Review" account, proposing
     rewrites or answering, then resolves what it has handled.
  5. You read the replies right in the Google Docs comment sidebar. Repeat.

Why replies and not new highlighted comments? The Drive API can read anchored
comments but cannot *create* them — comments it posts are always shown as
un-anchored by the Docs editor. Replies, however, land inside the thread you
anchored, so Claude's feedback stays attached to your highlighted text.

Commands:
  gdocs_review.py auth                          One-time sign-in (as Claude Review).
  gdocs_review.py status <doc>                  Open threads + doc body for context.
  gdocs_review.py run <doc> [--model ID]        For each open thread addressed to Claude
                                                with no reply yet, generate a rewrite via
                                                the Claude API and post it as a proposal.
  gdocs_review.py reply <comment_id> "msg" <doc> Reply in a thread, as Claude Review.
  gdocs_review.py resolve <comment_id> <doc>    Resolve a thread (optionally with a note).
  gdocs_review.py comment "msg" <doc> [--quote "text"]
                                                Post a new (un-anchored) comment.
  gdocs_review.py apply <comment_id> "new" <doc> [--resolve]
                                                Apply an approved rewrite to a thread's
                                                anchored text (leaves the thread open
                                                unless --resolve is given).
  gdocs_review.py replace "old" "new" <doc>     Edit the doc text directly (Docs API).

<doc> may be a full Google Docs URL or a bare document id.

Setup (one time): see SETUP_GOOGLE.md. In short — create a "Claude Review"
Google account, a Google Cloud project with the Drive + Docs APIs enabled and
an OAuth "desktop app" client, save the client secrets next to this script as
`credentials.json`, then run `gdocs_review.py auth` and sign in as Claude Review.
"""
import os
import re
import sys
import argparse

HERE = os.path.dirname(os.path.abspath(__file__))
CREDENTIALS = os.path.join(HERE, "credentials.json")
TOKEN = os.path.join(HERE, ".review", "google-token.json")

# Drive scope is needed to read/post comments; documents to read/edit the body.
SCOPES = [
    "https://www.googleapis.com/auth/drive",
    "https://www.googleapis.com/auth/documents",
]

DOC_ID_RE = re.compile(r"/document/d/([a-zA-Z0-9_-]+)")


def die(msg):
    sys.exit("error: " + msg)


def doc_id(ref):
    """Accept a full Docs URL or a bare id and return the document id."""
    m = DOC_ID_RE.search(ref)
    if m:
        return m.group(1)
    if "/" in ref or " " in ref:
        die(f"could not find a document id in: {ref}")
    return ref


def _is_service_account(path):
    """credentials.json may be an OAuth desktop client or a service-account key."""
    try:
        import json
        with open(path, encoding="utf-8") as f:
            return json.load(f).get("type") == "service_account"
    except (OSError, ValueError):
        return False


def services():
    """Build authenticated Drive + Docs API clients.

    credentials.json may be either a service-account key (no browser; the SA is
    itself the 'Claude Review' identity) or an OAuth desktop client (interactive
    sign-in as a real account, token cached under .review/).
    """
    try:
        from googleapiclient.discovery import build
    except ImportError:
        die("missing dependencies. Run:  pip install -r requirements.txt")

    if not os.path.exists(CREDENTIALS):
        die(
            "no credentials.json found next to this script.\n"
            "See SETUP_GOOGLE.md — save either a service-account key or an OAuth "
            "desktop client as:\n  " + CREDENTIALS
        )

    if _is_service_account(CREDENTIALS):
        from google.oauth2 import service_account
        creds = service_account.Credentials.from_service_account_file(
            CREDENTIALS, scopes=SCOPES
        )
    else:
        from google.oauth2.credentials import Credentials
        from google.auth.transport.requests import Request
        from google_auth_oauthlib.flow import InstalledAppFlow

        creds = None
        if os.path.exists(TOKEN):
            creds = Credentials.from_authorized_user_file(TOKEN, SCOPES)
        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                flow = InstalledAppFlow.from_client_secrets_file(CREDENTIALS, SCOPES)
                print("Sign in as the *Claude Review* account in the browser that opens "
                      "(or, over SSH, the URL printed below — make sure port 8765 is forwarded).")
                creds = flow.run_local_server(port=8765, open_browser=False)
            os.makedirs(os.path.dirname(TOKEN), exist_ok=True)
            with open(TOKEN, "w", encoding="utf-8") as f:
                f.write(creds.to_json())

    drive = build("drive", "v3", credentials=creds, cache_discovery=False)
    docs = build("docs", "v1", credentials=creds, cache_discovery=False)
    return drive, docs


def whoami(drive):
    about = drive.about().get(fields="user(displayName,emailAddress)").execute()
    u = about.get("user", {})
    return u.get("displayName", "?"), u.get("emailAddress", "?")


def squash(s, n):
    s = re.sub(r"\s+", " ", (s or "")).strip()
    return (s[: n - 1] + "…") if len(s) > n else s


COMMENT_FIELDS = (
    "comments(id,content,resolved,createdTime,modifiedTime,"
    "author/displayName,quotedFileContent/value,"
    "replies(id,content,createdTime,author/displayName,action)),nextPageToken"
)


def list_comments(drive, did, include_resolved=False):
    out, token = [], None
    while True:
        resp = drive.comments().list(
            fileId=did, fields=COMMENT_FIELDS, pageSize=100,
            includeDeleted=False, pageToken=token,
        ).execute()
        out.extend(resp.get("comments", []))
        token = resp.get("nextPageToken")
        if not token:
            break
    if not include_resolved:
        out = [c for c in out if not c.get("resolved")]
    return out


def doc_text(docs, did):
    """Return the document body as plain text (paragraphs joined by newlines)."""
    doc = docs.documents().get(documentId=did).execute()
    chunks = []
    for el in doc.get("body", {}).get("content", []):
        para = el.get("paragraph")
        if not para:
            continue
        line = "".join(
            r.get("textRun", {}).get("content", "")
            for r in para.get("elements", [])
        )
        chunks.append(line)
    return doc.get("title", ""), "".join(chunks)


# ---- commands ---------------------------------------------------------------

def cmd_auth(args):
    drive, _ = services()
    name, email = whoami(drive)
    print(f"Authenticated as: {name} <{email}>")
    if _is_service_account(CREDENTIALS):
        print("Using a service-account key. Share each doc with this address as "
              "Editor; replies are authored by this account.")
    else:
        if "review" not in (name + email).lower():
            print("note: this doesn't look like the 'Claude Review' account — "
                  "replies will be authored by whoever you signed in as.")
        print(f"Token cached at: {TOKEN}")


def cmd_status(args):
    drive, docs = services()
    did = doc_id(args.doc)
    title, body = doc_text(docs, did)
    comments = list_comments(drive, did)

    print("REVIEW STATUS — " + (title or did))
    print("=" * 64)
    print(f"\nOPEN COMMENT THREADS ({len(comments)})")
    print("-" * 64)
    if not comments:
        print("  (none)")
    for c in comments:
        import html
        quoted = squash(html.unescape(c.get("quotedFileContent", {}).get("value", "")), 200)
        author = c.get("author", {}).get("displayName", "?")
        print(f"[{c['id']}] by {author}" + (f" · on: \"{quoted}\"" if quoted else " · (no highlight)"))
        print(f"     >> {squash(c.get('content', ''), 500)}")
        for r in c.get("replies", []):
            ra = r.get("author", {}).get("displayName", "?")
            tag = f" [{r['action']}]" if r.get("action") else ""
            print(f"        ↳ {ra}{tag}: {squash(r.get('content', ''), 400)}")
        print()

    print("=" * 64)
    print("DOC BODY (for context)")
    print("-" * 64)
    print(body.rstrip())
    print("=" * 64)
    print('Reply with:    gdocs_review.py reply <comment_id> "your message" ' + args.doc)
    print("Resolve with:  gdocs_review.py resolve <comment_id> " + args.doc)


RUN_SYSTEM = (
    "You are a careful copy editor working inside a Google Doc. You are given the "
    "full document for context, a highlighted excerpt from it, and the reader's "
    "instruction about that excerpt. Produce a revised version of ONLY the "
    "highlighted excerpt that satisfies the instruction while preserving the "
    "author's meaning, voice, and the flow into the surrounding text. Output only "
    "the replacement text — no quotation marks, no preamble, no explanation."
)


def _thread_instruction(comment, claude_email):
    """The reader's request: the comment plus any of their follow-up replies."""
    import html
    parts = [html.unescape(comment.get("content", "")).strip()]
    for r in comment.get("replies", []):
        if r.get("author", {}).get("displayName") == claude_email:
            continue
        text = html.unescape(r.get("content", "")).strip()
        if text:
            parts.append(text)
    return "\n".join(p for p in parts if p)


def cmd_run(args):
    import html
    if not os.environ.get("ANTHROPIC_API_KEY"):
        die("ANTHROPIC_API_KEY is not set. Export your Claude API key first.")
    try:
        import anthropic
    except ImportError:
        die("the 'anthropic' package is missing. Run:  pip install -r requirements.txt")

    model = args.model or os.environ.get("ANTHROPIC_MODEL") or "claude-sonnet-4-6"

    drive, docs = services()
    did = doc_id(args.doc)
    _, claude_email = whoami(drive)
    title, body = doc_text(docs, did)
    comments = list_comments(drive, did)

    def addressed_to_claude(c):
        blob = c.get("content", "") + " " + " ".join(
            r.get("content", "") for r in c.get("replies", [])
        )
        low = blob.lower()
        return claude_email.lower() in low or "@claude" in low

    def already_handled(c):
        return any(
            r.get("author", {}).get("displayName") == claude_email
            for r in c.get("replies", [])
        )

    todo = [
        c for c in comments
        if c.get("quotedFileContent", {}).get("value")
        and addressed_to_claude(c)
        and not already_handled(c)
    ]

    print(f"Doc: {title or did}")
    print(f"Model: {model}")
    print(f"Open threads for Claude with no reply yet: {len(todo)}")
    if not todo:
        return

    client = anthropic.Anthropic()
    system = [
        {"type": "text", "text": RUN_SYSTEM},
        {
            "type": "text",
            "text": f"FULL DOCUMENT (for context only):\n\n{body}",
            "cache_control": {"type": "ephemeral"},
        },
    ]

    for c in todo:
        excerpt = html.unescape(c.get("quotedFileContent", {}).get("value", ""))
        instruction = _thread_instruction(c, claude_email)
        user = (
            f"Highlighted excerpt:\n{excerpt}\n\n"
            f"Reader's instruction:\n{instruction}\n\n"
            "Return only the rewritten replacement for the highlighted excerpt."
        )
        resp = client.messages.create(
            model=model,
            max_tokens=2000,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        rewrite = "".join(b.text for b in resp.content if b.type == "text").strip()
        cached = resp.usage.cache_read_input_tokens
        body_reply = (
            "Proposed rewrite (reply 👍 / yes to apply):\n\n" + rewrite
        )
        drive.replies().create(
            fileId=did, commentId=c["id"], body={"content": body_reply},
            fields="id",
        ).execute()
        print(f"[{c['id']}] proposed ({len(rewrite)} chars, cache_read={cached} tok): "
              f"{squash(rewrite, 80)}")


def cmd_reply(args):
    drive, _ = services()
    did = doc_id(args.doc)
    body = {"content": args.message}
    if args.resolve:
        body["action"] = "resolve"
    r = drive.replies().create(
        fileId=did, commentId=args.comment_id, body=body,
        fields="id,content,author/displayName,action",
    ).execute()
    who = r.get("author", {}).get("displayName", "?")
    print(f"Replied to {args.comment_id} as {who}." + (" (resolved)" if args.resolve else ""))


def cmd_resolve(args):
    drive, _ = services()
    did = doc_id(args.doc)
    body = {"action": "resolve", "content": args.note or "Resolved."}
    drive.replies().create(
        fileId=did, commentId=args.comment_id, body=body, fields="id,action",
    ).execute()
    print(f"Resolved {args.comment_id}.")


def cmd_comment(args):
    drive, _ = services()
    did = doc_id(args.doc)
    content = args.message
    if args.quote:
        content = f'Re: "{squash(args.quote, 120)}"\n\n{args.message}'
    c = drive.comments().create(
        fileId=did, body={"content": content}, fields="id,author/displayName",
    ).execute()
    print(f"Posted comment {c['id']} as {c.get('author', {}).get('displayName', '?')}.")
    print("note: API comments show as un-anchored in Google Docs. For feedback tied "
          "to specific text, reply to a comment the user anchored instead.")


def cmd_apply(args):
    """Apply a proposed rewrite tied to a comment's anchored text, then resolve.

    Pulls the comment's highlighted (quoted) text and replaces that exact string
    in the doc with the new text — so the approved change lands on the spot the
    user anchored, without restating the original. Resolves the thread unless
    --no-resolve is given.
    """
    drive, docs = services()
    did = doc_id(args.doc)
    c = drive.comments().get(
        fileId=did, commentId=args.comment_id,
        fields="id,quotedFileContent/value,resolved",
    ).execute()
    import html
    # The API returns quoted text HTML-escaped (e.g. that&#39;s); the doc body
    # holds the literal characters, so unescape before matching.
    original = html.unescape(c.get("quotedFileContent", {}).get("value", ""))
    if not original:
        die(f"comment {args.comment_id} has no anchored text to replace. "
            f'Use `replace "old" "new"` with explicit text instead.')
    res = docs.documents().batchUpdate(
        documentId=did,
        body={"requests": [{
            "replaceAllText": {
                "containsText": {"text": original, "matchCase": True},
                "replaceText": args.new,
            }
        }]},
    ).execute()
    n = res.get("replies", [{}])[0].get("replaceAllText", {}).get("occurrencesChanged", 0)
    if n == 0:
        die(f'the anchored text was not found verbatim in the doc '
            f'(it may have been edited since): "{squash(original, 120)}". No change made.')
    body = {"content": args.note or
            f'Applied your approved change: "{squash(original, 80)}" → "{squash(args.new, 80)}".'}
    if args.resolve:
        body["action"] = "resolve"
    drive.replies().create(
        fileId=did, commentId=args.comment_id, body=body, fields="id,action",
    ).execute()
    # Leave the thread open by default so the confirmation reply stays visible in
    # the sidebar — resolving collapses it out of view into the comment history.
    suffix = " and resolved the thread" if args.resolve else " (thread left open for your review)"
    print(f"Applied change for {args.comment_id} ({n} occurrence(s)){suffix}.")
    if n > 1:
        print(f"note: the anchored text appeared {n} times in the doc — all were "
              "replaced. Check the others weren't unintended.")


def cmd_replace(args):
    _, docs = services()
    did = doc_id(args.doc)
    res = docs.documents().batchUpdate(
        documentId=did,
        body={"requests": [{
            "replaceAllText": {
                "containsText": {"text": args.old, "matchCase": True},
                "replaceText": args.new,
            }
        }]},
    ).execute()
    n = res.get("replies", [{}])[0].get("replaceAllText", {}).get("occurrencesChanged", 0)
    print(f"Replaced {n} occurrence(s) of the text directly in the doc.")


def main():
    ap = argparse.ArgumentParser(description="Review a Google Doc via native comments.")
    sub = ap.add_subparsers(dest="command")

    sub.add_parser("auth", help="one-time sign-in (as the Claude Review account)")

    p = sub.add_parser("status", help="open threads + doc body")
    p.add_argument("doc", help="Google Docs URL or document id")

    p = sub.add_parser("run", help="generate rewrites for open Claude-addressed threads via the Claude API")
    p.add_argument("doc", help="Google Docs URL or document id")
    p.add_argument("--model", help="Claude model id (default: $ANTHROPIC_MODEL or claude-sonnet-4-6)")

    p = sub.add_parser("reply", help="reply in a comment thread")
    p.add_argument("comment_id")
    p.add_argument("message")
    p.add_argument("doc")
    p.add_argument("--resolve", action="store_true", help="resolve the thread after replying")

    p = sub.add_parser("resolve", help="resolve a comment thread")
    p.add_argument("comment_id")
    p.add_argument("doc")
    p.add_argument("--note", help="optional note to leave when resolving")

    p = sub.add_parser("comment", help="post a new (un-anchored) comment")
    p.add_argument("message")
    p.add_argument("doc")
    p.add_argument("--quote", help="text to reference for location context")

    p = sub.add_parser("apply", help="apply an approved rewrite to a comment's anchored text, then resolve")
    p.add_argument("comment_id")
    p.add_argument("new", help="the replacement text the user approved")
    p.add_argument("doc")
    p.add_argument("--note", help="reply text to leave (defaults to a summary of the change)")
    p.add_argument("--resolve", action="store_true",
                   help="also resolve the thread (default: leave it open so the reply stays visible)")

    p = sub.add_parser("replace", help="edit the doc text directly (Docs API)")
    p.add_argument("old")
    p.add_argument("new")
    p.add_argument("doc")

    args = ap.parse_args()
    cmd = args.command or "help"
    fn = {
        "auth": cmd_auth, "status": cmd_status, "run": cmd_run, "reply": cmd_reply,
        "resolve": cmd_resolve, "comment": cmd_comment, "apply": cmd_apply,
        "replace": cmd_replace,
    }.get(cmd)
    if not fn:
        ap.print_help()
        sys.exit(0)
    fn(args)


if __name__ == "__main__":
    main()
