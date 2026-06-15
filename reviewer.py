#!/usr/bin/env python3
"""Local review GUI for a Markdown doc.

Select text in the browser to comment (no markup to type). Click any block to edit it
as raw Markdown in place (re-renders on blur); edits autosave. Claude's edits appear as
tracked-change suggestions — struck-through red for removals, green for additions —
which you can accept, reject, or comment on. Comments live in a sidecar
(.review/<doc>.comments.json) next to the doc; suggestions live inline in the doc as
CriticMarkup, so Claude (via review.py) and you see the same thing.

Run:
    python3 reviewer.py --file "<doc.md>"
then open http://localhost:8042 .  Ctrl-C to stop.
"""
import os
import re
import json
import argparse
import datetime
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_DOC = os.path.join(HERE, "document.md")
DOC = DEFAULT_DOC

# one left-to-right scan over the three suggestion kinds, so sid indices match the client
SUG_RE = re.compile(r"\{~~(.*?)~>(.*?)~~\}|\{\+\+(.*?)\+\+\}|\{--(.*?)--\}", re.S)


def review_dir():
    return os.path.join(os.path.dirname(os.path.abspath(DOC)), ".review")


def comments_path():
    return os.path.join(review_dir(), os.path.basename(DOC) + ".comments.json")


def load_comments():
    p = comments_path()
    if not os.path.exists(p):
        return []
    with open(p, encoding="utf-8") as f:
        return json.load(f).get("comments", [])


def save_comments(comments):
    os.makedirs(review_dir(), exist_ok=True)
    with open(comments_path(), "w", encoding="utf-8") as f:
        json.dump({"comments": comments}, f, indent=2, ensure_ascii=False)


def read_doc():
    with open(DOC, encoding="utf-8") as f:
        return f.read()


def resolve_suggestion(text, sid, action):
    """Apply (accept) or revert (reject) the sid-th suggestion in document order."""
    idx = [0]

    def repl(m):
        i = idx[0]
        idx[0] += 1
        if i != sid:
            return m.group(0)
        if m.group(1) is not None:           # substitution {~~old~>new~~}
            return m.group(2) if action == "accept" else m.group(1)
        if m.group(3) is not None:           # addition {++x++}
            return m.group(3) if action == "accept" else ""
        if m.group(4) is not None:           # deletion {--x--}
            return "" if action == "accept" else m.group(4)
        return m.group(0)

    return SUG_RE.sub(repl, text)


def now_iso():
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M")


PAGE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Review — __TITLE__</title>
<script src="https://cdn.jsdelivr.net/npm/marked/marked.min.js"></script>
<style>
  :root {
    --bg:#fbfbfa; --fg:#1d1d1f; --muted:#6b6b70; --line:#e3e3e0;
    --card:#ffffff; --accent:#c9851b; --mark:#fff2cc; --markborder:#eccb66;
    --edit:rgba(201,133,27,.07); --shadow:0 1px 3px rgba(0,0,0,.07);
    --ins:#1a7f37; --insbg:rgba(38,160,80,.15); --del:#b3261e; --delbg:rgba(200,60,60,.12);
  }
  @media (prefers-color-scheme: dark) {
    :root { --bg:#1c1c1e; --fg:#eaeaec; --muted:#9a9aa0; --line:#34343a;
            --card:#26262a; --accent:#e0a93b; --mark:#5a4a1e; --markborder:#8a6f2e; --edit:rgba(224,169,59,.10);
            --ins:#4ec06f; --insbg:rgba(78,192,111,.18); --del:#ff7b6e; --delbg:rgba(255,123,110,.16); }
  }
  * { box-sizing:border-box; }
  body { margin:0; font:15px/1.6 -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif; color:var(--fg); background:var(--bg); }
  header { position:sticky; top:0; z-index:5; display:flex; align-items:center; gap:14px; padding:10px 18px; background:var(--bg); border-bottom:1px solid var(--line); }
  header h1 { font-size:14px; font-weight:600; margin:0; flex:1; color:var(--muted); }
  button { font:inherit; font-size:13px; padding:6px 12px; border:1px solid var(--line); background:var(--card); color:var(--fg); border-radius:7px; cursor:pointer; }
  button:hover { border-color:var(--accent); }
  button.primary { background:var(--accent); color:#fff; border-color:var(--accent); }
  button.ok { color:var(--ins); } button.no { color:var(--del); }
  .wrap { display:grid; grid-template-columns: 1fr 340px; gap:0; align-items:start; }
  main { padding:30px 48px 140px; max-width:820px; margin:0 auto; }
  aside { position:sticky; top:53px; height:calc(100vh - 53px); overflow:auto; border-left:1px solid var(--line); padding:16px; background:var(--bg); }
  aside h2 { font-size:12px; text-transform:uppercase; letter-spacing:.05em; color:var(--muted); margin:4px 0 12px; }
  .doc h1 { font-size:25px; } .doc h2 { font-size:20px; margin-top:1.5em; } .doc h3 { font-size:16px; }
  .doc code { background:rgba(130,130,130,.14); padding:.1em .35em; border-radius:4px; font-size:.9em; }
  .doc pre { background:rgba(130,130,130,.12); padding:12px 14px; border-radius:8px; overflow:auto; } .doc pre code { background:none; padding:0; }
  .doc table { border-collapse:collapse; width:100%; font-size:13.5px; margin:1em 0; }
  .doc th,.doc td { border:1px solid var(--line); padding:6px 9px; text-align:left; vertical-align:top; }
  .doc blockquote { border-left:3px solid var(--accent); margin:1em 0; padding:.2em 1em; color:var(--muted); background:rgba(201,133,27,.06); }
  .block { border-radius:6px; padding:2px 6px; margin:0 -6px; transition:background .12s; }
  .block:hover { background:rgba(130,130,130,.05); }
  .block.editing { background:var(--edit); }
  .block > :first-child { margin-top:0; } .block > :last-child { margin-bottom:0; }
  textarea.rawedit { width:100%; font:inherit; line-height:1.6; border:none; outline:none; background:transparent; color:var(--fg); resize:none; padding:0; margin:0; overflow:hidden; display:block; }
  ins.sug { background:var(--insbg); color:var(--ins); text-decoration:none; border-radius:2px; padding:0 1px; cursor:pointer; }
  del.sug { background:var(--delbg); color:var(--del); text-decoration:line-through; border-radius:2px; padding:0 1px; cursor:pointer; }
  ins.sug.active, del.sug.active { box-shadow:0 0 0 2px currentColor; }
  mark.cm { background:var(--mark); border-bottom:2px solid var(--markborder); border-radius:2px; cursor:pointer; padding:0 1px; }
  mark.cm.active { box-shadow:0 0 0 3px var(--markborder); }
  .card { background:var(--card); border:1px solid var(--line); border-radius:9px; padding:11px 12px; margin-bottom:10px; box-shadow:var(--shadow); }
  .card.orphan { border-style:dashed; opacity:.85; } .card.resolved { opacity:.5; }
  .card .quote { font-size:12.5px; color:var(--muted); border-left:2px solid var(--markborder); padding-left:8px; margin-bottom:7px; white-space:pre-wrap; cursor:pointer; }
  .card .body { white-space:pre-wrap; }
  .card .meta { font-size:11px; color:var(--muted); margin-top:8px; display:flex; gap:10px; align-items:center; }
  .card .reply { margin-top:8px; padding-top:8px; border-top:1px dashed var(--line); font-size:13.5px; } .card .reply b { color:var(--accent); }
  .badge { font-size:10px; padding:1px 6px; border-radius:10px; background:rgba(201,133,27,.18); color:var(--accent); }
  .pop { position:absolute; z-index:20; display:none; background:var(--card); border:1px solid var(--line); border-radius:10px; box-shadow:0 6px 24px rgba(0,0,0,.18); padding:10px; }
  #popup { width:300px; } #popup textarea { width:100%; height:70px; resize:vertical; border:1px solid var(--line); border-radius:7px; padding:7px; font:inherit; background:var(--bg); color:var(--fg); }
  .pop .row { display:flex; justify-content:flex-end; gap:8px; margin-top:8px; }
  #sugpop .row { margin-top:0; gap:6px; }
  #popup .qt { font-size:12px; color:var(--muted); margin-bottom:7px; max-height:48px; overflow:auto; border-left:2px solid var(--markborder); padding-left:7px; }
  .empty { color:var(--muted); font-size:13px; }
  .hint { font-size:12px; color:var(--muted); margin:0 0 18px; } .hint b { color:var(--ins); } .hint s { color:var(--del); }
</style>
</head>
<body>
<header>
  <h1 id="docname">__TITLE__</h1>
  <span id="status" class="hint" style="margin:0"></span>
  <button id="dlBtn">Download .md</button>
  <button id="reloadBtn">Reload from file</button>
</header>
<div class="wrap">
  <main>
    <p class="hint">Click any text to edit it · select text to comment · <b>green = Claude added</b>, <s>struck = Claude removed</s> — click a suggestion to accept, reject, or comment</p>
    <div id="preview" class="doc"></div>
  </main>
  <aside><h2>Comments (<span id="ccount">0</span>)</h2><div id="comments"></div></aside>
</div>

<div id="popup" class="pop">
  <div class="qt" id="popupQuote"></div>
  <textarea id="popupText" placeholder="Write a comment…"></textarea>
  <div class="row"><button id="popupCancel">Cancel</button><button class="primary" id="popupSave">Comment</button></div>
</div>
<div id="sugpop" class="pop"><div class="row">
  <button class="ok" id="sugAccept">Accept</button><button class="no" id="sugReject">Reject</button><button id="sugComment">Comment</button>
</div></div>

<script>
let STATE={markdown:"",comments:[]};
let blocks=[]; let editingIndex=-1; let saveTimer=null; let SID=0;
let lastLoaded=""; let dirty=false; let curSug=-1;
const preview=document.getElementById('preview');
const popup=document.getElementById('popup'); const sugpop=document.getElementById('sugpop');
let pending=null;
const SUG_RE=/\{~~([\s\S]*?)~>([\s\S]*?)~~\}|\{\+\+([\s\S]*?)\+\+\}|\{--([\s\S]*?)--\}/g;

function setStatus(s){ const e=document.getElementById('status'); e.textContent=s; if(s){ clearTimeout(e._t); e._t=setTimeout(()=>e.textContent='',2000);} }
function esc(s){ return (s||'').replace(/[&<>]/g,m=>({'&':'&amp;','<':'&lt;','>':'&gt;'}[m])); }

async function load(){
  const r=await fetch('/api/state'); STATE=await r.json();
  lastLoaded=STATE.markdown; dirty=false;
  blocks=splitBlocks(STATE.markdown); editingIndex=-1;
  renderDoc(); renderComments();
}
async function refreshState(){ const r=await fetch('/api/state'); STATE=await r.json(); lastLoaded=STATE.markdown; renderDoc(); renderComments(); }

function splitBlocks(md){
  const lines=md.replace(/\r\n/g,'\n').split('\n'); const out=[]; let cur=[]; let fence=false;
  for(const ln of lines){ if(/^\s*```/.test(ln)) fence=!fence;
    if(ln.trim()==='' && !fence){ if(cur.length){ out.push(cur.join('\n')); cur=[]; } } else cur.push(ln); }
  if(cur.length) out.push(cur.join('\n')); return out.length?out:[''];
}
function joinBlocks(){ return blocks.join('\n\n')+'\n'; }

function mdToHtml(src){
  const withSug=src.replace(SUG_RE,(m,a,b,add,del)=>{
    const sid=SID++;
    if(a!==undefined) return '<del class="sug" data-sid="'+sid+'">'+esc(a)+'</del><ins class="sug" data-sid="'+sid+'">'+esc(b)+'</ins>';
    if(add!==undefined) return '<ins class="sug" data-sid="'+sid+'">'+esc(add)+'</ins>';
    if(del!==undefined) return '<del class="sug" data-sid="'+sid+'">'+esc(del)+'</del>';
    return m;
  });
  return window.marked?marked.parse(withSug):'<pre>'+esc(withSug)+'</pre>';
}
function renderDoc(){
  const y=window.scrollY; SID=0; preview.innerHTML='';
  blocks.forEach((b,i)=>{ const d=document.createElement('div'); d.className='block'; d.dataset.i=i; d.innerHTML=mdToHtml(b); preview.appendChild(d); });
  highlightAll(); window.scrollTo(0,y);
}

function previewText(){ return preview.textContent; }
function findOccurrence(h,n,occ){ let i=-1; for(let k=0;k<=occ;k++){ i=h.indexOf(n,i+1); if(i<0) return -1; } return i; }
function wrapRange(start,len,id){
  const w=document.createTreeWalker(preview,NodeFilter.SHOW_TEXT,null); let acc=0,sN=null,sO=0,eN=null,eO=0; const end=start+len; let n;
  while((n=w.nextNode())){ const L=n.nodeValue.length; if(!sN&&acc+L>start){sN=n;sO=start-acc;} if(sN&&acc+L>=end){eN=n;eO=end-acc;break;} acc+=L; }
  if(!sN||!eN) return false;
  try{ const r=document.createRange(); r.setStart(sN,sO); r.setEnd(eN,eO);
    const m=document.createElement('mark'); m.className='cm'; m.dataset.id=id;
    m.addEventListener('click',(e)=>{e.stopPropagation();focusComment(id);}); r.surroundContents(m); return true; }catch(e){ return false; }
}
function highlightAll(){ const t=previewText(); STATE.comments.forEach(c=>{ if(c.resolved) return; const off=findOccurrence(t,c.quote,c.occ||0); c._anchored=off>=0; if(off>=0) wrapRange(off,c.quote.length,c.id); }); }
function focusComment(id){
  document.querySelectorAll('mark.cm').forEach(m=>m.classList.toggle('active',m.dataset.id===id));
  const card=document.querySelector('.card[data-id="'+id+'"]');
  if(card){ card.scrollIntoView({behavior:'smooth',block:'center'}); card.style.outline='2px solid var(--accent)'; setTimeout(()=>card.style.outline='',1100); }
}

// inline editing
function autoGrow(ta){ ta.style.height='auto'; ta.style.height=ta.scrollHeight+'px'; }
function editBlock(i){
  if(editingIndex===i) return; commitEdit();
  const div=preview.querySelector('.block[data-i="'+i+'"]'); if(!div) return; editingIndex=i;
  const probe=div.querySelector('h1,h2,h3,h4,h5,p,li,td,th,blockquote')||div; const cs=getComputedStyle(probe);
  div.classList.add('editing');
  const ta=document.createElement('textarea'); ta.className='rawedit'; ta.value=blocks[i]; ta.style.fontSize=cs.fontSize; ta.style.fontWeight=cs.fontWeight;
  div.innerHTML=''; div.appendChild(ta); autoGrow(ta); ta.focus(); ta.setSelectionRange(ta.value.length,ta.value.length);
  ta.addEventListener('input',()=>{ blocks[i]=ta.value; autoGrow(ta); dirty=true; scheduleSave(); });
  ta.addEventListener('blur',commitEdit);
  ta.addEventListener('keydown',(e)=>{ if(e.key==='Escape'){ e.preventDefault(); ta.blur(); } });
}
function commitEdit(){
  if(editingIndex<0) return; const i=editingIndex; editingIndex=-1;
  const div=preview.querySelector('.block[data-i="'+i+'"]'); const ta=div&&div.querySelector('.rawedit');
  if(ta) blocks[i]=ta.value;
  blocks=splitBlocks(blocks.join('\n\n')); renderDoc(); scheduleSave(true);
}
function scheduleSave(now){
  clearTimeout(saveTimer);
  const go=async()=>{ const md=joinBlocks(); await fetch('/api/save',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({markdown:md})}); lastLoaded=md; dirty=false; setStatus('saved'); };
  if(now) go(); else saveTimer=setTimeout(go,700);
}

preview.addEventListener('click',(e)=>{ const a=e.target.closest('a'); if(a) e.preventDefault(); });
preview.addEventListener('mouseup',(e)=>{ setTimeout(()=>{
  if(e.target.classList&&e.target.classList.contains('rawedit')) return;
  const sel=window.getSelection(); const q=sel.toString().trim();
  if(q && preview.contains(sel.anchorNode)){ openComment(sel,e.pageX,e.pageY); return; }
  if(e.target.closest('mark.cm')) return;
  const sug=e.target.closest('.sug'); if(sug){ showSug(parseInt(sug.dataset.sid,10),e.pageX,e.pageY); return; }
  const blk=e.target.closest('.block'); if(blk) editBlock(parseInt(blk.dataset.i,10));
},1); });

// comment popup
function openComment(sel,x,y){
  const q=sel.toString().trim();
  const pre=document.createRange(); pre.selectNodeContents(preview);
  try{ pre.setEnd(sel.getRangeAt(0).startContainer, sel.getRangeAt(0).startOffset); }catch(_){ return; }
  const before=pre.toString(); let occ=0,j=-1; while((j=before.indexOf(q,j+1))>=0) occ++;
  pending={quote:q,occ:occ};
  document.getElementById('popupQuote').textContent='“'+q+'”'; document.getElementById('popupText').value='';
  popup.style.display='block'; popup.style.left=Math.min(x,window.innerWidth-330)+'px'; popup.style.top=(y+8)+'px';
  document.getElementById('popupText').focus();
}
function hidePopup(){ popup.style.display='none'; pending=null; }
document.getElementById('popupCancel').onclick=hidePopup;
document.getElementById('popupSave').onclick=async()=>{
  const comment=document.getElementById('popupText').value.trim(); if(!comment||!pending){ hidePopup(); return; }
  await fetch('/api/comment',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({quote:pending.quote,occ:pending.occ,comment})});
  hidePopup(); setStatus('comment saved'); refreshState();
};
document.getElementById('popupText').addEventListener('keydown',e=>{ if((e.metaKey||e.ctrlKey)&&e.key==='Enter') document.getElementById('popupSave').click(); if(e.key==='Escape') hidePopup(); });

// suggestion popover
function showSug(sid,x,y){
  curSug=sid; document.querySelectorAll('.sug.active').forEach(s=>s.classList.remove('active'));
  preview.querySelectorAll('.sug[data-sid="'+sid+'"]').forEach(s=>s.classList.add('active'));
  sugpop.style.display='block'; sugpop.style.left=Math.min(x,window.innerWidth-220)+'px'; sugpop.style.top=(y+8)+'px';
}
function hideSug(){ sugpop.style.display='none'; document.querySelectorAll('.sug.active').forEach(s=>s.classList.remove('active')); }
async function applySug(action){ if(curSug<0) return; const s=curSug; hideSug();
  await fetch('/api/suggestion',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({sid:s,action})});
  setStatus(action+'ed suggestion'); load();
}
document.getElementById('sugAccept').onclick=()=>applySug('accept');
document.getElementById('sugReject').onclick=()=>applySug('reject');
document.getElementById('sugComment').onclick=()=>{
  const el=preview.querySelector('ins.sug[data-sid="'+curSug+'"]')||preview.querySelector('del.sug[data-sid="'+curSug+'"]'); if(!el){ hideSug(); return; }
  const r=document.createRange(); r.selectNodeContents(el); const sel=window.getSelection(); sel.removeAllRanges(); sel.addRange(r);
  const rect=el.getBoundingClientRect(); hideSug(); openComment(sel, rect.left+window.scrollX, rect.bottom+window.scrollY);
};

document.addEventListener('mousedown',e=>{
  if(popup.style.display==='block' && !popup.contains(e.target)) hidePopup();
  if(sugpop.style.display==='block' && !sugpop.contains(e.target) && !e.target.closest('.sug')) hideSug();
});

// sidebar
function renderComments(){
  const box=document.getElementById('comments'); box.innerHTML='';
  const open=STATE.comments.filter(c=>!c.resolved); document.getElementById('ccount').textContent=open.length;
  if(!STATE.comments.length){ box.innerHTML='<p class="empty">No comments yet. Select text to add one, or click a suggestion → Comment.</p>'; return; }
  STATE.comments.forEach(c=>{
    const div=document.createElement('div');
    div.className='card'+(c.resolved?' resolved':'')+(c._anchored===false&&!c.resolved?' orphan':''); div.dataset.id=c.id;
    const reply=c.reply?'<div class="reply"><b>Claude:</b> '+esc(c.reply)+'</div>':'';
    const orphan=(c._anchored===false&&!c.resolved)?' <span class="badge">text changed</span>':'';
    div.innerHTML='<div class="quote">'+esc(c.quote)+'</div><div class="body">'+esc(c.comment)+'</div>'+reply+
      '<div class="meta">'+esc(c.created||'')+orphan+'<span style="flex:1"></span>'+
      (c.resolved?'<button data-act="reopen">Reopen</button>':'<button data-act="resolve">Resolve</button>')+'</div>';
    div.querySelector('.quote').addEventListener('click',()=>focusComment(c.id));
    div.querySelector('[data-act]').addEventListener('click',async(e)=>{
      await fetch('/api/resolve',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({id:c.id,resolved:e.target.dataset.act==='resolve'})}); refreshState();
    });
    box.appendChild(div);
  });
}

// pick up Claude's edits to the file without a manual reload
setInterval(async()=>{
  if(editingIndex>=0 || dirty || popup.style.display==='block') return;
  try{ const r=await fetch('/api/state'); const s=await r.json();
    if(s.markdown!==lastLoaded){ STATE=s; lastLoaded=s.markdown; blocks=splitBlocks(s.markdown); renderDoc(); renderComments(); setStatus('updated'); }
  }catch(_){}
},2500);

document.getElementById('dlBtn').onclick=()=>{
  if(editingIndex>=0) commitEdit();
  const md=blocks.length?joinBlocks():STATE.markdown;
  const blob=new Blob([md],{type:'text/markdown;charset=utf-8'});
  const a=document.createElement('a');
  a.href=URL.createObjectURL(blob);
  a.download=document.getElementById('docname').textContent||'document.md';
  document.body.appendChild(a); a.click(); a.remove();
  setTimeout(()=>URL.revokeObjectURL(a.href),1000);
  setStatus('downloaded');
};

document.getElementById('reloadBtn').onclick=load;
load();
</script>
</body>
</html>
"""


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, body, ctype="application/json"):
        if isinstance(body, (dict, list)):
            body = json.dumps(body)
        data = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype + "; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _read(self):
        n = int(self.headers.get("Content-Length", 0))
        return json.loads(self.rfile.read(n) or b"{}")

    def do_GET(self):
        if self.path == "/" or self.path.startswith("/index"):
            self._send(200, PAGE.replace("__TITLE__", os.path.basename(DOC)), "text/html")
        elif self.path == "/api/state":
            self._send(200, {"markdown": read_doc(), "comments": load_comments()})
        else:
            self._send(404, {"error": "not found"})

    def do_POST(self):
        try:
            b = self._read()
        except Exception as e:
            return self._send(400, {"error": str(e)})

        if self.path == "/api/comment":
            comments = load_comments()
            nid = "c" + str(max([int(c["id"][1:]) for c in comments] + [0]) + 1)
            comments.append({"id": nid, "quote": b.get("quote", ""), "occ": b.get("occ", 0),
                             "comment": b.get("comment", ""), "created": now_iso(), "resolved": False, "reply": ""})
            save_comments(comments)
            self._send(200, {"ok": True, "id": nid})
        elif self.path == "/api/resolve":
            comments = load_comments()
            for c in comments:
                if c["id"] == b.get("id"):
                    c["resolved"] = bool(b.get("resolved", True))
            save_comments(comments)
            self._send(200, {"ok": True})
        elif self.path == "/api/suggestion":
            text = resolve_suggestion(read_doc(), int(b.get("sid", -1)), b.get("action", "accept"))
            with open(DOC, "w", encoding="utf-8") as f:
                f.write(text)
            self._send(200, {"ok": True})
        elif self.path == "/api/save":
            with open(DOC, "w", encoding="utf-8") as f:
                f.write(b.get("markdown", ""))
            self._send(200, {"ok": True})
        else:
            self._send(404, {"error": "not found"})


def main():
    global DOC
    ap = argparse.ArgumentParser()
    ap.add_argument("--file", default=DEFAULT_DOC)
    ap.add_argument("--port", type=int, default=8042)
    args = ap.parse_args()
    DOC = os.path.abspath(args.file)
    if not os.path.exists(DOC):
        raise SystemExit("Doc not found: " + DOC)
    os.makedirs(review_dir(), exist_ok=True)
    srv = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    print("Review GUI for: " + os.path.basename(DOC))
    print("Open  http://localhost:%d   (Ctrl-C to stop)" % args.port)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped.")


if __name__ == "__main__":
    main()
