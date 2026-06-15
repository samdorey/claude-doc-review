#!/usr/bin/env python3
"""Review tool for iterating on a Markdown doc with a human reviewer.

It surfaces three things in one place so Claude can act on them:
  1. Comments    — CriticMarkup highlights + comments: {==marked text==}{>>comment<<}
                   (or a standalone {>>comment<<} anchored to the text before it).
  2. Proposed edits — CriticMarkup additions/deletions/substitutions:
                   {++add++}  {--delete--}  {~~old~>new~~}
  3. Direct edits — prose the reviewer changed by typing over it, with no markup.
                   Detected by diffing against the last synced baseline.

Usage:
  python3 review.py [status]   Show comments, proposed edits, and direct edits. (default)
  python3 review.py sync       Snapshot the current clean text as the new baseline.
  python3 review.py accept     Apply all CriticMarkup to the file (adds in, dels out,
                               subs -> new, comments/highlights removed) and re-sync.
  python3 review.py clean      Print the clean (markup-applied) doc to stdout.

Options:
  --file PATH                  Target doc (default: "document.md"
                               next to this script).
"""
import os
import re
import sys
import json
import argparse
import difflib

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_DOC = os.path.join(HERE, "document.md")


def review_dir(doc):
    return os.path.join(os.path.dirname(os.path.abspath(doc)), ".review")

SUB = re.compile(r"\{~~(.*?)~>(.*?)~~\}", re.DOTALL)
ADD = re.compile(r"\{\+\+(.*?)\+\+\}", re.DOTALL)
DEL = re.compile(r"\{--(.*?)--\}", re.DOTALL)
HL = re.compile(r"\{==(.*?)==\}", re.DOTALL)
COM = re.compile(r"\{>>(.*?)<<\}", re.DOTALL)
HL_BEFORE = re.compile(r"\{==(.*?)==\}\s*$", re.DOTALL)


def baseline_path(doc):
    return os.path.join(review_dir(doc), os.path.basename(doc) + ".baseline.md")


def comments_path(doc):
    return os.path.join(review_dir(doc), os.path.basename(doc) + ".comments.json")


def load_gui_comments(doc):
    p = comments_path(doc)
    if not os.path.exists(p):
        return []
    with open(p, encoding="utf-8") as f:
        return json.load(f).get("comments", [])


def save_gui_comments(doc, comments):
    with open(comments_path(doc), "w", encoding="utf-8") as f:
        json.dump({"comments": comments}, f, indent=2, ensure_ascii=False)


def accepted_view(t):
    """The doc as it reads with every CriticMarkup proposal applied."""
    t = SUB.sub(lambda m: m.group(2), t)
    t = ADD.sub(lambda m: m.group(1), t)
    t = DEL.sub("", t)
    t = HL.sub(lambda m: m.group(1), t)
    t = COM.sub("", t)
    return t


def rejected_view(t):
    """The prose with every proposal rejected and all markup stripped.

    This is the baseline for direct-edit detection: proposals vanish, so any
    diff against the baseline is a change the reviewer typed directly."""
    t = SUB.sub(lambda m: m.group(1), t)
    t = ADD.sub("", t)
    t = DEL.sub(lambda m: m.group(1), t)
    t = HL.sub(lambda m: m.group(1), t)
    t = COM.sub("", t)
    return t


def lineno(t, idx):
    return t.count("\n", 0, idx) + 1


def squash(s, n):
    s = re.sub(r"\s+", " ", s).strip()
    return (s[: n - 1] + "…") if len(s) > n else s


def parse_comments(text):
    items = []
    for i, m in enumerate(COM.finditer(text), 1):
        body = m.group(1).strip()
        pre = text[: m.start()]
        hm = HL_BEFORE.search(pre)
        if hm:
            marked, anchor_idx, kind = hm.group(1), hm.start(), "marked text"
        else:
            marked, anchor_idx, kind = rejected_view(pre)[-160:], m.start(), "text before comment"
        items.append({
            "id": f"C{i}",
            "line": lineno(text, anchor_idx),
            "kind": kind,
            "marked": squash(marked, 200),
            "comment": squash(body, 400),
        })
    return items


def parse_edits(text):
    edits = []
    for m in SUB.finditer(text):
        edits.append((lineno(text, m.start()), "substitution",
                      f'"{squash(m.group(1), 90)}"  ->  "{squash(m.group(2), 90)}"'))
    for m in ADD.finditer(text):
        edits.append((lineno(text, m.start()), "addition", f'"{squash(m.group(1), 140)}"'))
    for m in DEL.finditer(text):
        edits.append((lineno(text, m.start()), "deletion", f'"{squash(m.group(1), 140)}"'))
    edits.sort(key=lambda e: e[0])
    return edits


def word_diff(old, new):
    ow, nw = old.split(), new.split()
    sm = difflib.SequenceMatcher(None, ow, nw)
    out = []
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            seg = " ".join(ow[i1:i2])
            out.append(seg if len(seg) <= 60 else "…")
        elif tag == "delete":
            out.append("[-" + " ".join(ow[i1:i2]) + "-]")
        elif tag == "insert":
            out.append("{+" + " ".join(nw[j1:j2]) + "+}")
        elif tag == "replace":
            out.append("[-" + " ".join(ow[i1:i2]) + "-]{+" + " ".join(nw[j1:j2]) + "+}")
    return " ".join(out)


def direct_edits(text, doc):
    bp = baseline_path(doc)
    if not os.path.exists(bp):
        return None
    with open(bp, encoding="utf-8") as f:
        base = f.read()
    cur = rejected_view(text)
    if base == cur:
        return []
    base_p = re.split(r"\n\s*\n", base)
    cur_p = re.split(r"\n\s*\n", cur)
    sm = difflib.SequenceMatcher(None, base_p, cur_p)
    blocks = []
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            continue
        old = "\n\n".join(base_p[i1:i2]).strip()
        new = "\n\n".join(cur_p[j1:j2]).strip()
        if tag == "insert":
            blocks.append(("added paragraph", squash(new, 300)))
        elif tag == "delete":
            blocks.append(("deleted paragraph", squash(old, 300)))
        else:
            blocks.append(("changed", word_diff(old, new)))
    return blocks


def find_occurrence(hay, needle, occ):
    idx = -1
    for _ in range(occ + 1):
        idx = hay.find(needle, idx + 1)
        if idx < 0:
            return -1
    return idx


def cmd_status(text, doc):
    title = os.path.basename(doc)
    print("REVIEW STATUS — " + title)
    print("=" * 64)

    gui = [c for c in load_gui_comments(doc) if not c.get("resolved")]
    print(f"\nGUI COMMENTS ({len(gui)})")
    print("-" * 64)
    if not gui:
        print("  (none)")
    for c in gui:
        off = find_occurrence(text, c.get("quote", ""), c.get("occ", 0))
        loc = f"line {lineno(text, off)}" if off >= 0 else "TEXT CHANGED — no longer anchors"
        print(f"[{c['id']}] {loc} · marked text:")
        print(f'     "{squash(c.get("quote", ""), 200)}"')
        print(f"     >> {squash(c.get('comment', ''), 400)}")
        if c.get("reply"):
            print(f"     (your reply: {squash(c['reply'], 200)})")
        print()

    comments = parse_comments(text)
    print(f"INLINE COMMENTS ({len(comments)})")
    print("-" * 64)
    if not comments:
        print("  (none)")
    for c in comments:
        print(f"[{c['id']}] line {c['line']} · {c['kind']}:")
        print(f'     "{c["marked"]}"')
        print(f"     >> {c['comment']}")
        print()

    edits = parse_edits(text)
    print(f"PROPOSED EDITS ({len(edits)})")
    print("-" * 64)
    if not edits:
        print("  (none)")
    for line, kind, desc in edits:
        print(f"  • {kind} @ line {line}: {desc}")

    de = direct_edits(text, doc)
    print()
    if de is None:
        print("DIRECT EDITS: no baseline yet — run `python3 review.py sync` to start tracking.")
    else:
        print(f"DIRECT EDITS since last sync (treat as intentional) ({len(de)} block(s))")
        print("-" * 64)
        if not de:
            print("  (none)")
        for kind, desc in de:
            print(f"  ~ {kind}: {desc}")

    print()
    print("=" * 64)
    print("After processing this round, run `python3 review.py sync` to reset the baseline.")


def cmd_sync(text, doc):
    os.makedirs(review_dir(doc), exist_ok=True)
    with open(baseline_path(doc), "w", encoding="utf-8") as f:
        f.write(rejected_view(text))
    print(f"Baseline synced for {os.path.basename(doc)}.")


def cmd_accept(text, doc):
    with open(doc, "w", encoding="utf-8") as f:
        f.write(accepted_view(text))
    with open(doc, encoding="utf-8") as f:
        cmd_sync(f.read(), doc)
    print("All CriticMarkup applied to the file and baseline re-synced.")


def cmd_reply(doc, cid, message):
    comments = load_gui_comments(doc)
    hit = next((c for c in comments if c["id"] == cid), None)
    if not hit:
        sys.exit(f"No GUI comment with id {cid}")
    hit["reply"] = message
    save_gui_comments(doc, comments)
    print(f"Replied to {cid} (shows in the GUI under the comment).")


def cmd_resolve(doc, ids):
    comments = load_gui_comments(doc)
    known = {c["id"] for c in comments}
    for c in comments:
        if c["id"] in ids:
            c["resolved"] = True
    save_gui_comments(doc, comments)
    missing = [i for i in ids if i not in known]
    print(f"Resolved: {', '.join(i for i in ids if i in known) or '(none)'}"
          + (f" · unknown ids: {', '.join(missing)}" if missing else ""))


def main():
    ap = argparse.ArgumentParser(description="Markdown review helper.")
    ap.add_argument("command", nargs="?", default="status",
                    choices=["status", "sync", "accept", "clean", "reply", "resolve"])
    ap.add_argument("args", nargs="*", help="for reply: <id> <message…>; for resolve: <id> [<id>…]")
    ap.add_argument("--file", default=DEFAULT_DOC)
    args = ap.parse_args()

    doc = args.file
    if not os.path.exists(doc):
        sys.exit(f"Doc not found: {doc}")
    with open(doc, encoding="utf-8") as f:
        text = f.read()

    if args.command == "status":
        cmd_status(text, doc)
    elif args.command == "sync":
        cmd_sync(text, doc)
    elif args.command == "accept":
        cmd_accept(text, doc)
    elif args.command == "clean":
        sys.stdout.write(accepted_view(text))
    elif args.command == "reply":
        if len(args.args) < 2:
            sys.exit("usage: review.py reply <id> <message…>")
        cmd_reply(doc, args.args[0], " ".join(args.args[1:]))
    elif args.command == "resolve":
        if not args.args:
            sys.exit("usage: review.py resolve <id> [<id>…]")
        cmd_resolve(doc, args.args)


if __name__ == "__main__":
    main()
