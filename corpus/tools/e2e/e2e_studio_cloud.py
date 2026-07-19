"""Full end-to-end walk-through of the DEPLOYED browser Studio, recorded to
video: sign in with Cognito, hand-enter a climb, curate it (prose, grade,
tags), upload a crag photo (the cloud presigned browser→S3 path), draw its
topo, then delete the climb again — leaving the corpus exactly as it started.

Run:  STUDIO_PW=... agent/.venv/bin/python corpus/tools/e2e/e2e_studio_cloud.py
The overlay speaks the Studio's own language: paper, olive, serif + mono.
"""
import os
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

BASE = os.environ.get("STUDIO_URL", "https://driuinui6do86.cloudfront.net")
EMAIL = os.environ.get("STUDIO_EMAIL", "uncini.michel@gmail.com")
PW = os.environ["STUDIO_PW"]
HERE = Path(__file__).parent
PHOTO = HERE / "user-photo.jpg"
OUT = HERE / "cloud-video"

NAME = "Test Arete (E2E)"
INTRO = ("A clean test line up the seaward arete — delicate padding into a "
         "positive crack, drawn here only to prove the full flow end to end.")

OVERLAY_JS = r"""
() => {
  if (document.getElementById('demoCur')) return;
  const st = document.createElement('style');
  st.textContent = `
    #demoCap{position:fixed;left:50%;transform:translateX(-50%);z-index:99999;pointer-events:none;
      background:rgba(243,244,240,.97);border:1px solid #C3C8BE;border-left:4px solid #5E6B14;
      border-radius:10px;padding:9px 16px 10px;max-width:74%;
      box-shadow:0 2px 6px rgba(35,42,39,.10),0 10px 28px rgba(35,42,39,.14);
      opacity:0;transition:opacity .3s}
    #demoCap .eb{font:700 9.5px ui-monospace,Menlo,monospace;letter-spacing:.14em;color:#5E6B14;
      text-transform:uppercase;display:flex;align-items:center;gap:7px;margin-bottom:2px}
    #demoCap .dots{display:inline-flex;gap:3px}
    #demoCap .dots i{width:5px;height:5px;border-radius:99px;background:#C3C8BE}
    #demoCap .dots i.on{background:#5E6B14}
    #demoCap .tx{font:500 16.5px/1.4 ui-serif,'Iowan Old Style',Georgia,serif;color:#232A27}
    #demoCard{position:fixed;inset:0;z-index:100000;background:#EAECE7;display:flex;flex-direction:column;
      align-items:center;justify-content:center;gap:12px;opacity:0;transition:opacity .45s;pointer-events:none}
    #demoCard .eb{font:700 11px ui-monospace,Menlo,monospace;letter-spacing:.22em;color:#5E6B14;text-transform:uppercase}
    #demoCard h1{font:600 38px/1.15 ui-serif,'Iowan Old Style',Georgia,serif;color:#232A27;margin:0;text-align:center;max-width:70%}
    #demoCard .sub{font:400 14.5px system-ui,sans-serif;color:#616B64}
    #demoCard .rule{width:64px;height:2px;background:#5E6B14;border-radius:2px}
    #demoCur{position:fixed;z-index:100001;width:16px;height:16px;margin:-8px 0 0 -8px;border-radius:50%;
      background:rgba(255,255,255,.95);border:3px solid #5E6B14;box-shadow:0 1px 4px rgba(35,42,39,.35);
      pointer-events:none;transition:transform .08s;left:-40px}
    .demoRip{position:fixed;z-index:100000;width:14px;height:14px;margin:-7px 0 0 -7px;border-radius:50%;
      border:2.5px solid #5E6B14;pointer-events:none;animation:demorip .5s ease-out forwards}
    @keyframes demorip{from{transform:scale(.6);opacity:.85}to{transform:scale(3.2);opacity:0}}`;
  document.head.appendChild(st);
  const cur = document.createElement('div'); cur.id = 'demoCur'; document.body.appendChild(cur);
  document.addEventListener('pointermove', e => { cur.style.left = e.clientX+'px'; cur.style.top = e.clientY+'px'; }, true);
  document.addEventListener('pointerdown', e => {
    cur.style.transform='scale(.8)';
    const r=document.createElement('div'); r.className='demoRip';
    r.style.left=e.clientX+'px'; r.style.top=e.clientY+'px';
    document.body.appendChild(r); setTimeout(()=>r.remove(),550);
  }, true);
  document.addEventListener('pointerup', ()=>{ cur.style.transform=''; }, true);
}
"""

TOTAL = 6


def run():
    with sync_playwright() as pw:
        b = pw.chromium.launch()
        ctx = b.new_context(viewport={"width": 1280, "height": 800},
                            record_video_dir=str(OUT),
                            record_video_size={"width": 1280, "height": 800})
        page = ctx.new_page()
        fails = []
        page.on("pageerror", lambda e: fails.append(f"JS: {e}"))

        def pause(ms): page.wait_for_timeout(ms)

        def overlay(): page.evaluate(OVERLAY_JS)

        def narrate(step, text, pos="bottom", hold=2300):
            page.evaluate("""([step,total,t,pos])=>{
                let e=document.getElementById('demoCap');
                if(!e){e=document.createElement('div');e.id='demoCap';document.body.appendChild(e);}
                if(pos==='modal'){e.style.top='108px';e.style.bottom='auto';}else{e.style.bottom='20px';e.style.top='auto';}
                if(!t){e.style.opacity=0;return;}
                const dots=Array.from({length:total},(_,i)=>`<i class="${i<step?'on':''}"></i>`).join('');
                e.innerHTML=`<div class="eb"><span>step ${step} of ${total}</span><span class="dots">${dots}</span></div><div class="tx"></div>`;
                e.querySelector('.tx').textContent=t; e.style.opacity=1;
            }""", [step, TOTAL, text, pos])
            if text: pause(hold)

        def card(title, sub, hold=2400):
            page.evaluate("""([title,sub])=>{
                let c=document.getElementById('demoCard');
                if(!c){c=document.createElement('div');c.id='demoCard';document.body.appendChild(c);}
                c.innerHTML=`<div class="eb">multi-pitch — curation studio</div><h1></h1><div class="rule"></div><div class="sub"></div>`;
                c.querySelector('h1').textContent=title; c.querySelector('.sub').textContent=sub;
                requestAnimationFrame(()=>c.style.opacity=1);
            }""", [title, sub])
            pause(hold)
            page.evaluate("document.getElementById('demoCard').style.opacity=0")
            pause(500)

        # ── 0 · sign in (the cloud gate) ──
        page.goto(BASE, wait_until="networkidle")
        page.wait_for_selector("#loginOvl", timeout=15000)
        overlay()
        card("The Studio, in the cloud.", "sign in → curate → clean up")
        narrate(1, "Curators only — sign in with Cognito", hold=1500)
        page.fill("#lgEmail", EMAIL)
        page.fill("#lgPass", PW)
        page.click("#loginForm button[type=submit]")
        page.wait_for_selector("#loginOvl", state="hidden", timeout=20000)
        page.wait_for_selector(".qrow", timeout=20000)
        overlay()
        pause(600)

        # ── 2 · hand-enter a new climb ──
        narrate(2, "Add a climb by hand — not everything comes from the crawl", hold=2200)
        page.click("button:has-text('climb')")
        page.wait_for_selector("#ncName", timeout=8000)
        pause(400)
        page.fill("#ncName", NAME)
        # pick a real crag from the breadcrumb list (exact-label match, as the form requires)
        label = page.evaluate("""() => {
          const a=document.getElementById('newOvl')._areas;
          // a real crag/sector (deepest breadcrumb), not a bare region
          const c=a.filter(x=>/Fair Head/i.test(x.label)).sort((p,q)=>q.label.split('›').length-p.label.split('›').length);
          return (c[0]||a.find(x=>x.kind==='sector')||a[0]).label;
        }""")
        page.fill("#ncArea", label)
        pause(500)
        page.click("#newForm button[type=submit]")
        # wait for the NEW card specifically — a card is already open from page load
        page.wait_for_function("n => document.querySelector('.rt-head h2')?.textContent.includes(n)",
                               arg=NAME, timeout=12000)
        pause(600)

        # ── 3 · curate: prose, grade, tags ──
        narrate(3, "Curate it — the prose first, the product is the page", hold=2000)
        page.locator("#ta-intro").click()
        page.keyboard.type(INTRO, delay=6)
        pause(300)
        narrate(3, "Grade on its scale, then the tags — features, character, hazards", hold=2000)
        gsel = page.locator(".fact", has_text="grade system").locator("select")
        labels = gsel.locator("option").all_text_contents()
        uk = next((l for l in labels if "British" in l or "UK" in l), None)
        if uk:
            gsel.select_option(label=uk)
            pause(300)
        gi = page.locator("#gradeInput")
        gi.click(); gi.fill("")
        page.keyboard.type("HS 4b", delay=45)
        page.keyboard.press("Tab")
        pause(300)
        for fam, vals in [("features", ["crack", "arête"]),
                          ("character", ["delicate", "exposed"]),
                          ("hazards", ["loose"])]:
            for v in vals:
                page.locator(f"#chips-{fam} select").select_option(v)
                pause(350)
        page.locator("#starsRow span").nth(1).click()
        pause(200)
        for m in (5, 6, 7, 8, 9):
            page.locator("#seasonRow i").nth(m - 1).click()
            pause(70)
        pause(500)

        # ── 4 · upload the crag photo (cloud: browser → S3 presigned PUT) ──
        page.locator("#topoSec").scroll_into_view_if_needed()
        narrate(4, "Add the crag photo — it uploads straight to storage, credit is the gate", hold=2400)
        page.set_input_files("#tpFile", str(PHOTO))
        page.fill("#tpCredit", "Dan Knight / multi-pitch.com")
        pause(300)
        page.click("button:has-text('add crag photo')")
        page.wait_for_selector("#topoModal.on", timeout=20000)
        assert "topoModal" in page.evaluate("document.querySelector('#topoModal.on')?.id || ''"), "topo editor never opened"
        pause(1000)

        # ── 5 · draw the line, save ──
        narrate(5, "Draw the line bottom to top — it renders smoothed, like a guidebook", pos="modal", hold=2400)
        cv = page.locator("#tpCanvas"); box = cv.bounding_box()
        X, Y, w, h = box["x"], box["y"], box["width"], box["height"]
        for fx, fy in [(0.55, 0.93), (0.52, 0.82), (0.50, 0.70), (0.53, 0.58),
                       (0.49, 0.46), (0.47, 0.33), (0.50, 0.22), (0.46, 0.11)]:
            page.mouse.move(X + fx * w, Y + fy * h, steps=8)
            page.mouse.down(); page.mouse.up()
            pause(150)
        pause(500)
        narrate(5, "One save — the drawing lands on the record", pos="modal", hold=1600)
        page.click("#tpSaveBtn")
        pause(1200)

        # ── 6 · tidy up: remove the topo photo, then the climb — leave nothing ──
        page.on("dialog", lambda d: d.accept())
        narrate(6, "Tidy up — delete the topo photo (and its stored files)", pos="modal", hold=2000)
        page.click("#topoModal button:has-text('photo')")   # 🗑 photo — deletes the topo + S3 media
        page.wait_for_selector("#topoModal.on", state="hidden", timeout=10000)
        pause(700)
        narrate(6, "…then the climb itself — the corpus ends as it started", hold=2000)
        page.click("button:has-text('Delete')")
        pause(1500)
        assert NAME not in page.inner_text("body"), "climb still present after delete"
        narrate(6, "Gone — record file, topo and media removed, local and S3", hold=1800)
        card("End to end. ✓", "sign-in · create · curate · photo · topo · delete")

        narrate(0, "")
        pause(500)
        ctx.close()
        b.close()
        vid = next(OUT.glob("*.webm"), None)
        if fails:
            print("PAGE ERRORS:", *fails, sep="\n  ")
        print(f"video: {vid}")
        return not fails


if __name__ == "__main__":
    OUT.mkdir(exist_ok=True)
    sys.exit(0 if run() else 1)
