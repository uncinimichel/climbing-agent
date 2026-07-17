"""Topo Studio demo v2 — the unified flow: place a belay, write the pitch,
right on the photo; one save; the card and page preview carry the same rows."""
from pathlib import Path

from playwright.sync_api import sync_playwright

BASE = "http://localhost:8890"
HERE = Path(__file__).parent
PHOTO = HERE / "user-photo.jpg"

INTRO = ("A wandering line up the North Tor's cleanest granite — delicate slab into a "
         "soaring corner crack, topping out above the Silent Valley.")
APPROACH = ("Carrick Little car park, Annalong track 40 min, then open hillside to the tor.")
PITCHES = [
    ("4a", "30", "Pad up the slab on positive edges, trending left to the ledge below the corner."),
    ("4c", "35", "The corner crack — bridge and jam past the bulge (crux), stance out on the arete."),
    ("4b", "25", "Step right onto the exposed nose; juggy granite to the summit blocks."),
]

# the overlay speaks the Studio's own design language: paper, olive, serif + mono
OVERLAY_JS = """
() => {
  if (document.getElementById('demoLayer')) return;
  const st = document.createElement('style');
  st.textContent = `
    #demoCap{position:fixed;left:50%;transform:translateX(-50%);z-index:9999;pointer-events:none;
      background:rgba(243,244,240,.97);border:1px solid #C3C8BE;border-left:4px solid #5E6B14;
      border-radius:10px;padding:9px 16px 10px;max-width:72%;
      box-shadow:0 2px 6px rgba(35,42,39,.10),0 10px 28px rgba(35,42,39,.14);
      opacity:0;transition:opacity .3s}
    #demoCap .eb{font:700 9.5px ui-monospace,Menlo,monospace;letter-spacing:.14em;color:#5E6B14;
      text-transform:uppercase;display:flex;align-items:center;gap:7px;margin-bottom:2px}
    #demoCap .dots{display:inline-flex;gap:3px}
    #demoCap .dots i{width:5px;height:5px;border-radius:99px;background:#C3C8BE}
    #demoCap .dots i.on{background:#5E6B14}
    #demoCap .tx{font:500 16.5px/1.4 ui-serif,'Iowan Old Style',Georgia,serif;color:#232A27}
    #demoCard{position:fixed;inset:0;z-index:10000;background:#EAECE7;display:flex;flex-direction:column;
      align-items:center;justify-content:center;gap:12px;opacity:0;transition:opacity .45s;pointer-events:none}
    #demoCard .eb{font:700 11px ui-monospace,Menlo,monospace;letter-spacing:.22em;color:#5E6B14;text-transform:uppercase}
    #demoCard h1{font:600 38px/1.15 ui-serif,'Iowan Old Style',Georgia,serif;color:#232A27;margin:0;text-align:center;max-width:70%}
    #demoCard .sub{font:400 14.5px system-ui,sans-serif;color:#616B64}
    #demoCard .rule{width:64px;height:2px;background:#5E6B14;border-radius:2px}
    #demoCur{position:fixed;z-index:10001;width:16px;height:16px;margin:-8px 0 0 -8px;border-radius:50%;
      background:rgba(255,255,255,.95);border:3px solid #5E6B14;box-shadow:0 1px 4px rgba(35,42,39,.35);
      pointer-events:none;transition:transform .08s;left:-40px}
    .demoRip{position:fixed;z-index:10000;width:14px;height:14px;margin:-7px 0 0 -7px;border-radius:50%;
      border:2.5px solid #5E6B14;pointer-events:none;animation:demorip .5s ease-out forwards}
    @keyframes demorip{from{transform:scale(.6);opacity:.85}to{transform:scale(3.2);opacity:0}}`;
  document.head.appendChild(st);
  const cur = document.createElement('div'); cur.id = 'demoCur'; document.body.appendChild(cur);
  document.addEventListener('pointermove', e => { cur.style.left = e.clientX + 'px'; cur.style.top = e.clientY + 'px'; }, true);
  document.addEventListener('pointerdown', e => {
    cur.style.transform = 'scale(.8)';
    const r = document.createElement('div'); r.className = 'demoRip';
    r.style.left = e.clientX + 'px'; r.style.top = e.clientY + 'px';
    document.body.appendChild(r); setTimeout(() => r.remove(), 550);
  }, true);
  document.addEventListener('pointerup', () => { cur.style.transform = ''; }, true);
}
"""


def run():
    with sync_playwright() as pw:
        b = pw.chromium.launch()
        ctx = b.new_context(viewport={"width": 1280, "height": 800},
                            record_video_dir=str(HERE / "video"),
                            record_video_size={"width": 1280, "height": 800})
        page = ctx.new_page()

        def pause(ms):
            page.wait_for_timeout(ms)

        TOTAL = 7
        def overlay():
            page.evaluate(OVERLAY_JS)

        def narrate(step, text, pos="bottom", hold=2300):
            page.evaluate("""([step, total, t, pos]) => {
                let e = document.getElementById('demoCap');
                if (!e) { e = document.createElement('div'); e.id = 'demoCap'; document.body.appendChild(e); }
                if (pos === 'modal') { e.style.top = '112px'; e.style.bottom = 'auto'; }
                else { e.style.bottom = '20px'; e.style.top = 'auto'; }
                if (!t) { e.style.opacity = 0; return; }
                const dots = Array.from({length: total}, (_, i) =>
                  `<i class="${i < step ? 'on' : ''}"></i>`).join('');
                e.innerHTML = `<div class="eb"><span>step ${step} of ${total}</span><span class="dots">${dots}</span></div>
                               <div class="tx"></div>`;
                e.querySelector('.tx').textContent = t;
                e.style.opacity = 1;
            }""", [step, TOTAL, text, pos])
            if text:
                pause(hold)

        def card(title, sub, hold=2400):
            page.evaluate("""([title, sub]) => {
                let c = document.getElementById('demoCard');
                if (!c) { c = document.createElement('div'); c.id = 'demoCard'; document.body.appendChild(c); }
                c.innerHTML = `<div class="eb">multi-pitch — curation studio</div>
                  <h1></h1><div class="rule"></div><div class="sub"></div>`;
                c.querySelector('h1').textContent = title;
                c.querySelector('.sub').textContent = sub;
                requestAnimationFrame(() => c.style.opacity = 1);
            }""", [title, sub])
            pause(hold)
            page.evaluate("document.getElementById('demoCard').style.opacity = 0")
            pause(500)

        # ── 1 · straight in: find the climb ──
        page.goto(BASE)
        page.wait_for_selector(".qrow", timeout=10000)
        overlay()
        card("A climb, start to finish.", "photo → page in under two minutes")
        narrate(1, "Find the route — same queue, same filters", hold=1800)
        page.click("#q")
        page.keyboard.type("granite", delay=50)
        pause(500)
        page.locator(".qrow", has_text="Granite Whisper").first.click()
        page.wait_for_selector(".rt-head h2", timeout=8000)
        pause(500)

        # ── 2 · the words + the facts ──
        narrate(2, "The words first — the prose is the product", hold=1800)
        page.locator("#ta-intro").click()
        page.keyboard.type(INTRO, delay=7)
        pause(250)
        narrate(2, "Grade, tags, quality, season — a few clicks", hold=1600)
        gsel = page.locator(".fact", has_text="grade system").locator("select")
        labels = gsel.locator("option").all_text_contents()
        uk = next((l for l in labels if "British" in l), next((l for l in labels if "UK" in l), None))
        if uk:
            gsel.select_option(label=uk)
            pause(300)
        gi = page.locator("#gradeInput")
        gi.click()
        gi.fill("")
        page.keyboard.type("VS 4c", delay=40)
        page.keyboard.press("Tab")
        pause(250)
        for fam, vals in [("features", ["crack", "corner", "arête"]),
                          ("character", ["delicate", "exposed"])]:
            row = page.locator(".chips", has_text=fam).first
            for v in vals:
                row.locator("select").select_option(v)
                pause(200)
        page.locator("#starsRow span").nth(1).click()
        pause(200)
        for m in [5, 6, 7, 8, 9]:
            page.locator("#seasonRow i").nth(m - 1).click()
            pause(80)
        page.locator("#ta-appr").scroll_into_view_if_needed()
        page.locator("#ta-appr").click()
        page.keyboard.type(APPROACH, delay=5)
        pause(300)

        # ── 3 · the crag photo ──
        page.locator("#topoSec").scroll_into_view_if_needed()
        narrate(3, "Add the crag photo — credit and license are the gate", hold=2200)
        page.set_input_files("#tpFile", str(PHOTO))
        page.fill("#tpCredit", "Dan Knight / multi-pitch.com")
        pause(250)
        page.locator("button", has_text="add crag photo").click()
        page.wait_for_selector("#topoModal.on", timeout=12000)
        pause(1100)

        # ── 4 · the line ──
        narrate(4, "Draw the line, bottom to top — it renders smoothed, like a guidebook", pos="modal", hold=2400)
        cv = page.locator("#tpCanvas")
        box = cv.bounding_box()
        X, Y, w, h = box["x"], box["y"], box["width"], box["height"]

        def glide_click(fx, fy, ms=140):
            page.mouse.move(X + fx * w, Y + fy * h, steps=10)
            page.mouse.down()
            page.mouse.up()
            pause(ms)

        for fx, fy in [(0.55, 0.93), (0.52, 0.84), (0.50, 0.76), (0.55, 0.66), (0.54, 0.57),
                       (0.50, 0.48), (0.47, 0.40), (0.50, 0.30), (0.46, 0.20), (0.44, 0.11)]:
            glide_click(fx, fy)
        pause(400)

        # ── 5 · pitches, one by one, ON the photo ──
        narrate(5, "The pitches: place the belay, write the pitch, right there", pos="modal", hold=2600)
        page.locator("#topoModal button[data-m=belay]").click()
        pause(300)
        stances = [(0.50, 0.76), (0.54, 0.57), (0.50, 0.30)]
        for i, ((bx, by), (gr, ln, desc)) in enumerate(zip(stances, PITCHES)):
            glide_click(bx, by, ms=450)          # ring lands, rail focuses this pitch
            chip = page.locator(f'.tppitch[data-i="{i}"]')
            chip.locator("input").nth(0).click()
            page.keyboard.type(gr, delay=45)
            chip.locator("input").nth(1).click()
            page.keyboard.type(ln, delay=45)
            chip.locator("textarea").click()
            page.keyboard.type(desc, delay=5)
            pause(350)
        # the zoom money-shot: read P2's label up close
        page.mouse.move(X + 0.56 * w, Y + 0.55 * h)
        narrate(5, "Each label carries its pitch — grade and length from the text", pos="modal", hold=1200)
        for _ in range(5):
            page.mouse.wheel(0, -240)
            pause(160)
        pause(1500)
        page.locator("#topoModal button", has_text="fit").click()
        pause(600)

        # ── 6 · descent, same surface ──
        narrate(6, "The descent: draw it in blue, note it in the same breath", pos="modal", hold=2200)
        page.locator("#topoModal button[data-m=descent]").click()
        pause(300)
        for fx, fy in [(0.32, 0.12), (0.27, 0.45), (0.24, 0.86)]:
            glide_click(fx, fy, ms=250)
        page.fill("#tpSegLabel", "abseil 45m")
        page.locator("#tpSegLabel").press("Tab")
        try:
            page.locator("#tpDescMethod").select_option("abseil")
        except Exception:
            pass
        page.fill("#tpDescAbs", "2")
        page.locator("#tpDescAbs").press("Tab")
        pause(600)

        # ── 7 · one save ──
        narrate(7, "One save — the drawing and the pitch text land together", pos="modal", hold=2000)
        page.locator("#tpSaveBtn").click()
        pause(900)
        page.locator("#tpStatusBtn").click()
        pause(800)
        page.locator("#topoModal button", has_text="close").click()
        pause(500)

        # ── 8 · proof: the card already has the rows ──
        page.locator(".pitchhead").scroll_into_view_if_needed()
        narrate(7, "The card's pitch-by-pitch? Already there — same rows, two views", hold=2600)
        pause(500)

        # ── 9 · the payoff: the page preview ──
        page.locator("button", has_text="page preview").click()
        page.wait_for_selector("#pv", timeout=6000)
        pause(400)
        narrate(7, "And this is the climb page it becomes — prose, rings, pitch by pitch", hold=2800)
        page.evaluate("document.querySelector('#pv .pv').scrollBy({top: 500, behavior: 'smooth'})")
        pause(1600)
        page.evaluate("document.querySelector('#pv .pv').scrollBy({top: 500, behavior: 'smooth'})")
        pause(1600)
        narrate(0, "")
        card("Draw it once — it's data everywhere.", "the line, the belays, the pitches: one record, every view", hold=2800)
        pause(400)
        ctx.close()
        b.close()
        vids = sorted((HERE / "video").glob("*.webm"), key=lambda p: p.stat().st_mtime)
        print("video:", vids[-1] if vids else "MISSING")


run()
