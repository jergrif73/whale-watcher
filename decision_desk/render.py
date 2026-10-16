"""Static HTML for the Pages site: docs/today.html and docs/weekly.html.
Rendered by the Python runs, no client-side data fetching except the
decision-journal form, which commits through the same GitHub token the
main dashboard already stores in localStorage (ww_token / ww_repo)."""

import html

from decision_desk.common import DOCS_DIR, FOOTER_TEXT, MTD_CAP_USD, month_to_date_spend, now_utc

REPO_URL = "https://github.com/jergrif73/whale-watcher"

CSS = """
:root{--bg:#0d1117;--bg2:#161b22;--bg3:#21262d;--fg:#e6edf3;--fg2:#8b949e;--line:#30363d;
--green:#3fb950;--amber:#d29922;--red:#f85149;--blue:#58a6ff}
*{box-sizing:border-box;margin:0;padding:0}
body{background:var(--bg);color:var(--fg);font:15px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif}
.wrap{max-width:900px;margin:0 auto;padding:16px}
header{display:flex;flex-wrap:wrap;gap:12px;align-items:center;justify-content:space-between;border-bottom:1px solid var(--line);padding-bottom:12px;margin-bottom:16px}
h1{font-size:20px} h2{font-size:16px;margin:24px 0 10px} h3{font-size:15px}
nav a{color:var(--fg2);text-decoration:none;margin-left:14px;font-size:14px} nav a.on{color:var(--fg);font-weight:600}
.muted{color:var(--fg2);font-size:13px}
.card{background:var(--bg2);border:1px solid var(--line);border-radius:8px;padding:14px;margin-bottom:12px}
.row{display:flex;flex-wrap:wrap;gap:8px 18px;align-items:baseline}
.pill{display:inline-block;padding:1px 9px;border-radius:999px;font-size:12px;font-weight:600;text-transform:uppercase;letter-spacing:.03em}
.intact,.ok,.on_pace,.diversified,.low{background:rgba(63,185,80,.15);color:var(--green)}
.watch,.elevated,.partly_overlapping,.ahead,.behind,.medium,.approaching,.unclear{background:rgba(210,153,34,.15);color:var(--amber)}
.broken,.high,.effectively_one_bet,.met,.no_plan{background:rgba(248,81,73,.15);color:var(--red)}
.not_met{background:var(--bg3);color:var(--fg2)}
ul{padding-left:20px} li{margin:3px 0}
table{width:100%;border-collapse:collapse;font-size:13px} th,td{text-align:left;padding:6px 8px;border-bottom:1px solid var(--line)} th{color:var(--fg2);font-weight:500}
.scroll{overflow-x:auto}
.spend{display:flex;flex-wrap:wrap;align-items:center;gap:6px 10px;font-size:13px;color:var(--fg2);margin-bottom:12px}
.bar{width:120px;height:6px;background:var(--bg3);border-radius:3px;overflow:hidden}.bar i{display:block;height:100%;background:var(--blue)}
.warn{border-color:var(--amber)} .err{border-color:var(--red)}
label{display:block;font-size:13px;color:var(--fg2);margin:8px 0 3px}
input,select,textarea{width:100%;background:var(--bg);color:var(--fg);border:1px solid var(--line);border-radius:6px;padding:8px;font:inherit}
textarea{min-height:90px}
button{background:#238636;color:#fff;border:0;border-radius:6px;padding:9px 16px;font:inherit;font-weight:600;margin-top:10px;cursor:pointer}
.grid2{display:grid;grid-template-columns:1fr 1fr;gap:0 12px}
@media(max-width:560px){.grid2{grid-template-columns:1fr} nav a{margin:0 12px 0 0}}
footer{margin:32px 0 12px;padding-top:12px;border-top:1px solid var(--line);color:var(--fg2);font-size:12px}
"""

e = html.escape


def _pill(v):
    v = str(v)
    return f'<span class="pill {e(v)}">{e(v.replace("_", " "))}</span>'


def _money(v):
    return "n/a" if v is None else f"${v:,.2f}"


def _pct(v):
    return "n/a" if v is None else f"{v:+.2f}%"


def _list(items):
    items = [i for i in items if i]
    if not items:
        return '<p class="muted">None.</p>'
    return "<ul>" + "".join(f"<li>{e(str(i))}</li>" for i in items) + "</ul>"


def spend_widget():
    mtd = month_to_date_spend()
    pct = min(100, mtd / MTD_CAP_USD * 100) if MTD_CAP_USD else 0
    return (f'<div class="spend"><span>API spend this month <b style="color:var(--fg)">${mtd:,.2f}</b>'
            f' of ${MTD_CAP_USD:,.0f} cap</span><span class="bar"><i style="width:{pct:.1f}%"></i></span></div>')


def page(title, active, body):
    nav = "".join(
        f'<a href="{href}" class="{"on" if key == active else ""}">{label}</a>'
        for key, href, label in [("dash", "index.html", "Dashboard"), ("today", "today.html", "Today"),
                                 ("weekly", "weekly.html", "Weekly")])
    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{e(title)}</title><style>{CSS}</style></head>
<body><div class="wrap">
<header><div><h1>{e(title)}</h1><div class="muted">Rendered {now_utc().strftime('%Y-%m-%d %H:%M')} UTC</div></div>
<nav>{nav}</nav></header>
{spend_widget()}
{body}
<footer>{e(FOOTER_TEXT)}</footer>
</div></body></html>
"""


def write_page(name, html_text):
    DOCS_DIR.mkdir(parents=True, exist_ok=True)
    (DOCS_DIR / name).write_text(html_text, encoding="utf-8")
    print(f"   wrote docs/{name}")


# ----------------------------------------------------------------- today

DECISION_FORM = """
<h2>Log a decision</h2>
<div class="card">
<p class="muted">Anything you do, or decide not to do, with your reasoning written before you act. Saved to data/decisions.json in the repo with the GitHub token from the dashboard settings. The next run fills in the price at decision.</p>
<form id="dform">
<div class="grid2">
<div><label>Ticker</label><input id="d-ticker" list="d-tickers" required>
<datalist id="d-tickers">__TICKERS__</datalist></div>
<div><label>Action</label><select id="d-action">
<option value="hold">hold (decided not to act)</option><option value="skip_dca">skip a DCA buy</option>
<option value="buy">buy</option><option value="add">add</option><option value="trim">trim</option>
<option value="sell">sell</option><option value="other">other</option></select></div>
<div><label>Amount USD (optional)</label><input id="d-amount" type="number" step="0.01" min="0"></div>
<div><label>Thesis status as you see it</label><select id="d-status">
<option>intact</option><option>watch</option><option>broken</option><option>unknown</option></select></div>
</div>
<label>Reasoning (what you are doing, why, and what would prove you wrong)</label>
<textarea id="d-reason" required></textarea>
<button type="submit">Save to journal</button> <span id="d-msg" class="muted"></span>
</form></div>
<script>
(function(){
const f=document.getElementById('dform'),msg=document.getElementById('d-msg');
const b64e=s=>btoa(String.fromCharCode(...new TextEncoder().encode(s)));
const b64d=s=>new TextDecoder().decode(Uint8Array.from(atob(s.replace(/\\n/g,'')),c=>c.charCodeAt(0)));
f.addEventListener('submit',async ev=>{
 ev.preventDefault();
 const token=localStorage.getItem('ww_token'),repo=localStorage.getItem('ww_repo')||'jergrif73/whale-watcher';
 if(!token){msg.textContent='No GitHub token saved. Add it under Settings on the Dashboard page.';return;}
 msg.textContent='Saving...';
 const url=`https://api.github.com/repos/${repo}/contents/data/decisions.json`;
 const h={'Authorization':`token ${token}`,'Accept':'application/vnd.github.v3+json'};
 try{
  const r=await fetch(url,{headers:h});let data={version:1,decisions:[]},sha=null;
  if(r.ok){const j=await r.json();sha=j.sha;data=JSON.parse(b64d(j.content));}
  else if(r.status!==404){throw new Error('GitHub API '+r.status);}
  const now=new Date(),amt=document.getElementById('d-amount').value;
  const entry={id:now.toISOString().slice(0,10)+'-'+Math.random().toString(36).slice(2,6),
   date:now.toLocaleDateString('en-CA',{timeZone:'America/New_York'}),
   ticker:document.getElementById('d-ticker').value.trim().toUpperCase(),
   action:document.getElementById('d-action').value,amount_usd:amt?Number(amt):null,
   price_at_decision:null,thesis_status_at_time:document.getElementById('d-status').value,
   reasoning:document.getElementById('d-reason').value.trim(),related_brief:'__BRIEF__'||null,
   logged_at:now.toISOString()};
  data.decisions.push(entry);
  const body={message:`decision: ${entry.action} ${entry.ticker}`,content:b64e(JSON.stringify(data,null,2)+'\\n'),branch:'main'};
  if(sha)body.sha=sha;
  const p=await fetch(url,{method:'PUT',headers:{...h,'Content-Type':'application/json'},body:JSON.stringify(body)});
  if(!p.ok){const er=await p.json();throw new Error(er.message||p.status);}
  msg.textContent='Saved. It will show here after the next run.';f.reset();
 }catch(err){msg.textContent='Failed: '+err.message;}
});})();
</script>
"""


def render_today(brief: dict, decisions: list):
    if not brief:
        body = '<div class="card">No brief yet. The first one runs on the next weekday after market close, or from Actions, Decision Desk Daily, Run workflow.</div>'
        write_page("today.html", page("Decision Desk: Today", "today", body))
        return
    snap = {h["ticker"]: h for h in brief["snapshot"]["holdings"]}
    out = brief.get("output") or {}
    parts = [f'<p class="muted">Brief for {e(brief["date"])} (New York), model {e(brief.get("model", ""))}. '
             f'Archive: <a style="color:var(--blue)" href="{REPO_URL}/tree/main/briefs">briefs/</a></p>']
    if brief.get("error"):
        parts.append(f'<div class="card err"><b>Run problem:</b> {e(brief["error"])}</div>')
    s = brief["snapshot"]
    parts.append('<div class="card"><div class="row">'
                 f'<span>Holdings value <b>{_money(s["total_value_usd"])}</b></span>'
                 f'<span>Cost basis <b>{_money(s["total_cost_basis_usd"])}</b></span>'
                 f'<span>Planned capital <b>{_money(s.get("planned_capital_usd"))}</b></span>'
                 f'<span>Cash <b>{_money(s.get("cash_usd"))}</b></span></div>'
                 + (f'<p style="margin-top:8px">{e(out.get("portfolio_note", ""))}</p>' if out else "")
                 + (f'<p class="muted" style="margin-top:6px">Journal: {e(out.get("journal_nudge", ""))}</p>' if out else "")
                 + '</div>')
    for h in out.get("holdings", []):
        sh = snap.get(h["ticker"], {})
        a = h.get("allocation_drift", {})
        trig = h.get("rule_triggers", [])
        parts.append(
            f'<div class="card {"err" if h["thesis_status"] == "broken" else "warn" if h["thesis_status"] == "watch" else ""}">'
            f'<div class="row"><h3>{e(h["ticker"])}</h3>{_pill(h["thesis_status"])}'
            f'<span class="muted">{_money(sh.get("price"))} | day {_pct(sh.get("day_change_pct"))} | week {_pct(sh.get("week_change_pct"))}'
            f' | P/L {_pct(sh.get("unrealized_pl_pct"))} on {_money(sh.get("cost_basis_usd"))}</span></div>'
            f'<p style="margin-top:8px">{e(h["what_changed"])}</p>'
            f'<p class="muted" style="margin-top:8px">Allocation {a.get("current_pct")}% vs target {a.get("target_pct")}%'
            f' (drift {a.get("drift_pts")} pts). {e(a.get("comment", ""))}</p>'
            f'<h3 style="margin-top:10px;font-size:13px">Rule triggers</h3>'
            + _list([f'{t["rule"]}: {t["detail"]}' for t in trig])
            + '<h3 style="margin-top:10px;font-size:13px">Questions before acting</h3>'
            + _list(h.get("questions_before_acting", []))
            + '</div>')
    tickers = "".join(f'<option value="{e(t)}">' for t in snap)
    form = DECISION_FORM.replace("__TICKERS__", tickers).replace("__BRIEF__", e(brief["date"]))
    parts.append(form)
    parts.append(_decisions_table(decisions[-15:]))
    write_page("today.html", page("Decision Desk: Today", "today", "\n".join(parts)))


def _decisions_table(decisions):
    if not decisions:
        return '<h2>Recent decisions</h2><p class="muted">Journal is empty.</p>'
    rows = "".join(
        f'<tr><td>{e(d.get("date", ""))}</td><td>{e(d.get("ticker", ""))}</td><td>{e(d.get("action", ""))}</td>'
        f'<td>{_money(d.get("amount_usd"))}</td><td>{e(str(d.get("price_at_decision") or ""))}</td>'
        f'<td>{e(d.get("reasoning", ""))}</td></tr>' for d in reversed(decisions))
    return ('<h2>Recent decisions</h2><div class="scroll"><table><tr><th>Date</th><th>Ticker</th><th>Action</th>'
            f'<th>Amount</th><th>Price</th><th>Reasoning</th></tr>{rows}</table></div>')


# ---------------------------------------------------------------- weekly

def render_weekly(review: dict):
    if not review:
        body = '<div class="card">No weekly review yet. It runs Sunday, or from Actions, Decision Desk Weekly, Run workflow.</div>'
        write_page("weekly.html", page("Decision Desk: Weekly", "weekly", body))
        return
    parts = [f'<p class="muted">Week {e(review["week"])}, model {e(review.get("model", ""))}, batch {e(review.get("batch_id", ""))}. '
             f'Archive: <a style="color:var(--blue)" href="{REPO_URL}/tree/main/reviews">reviews/</a></p>']
    if review.get("errors"):
        parts.append('<div class="card err"><b>Run problems:</b>' + _list(review["errors"]) + '</div>')
    p = review.get("portfolio")
    if p:
        c, k, d = p["concentration"], p["correlation"], p["dca_pacing"]
        parts.append(
            '<h2>Portfolio</h2><div class="card">'
            f'<p><b>Concentration</b> {_pill(c["assessment"])} top weight {c["top_weight_pct"]}%. {e(c["comment"])}</p>'
            f'<p style="margin-top:8px"><b>Correlation</b> {_pill(k["assessment"])} {e(k["notes"])}</p>'
            f'<p style="margin-top:8px"><b>DCA pacing</b> {_pill(d["assessment"])} {e(d["notes"])}</p></div>')
        viol = p.get("rule_violations", [])
        parts.append('<h2>Rule violations</h2><div class="card">' + (
            "".join(f'<p style="margin:4px 0">{_pill(v["severity"])} <b>{e(v["rule"])}</b>: {e(v["detail"])}</p>' for v in viol)
            if viol else '<p class="muted">None found.</p>') + '</div>')
        jr = p["decision_journal_review"]
        parts.append('<h2>Decision journal scorecard</h2><div class="card">'
                     f'<p>{e(jr["summary"])}</p>' + _scores(jr.get("decision_scores", []), review) + '</div>')
        parts.append('<h2>Top questions for next week</h2><div class="card">' + _list(p.get("top_questions", [])) + '</div>')
    for h in review.get("holdings", []):
        parts.append(
            f'<h2>{e(h["ticker"])}</h2><div class="card"><div class="row">{_pill(h["thesis_status"])}</div>'
            f'<p style="margin-top:8px">{e(h["week_summary"])}</p>'
            f'<p style="margin-top:8px"><b>Stress test.</b> {e(h["thesis_stress_test"])}</p>'
            '<h3 style="margin-top:10px;font-size:13px">Sell criteria</h3>'
            + "".join(f'<p style="margin:4px 0">{_pill(s["status"])} {e(s["criterion"])}<br><span class="muted">{e(s["evidence"])}</span></p>'
                      for s in h.get("sell_criteria_check", []))
            + f'<p style="margin-top:8px"><b>DCA.</b> {e(h["dca_assessment"])}</p>'
            + '<h3 style="margin-top:10px;font-size:13px">Questions</h3>' + _list(h.get("questions_for_jeremiah", []))
            + '</div>')
    write_page("weekly.html", page("Decision Desk: Weekly", "weekly", "\n".join(parts)))


def _scores(scores, review):
    if not scores:
        return '<p class="muted">No decisions logged yet, so nothing to score.</p>'
    outcomes = {o["id"]: o for o in review.get("decision_outcomes", [])}
    rows = ""
    for s in scores:
        o = outcomes.get(s["decision_id"], {})
        rows += (f'<tr><td>{e(o.get("date", ""))}</td><td>{e(o.get("ticker", ""))} {e(o.get("action", ""))}</td>'
                 f'<td>{s["process_score"]}/5</td><td>{_pill(s["outcome_so_far"])}</td>'
                 f'<td>{_pct(o.get("price_change_since_pct"))}</td><td>{e(s["lesson"])}</td></tr>')
    return ('<div class="scroll"><table><tr><th>Date</th><th>Decision</th><th>Process</th><th>Outcome</th>'
            f'<th>Price since</th><th>Lesson</th></tr>{rows}</table></div>')
