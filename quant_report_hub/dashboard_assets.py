"""Offline styles and interactions embedded in the generated dashboard."""

CSS = """
:root{color-scheme:light;--ink:#16302f;--muted:#647370;--line:#dce4df;--paper:#f4f6f2;--accent:#146859}
*{box-sizing:border-box}body{margin:0;background:var(--paper);color:var(--ink);font:15px/1.65 system-ui,-apple-system,'Microsoft YaHei',sans-serif}
a{color:var(--accent);text-underline-offset:4px}button,input,select{font:inherit}button,summary,a,input,select{outline-offset:4px}
[hidden]{display:none!important}.shell{max-width:1440px;margin:auto;padding:0 40px 70px}
header{display:flex;align-items:center;justify-content:space-between;border-bottom:1px solid var(--line);padding:22px 0;gap:24px}
.brand{font-size:17px;font-weight:750;letter-spacing:-.3px}.brand b{background:var(--accent);color:white;padding:5px 9px;margin-right:10px;border-radius:7px}
nav{display:flex;gap:25px}nav a{text-decoration:none;font-size:14px}.eyebrow{color:var(--accent);letter-spacing:2px;font:700 11px/1.6 system-ui;margin:0 0 12px}
.hero{display:flex;justify-content:space-between;align-items:end;gap:28px;padding:44px 0 28px}h1{font-size:36px;letter-spacing:-1px;line-height:1.3;margin:0 0 12px}h2{font-size:23px;margin:0}h3{font-size:18px;margin:0 0 12px}h4{font-size:14px;margin:22px 0 8px}
p{margin:8px 0}.muted,small{color:var(--muted)}.meta{font-size:12px;overflow-wrap:anywhere}.hero .meta{text-align:right;min-width:230px}.intro{max-width:670px;color:var(--muted)}
.stats{display:grid;grid-template-columns:repeat(4,1fr);gap:16px;margin-bottom:28px}.stat{padding:20px 22px;border:1px solid var(--line);background:#fff;border-radius:12px}.stat strong{display:block;font-size:28px;line-height:1.4;font-weight:650}.stat span{font-size:12px;color:var(--muted)}
.toolbar{display:flex;align-items:center;gap:12px;flex-wrap:wrap;padding:16px 0;border-top:1px solid var(--line);border-bottom:1px solid var(--line);margin-bottom:32px}.toolbar label{display:flex;align-items:center;gap:8px;font-size:13px}.toolbar input,.toolbar select{border:1px solid #cdd8d2;background:#fff;border-radius:7px;padding:8px 10px;color:var(--ink)}.toolbar input{width:260px}.toolbar small{margin-left:auto}
.section-head{display:flex;align-items:center;justify-content:space-between;gap:15px;margin:32px 0 16px}.section-head p{font-size:13px;color:var(--muted)}.card{background:#fff;border:1px solid var(--line);border-radius:14px;padding:26px;margin:16px 0;box-shadow:0 3px 15px #173b2e04}
.card-head{display:flex;align-items:flex-start;justify-content:space-between;gap:16px}.run-id{font:12px/1.7 ui-monospace,monospace;color:var(--muted);overflow-wrap:anywhere}.badge{display:inline-block;border-radius:5px;padding:4px 9px;font-size:12px;font-weight:650;background:#e8eeea;white-space:nowrap}.paper_ready{background:#e2f1e8;color:#19573d}.blocked,.invalid{background:#fbe9e5;color:#9a402f}.observe,.expired{background:#faf0d7;color:#826126}
.notice{padding:13px 16px;border-left:3px solid #adbcaf;background:#f2f5f1;border-radius:0 7px 7px 0;font-size:13px;margin:16px 0;overflow-wrap:anywhere}.notice.warning{background:#fff6e4;border-color:#c79536}.notice.error{background:#fff0ec;border-color:#c3674f}.metrics{display:grid;grid-template-columns:repeat(4,1fr);gap:18px;padding:20px 0;border-bottom:1px solid var(--line)}.metrics b{display:block;font-size:22px;font-weight:650}.metrics span{font-size:12px;color:var(--muted)}
.columns{display:grid;grid-template-columns:1fr 1fr;gap:28px}.scroll{overflow-x:auto}table{border-collapse:collapse;width:100%;font-size:13px}th,td{text-align:left;padding:11px 12px;border-bottom:1px solid #e8ede8;vertical-align:top;overflow-wrap:anywhere}th{font-weight:600;color:var(--muted);background:#f8faf7;white-space:nowrap}.facts th{width:40%;white-space:normal}.facts td{word-break:break-word}.empty{padding:22px;border:1px dashed #cbd6ce;border-radius:8px;color:var(--muted);font-size:13px}
.evidence{display:flex;gap:9px;flex-wrap:wrap;margin:15px 0}.evidence a{font-size:12px;text-decoration:none;border:1px solid var(--line);border-radius:6px;padding:5px 10px}.evidence a:hover{background:#eef5ee}.details{margin-top:18px}summary{cursor:pointer;color:var(--accent);font-size:13px;padding:9px 0}pre{background:#f5f7f3;border-radius:7px;padding:15px;white-space:pre-wrap;overflow-wrap:anywhere;font:12px/1.7 ui-monospace,monospace;max-height:340px;overflow:auto}.history{margin-top:20px}.history .card{box-shadow:none;border-radius:8px}.check{accent-color:var(--accent);width:17px;height:17px}.compare-button{background:var(--accent);color:#fff;border:0;border-radius:7px;padding:9px 14px;cursor:pointer}.compare-button:disabled{opacity:.45;cursor:default}footer{margin-top:40px;padding-top:20px;border-top:1px solid var(--line);color:var(--muted);font-size:12px}
@media(max-width:850px){.shell{padding:0 20px 40px}.hero{align-items:start;flex-direction:column;padding-top:30px}.hero .meta{text-align:left}.stats,.metrics{grid-template-columns:repeat(2,1fr)}.columns{grid-template-columns:1fr}.toolbar small{margin-left:0}.card{padding:18px}h1{font-size:29px}.card-head{flex-wrap:wrap}nav{gap:12px;font-size:12px}}
@media(max-width:480px){header{align-items:start;flex-direction:column;gap:14px}.toolbar input{width:190px}.section-head{align-items:start;flex-direction:column}.stats{gap:9px}.stat{padding:14px}.shell{padding:0 14px 30px}}
"""

SCRIPT = """
(() => {
  const q = (s) => document.querySelector(s);
  const all = (s) => Array.from(document.querySelectorAll(s));
  const search = q('#search'), status = q('#status-filter');
  function filter() {
    const text = search.value.toLocaleLowerCase();
    all('[data-search]').forEach(el => {
      el.hidden = !el.dataset.search.toLocaleLowerCase().includes(text) ||
        (status.value !== 'all' && el.dataset.status !== status.value);
    });
  }
  function freshness() {
    all('[data-valid-until]').forEach(el => {
      const deadline = Date.parse(el.dataset.validUntil);
      const fresh = Number.isFinite(deadline) && Date.now() < deadline;
      el.querySelectorAll('[data-paper-actions]').forEach(block => {
        block.hidden = !(fresh && el.dataset.eligible === 'true');
      });
      if (!fresh && el.dataset.expirable === 'true') {
        el.dataset.status = 'expired';
        const badge = el.querySelector('[data-status-badge]');
        badge.textContent = (el.dataset.latest === 'true' ? '' : '历史状态：') + '已过期 · 仅供复盘'; badge.className = 'badge expired';
        el.querySelectorAll('[data-expiry-notice]').forEach(block => block.hidden = false);
      }
    });
    q('#ready-count').textContent = all('[data-latest="true"][data-status="paper_ready"]').length;
    filter();
  }
  search.addEventListener('input', filter);
  status.addEventListener('change', filter);
  const button = q('#compare-button');
  function selection() {
    const count = all('.experiment-check:checked').length;
    button.disabled = count < 2;
    button.textContent = `对比所选实验（${count}）`;
  }
  all('.experiment-check').forEach(el => el.addEventListener('change', selection));
  button.addEventListener('click', () => {
    const selected = new Set(all('.experiment-check:checked').map(el => el.value));
    all('[data-comparison]').forEach(el => el.hidden = !selected.has(el.dataset.comparison));
    q('#comparison').hidden = false;
    q('#comparison').scrollIntoView({behavior:'smooth', block:'start'});
  });
  freshness(); selection(); setInterval(freshness, 15000);
})();
"""
