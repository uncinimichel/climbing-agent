"""E2E: drive the Curation Studio like a user — new climb, pitches, photo, topo."""
import json
import sys
import time
import urllib.request
from pathlib import Path

from playwright.sync_api import sync_playwright

BASE = "http://localhost:8890"
RID = 1051
HERE = Path(__file__).parent
PHOTO = HERE / "user-photo.jpg"
LOG = {"console": [], "pageerrors": [], "reqfail": [], "findings": []}


def note(f):
    LOG["findings"].append(f)
    print("FINDING:", f)


def ok(m):
    print("ok:", m)


def shot(page, name):
    page.screenshot(path=str(HERE / f"{name}.png"))


def clear_toast(page):
    page.evaluate("const t=document.getElementById('toast');t.textContent='';t.style.opacity=0")


def wait_toast(page, want=None, timeout=5000):
    """Deterministic: caller must clear_toast() before the action."""
    try:
        page.wait_for_function(
            "() => {const t=document.getElementById('toast');return t.style.opacity==1 && t.textContent}",
            timeout=timeout)
        t = page.locator("#toast").text_content() or ""
        if want and want not in t:
            note(f"expected toast containing '{want}', got '{t}'")
        return t
    except Exception:
        if want:
            note(f"no toast appeared (expected '{want}')")
        return ""


def api_json(path):
    with urllib.request.urlopen(BASE + path) as r:
        return json.load(r)


def run():
    with sync_playwright() as pw:
        b = pw.chromium.launch()
        ctx = b.new_context(viewport={"width": 1440, "height": 950})
        page = ctx.new_page()
        page.on("console", lambda m: LOG["console"].append(f"{m.type}: {m.text}")
                if m.type in ("error", "warning") else None)
        page.on("pageerror", lambda e: LOG["pageerrors"].append(str(e)))
        page.on("requestfailed", lambda r: LOG["reqfail"].append(f"{r.method} {r.url} {r.failure}"))
        page.on("dialog", lambda d: d.accept())

        # ── 1 · open the new climb's card ──
        page.goto(f"{BASE}/#r={RID}")
        page.wait_for_selector(".rt-head h2", timeout=8000)
        assert "Granite Whisper" in (page.locator(".rt-head h2").text_content() or "")
        ok("card opened for the new climb")
        shot(page, "01-card")

        # ── 2 · edit a fact like a user (length) ──
        clear_toast(page)
        page.locator(".fact", has_text="length m").locator("input").fill("95")
        page.locator(".fact", has_text="length m").locator("input").press("Tab")
        wait_toast(page, "saved")
        ok("fact edit saved")

        # ── 2b · regression (review P0-1): ⌘⏎ while typing must NOT publish ──
        page.locator("#ta-intro").click()
        page.keyboard.type("typing a sentence")
        page.keyboard.press("Meta+Enter")
        page.wait_for_timeout(600)
        chip = page.locator("#statusChip").text_content() or ""
        if "published" in chip:
            note("cmd+Enter inside a textarea still publishes (P0-1 regression)")
        else:
            ok("cmd+Enter guarded while typing")
        page.keyboard.press("Escape")

        # ── 3 · (re)write the 3 pitches like a user ──
        for i, (ln, gr, desc) in enumerate([("30", "4b", "Easy slab to a big ledge."),
                                            ("35", "4c", "The crux corner crack."),
                                            ("25", "4a", "Romp to the top.")]):
            if page.locator(".pitchrow").count() <= i:
                page.locator("button", has_text="+ pitch").first.click()
            row = page.locator(".pitchrow").nth(i)
            row.locator("input").nth(1).fill(ln)
            row.locator("input").nth(2).fill(gr)
            row.locator("textarea").fill(desc)
        # regression (review P0-2): clicking a star must not wipe the unsaved rows
        page.locator("#starsRow span").nth(1).click()
        page.wait_for_timeout(400)
        v = page.locator(".pitchrow").nth(0).locator("textarea").input_value()
        if "Easy slab" not in v:
            note("star click still wipes unsaved pitch rows (P0-2 regression)")
        else:
            ok("star click keeps unsaved pitch rows")
        btn = page.locator("#savePitchesBtn").text_content() or ""
        if "●" not in btn:
            note("no unsaved-changes pill on save pitches button")
        else:
            ok("dirty pill shows on unsaved pitches")
        clear_toast(page)
        page.locator("#savePitchesBtn").click()
        wait_toast(page, "pitches saved")
        ok("3 pitches saved")
        shot(page, "02-pitches")

        # ── 4 · topo section starts empty for a fresh crag ──
        page.locator("#topoSec").scroll_into_view_if_needed()
        page.wait_for_timeout(400)
        sec = page.locator("#topoSec").text_content() or ""
        if "no crag photos" not in sec:
            note(f"expected empty-topo message, got: {sec[:80]}")
        shot(page, "03-topo-empty")

        # ── 5 · rights gate: upload without credit blocked client-side ──
        page.set_input_files("#tpFile", str(PHOTO))
        clear_toast(page)
        page.locator("button", has_text="add crag photo").click()
        t = wait_toast(page)
        if "credit" not in t:
            note(f"no-credit upload not blocked (toast '{t}')")
        else:
            ok("blocked: no credit")

        # ── 6 · rights gate: permission without note must be refused (server 400) ──
        page.fill("#tpCredit", "E2E Tester")
        page.select_option("#tpLic", "permission")
        clear_toast(page)
        page.locator("button", has_text="add crag photo").click()
        t = wait_toast(page)
        if "permission" not in t:
            note(f"permission-without-note not refused (toast '{t}')")
        else:
            ok("blocked: permission w/o note")

        # ── 7 · proper upload — editor should auto-open ──
        page.select_option("#tpLic", "owned")
        clear_toast(page)
        page.locator("button", has_text="add crag photo").click()
        try:
            page.wait_for_selector("#topoModal.on", timeout=10000)
            ok("photo uploaded, editor auto-opened")
        except Exception:
            note("editor did not auto-open after upload")
        page.wait_for_timeout(900)
        shot(page, "04-editor-open")

        # ── 8 · draw the line ──
        cv = page.locator("#tpCanvas")
        box = cv.bounding_box()
        w, h = box["width"], box["height"]
        pts = [(0.52, 0.92), (0.50, 0.80), (0.55, 0.68), (0.52, 0.55),
               (0.47, 0.44), (0.50, 0.33), (0.46, 0.22), (0.44, 0.12)]
        for fx, fy in pts:
            cv.click(position={"x": fx * w, "y": fy * h})
        assert page.evaluate("TPline.length") == 8
        ok("8-point line drawn")
        page.locator("#topoModal button", has_text="undo").first.click()
        assert page.evaluate("TPline.length") == 7
        cv.click(position={"x": pts[-1][0] * w, "y": pts[-1][1] * h})
        ok("undo + redraw works")

        # ── 9 · belays with prefill from the pitches saved MOMENTS ago (bug fix check) ──
        page.locator("#topoModal button[data-m=belay]").click()
        for fx, fy in [(0.50, 0.80), (0.52, 0.55), (0.50, 0.33)]:
            cv.click(position={"x": fx * w, "y": fy * h})
            page.wait_for_timeout(150)
        pre = page.evaluate("TPitems.map(p=>p.grade+'|'+(p.length_m??''))")
        if pre != ["4b|30", "4c|35", "4a|25"]:
            note(f"unified pitch rail prefill wrong: {pre}")
        else:
            ok(f"pitch rail bound to the route's pitch rows: {pre}")
        # the unified flow: belay click focused P3's description — type right there
        page.locator(".tppitch").nth(2).locator("textarea").fill("Rewritten from the topo editor itself.")
        page.locator(".tppitch").nth(1).locator("input").first.fill("5a")
        page.locator(".tppitch").nth(1).locator("input").first.press("Tab")
        page.locator(".tppitch").nth(0).locator("button", has_text="label").click()
        cv.click(position={"x": 0.62 * w, "y": 0.78 * h})
        ok("pitch text + grade edited beside the photo, label placed")
        shot(page, "05-belays")

        # ── 10 · descent path ──
        page.locator("#topoModal button[data-m=descent]").click()
        for fx, fy in [(0.30, 0.15), (0.25, 0.45), (0.22, 0.85)]:
            cv.click(position={"x": fx * w, "y": fy * h})
        shot(page, "06-full-topo")

        # ── 11 · save, close, thumbnail state ──
        clear_toast(page)
        page.locator("#tpSaveBtn").click()
        wait_toast(page, "saved")
        rows = api_json(f"/api/route/{RID}")["pitch_rows"]
        if rows[2]["description"] != "Rewritten from the topo editor itself." or rows[1]["original_grade"] != "5a":
            note(f"unified save did not write pitch rows: {rows[1:]}")
        else:
            ok("one save wrote topo line AND pitch rows (single source of truth)")
        page.locator("#topoModal button", has_text="close").click()
        page.wait_for_timeout(700)
        page.locator("#topoSec").scroll_into_view_if_needed()
        thumb = page.locator(".topothumb").first.text_content() or ""
        if "this route drawn" not in thumb:
            note(f"thumbnail lacks drawn state after save: '{thumb}'")
        else:
            ok("thumbnail shows ✓ this route drawn")
        shot(page, "07-thumb-after-save")

        # ── 12 · reopen: persistence ──
        page.locator(".topothumb").first.click()
        page.wait_for_selector("#topoModal.on", timeout=6000)
        page.wait_for_timeout(800)
        state = page.evaluate("[TPline.length, TPitems.length, (TPdesc[0]?.path||[]).length, TPitems[1].grade, TPitems[2].description.slice(0,9)]")
        if state != [8, 3, 3, "5a", "Rewritten"]:
            note(f"persistence mismatch on reopen: {state}")
        else:
            ok("full persistence on reopen (incl. descriptions)")
        shot(page, "08-reopen")

        # ── 13 · publish toggle, then delete the line ──
        clear_toast(page)
        page.locator("#tpStatusBtn").click()
        wait_toast(page, "publish")
        clear_toast(page)
        page.locator("#topoModal button", has_text="✕ line").click()
        wait_toast(page, "removed")
        assert page.evaluate("TPline.length") == 0
        tid = api_json(f"/api/route/{RID}/topoinfo")["topos"][0]["id"]
        if api_json(f"/api/topo/{tid}")["lines"]:
            note("line still in DB after delete")
        else:
            ok("line deleted server-side")
        page.locator("#topoModal button", has_text="close").click()
        page.wait_for_timeout(600)
        if "this route drawn" in (page.locator(".topothumb").first.text_content() or ""):
            note("thumbnail still says drawn after deletion")
        else:
            ok("thumbnail reflects deleted line")

        # ── 14 · dark mode ──
        page.emulate_media(color_scheme="dark")
        page.goto(f"{BASE}/#r={RID}&topo={tid}")
        page.reload()
        page.wait_for_selector("#topoModal.on", timeout=8000)
        page.wait_for_timeout(900)
        shot(page, "09-dark-modal")
        ok("dark mode modal rendered")

        # ── 15 · smoke the other views ──
        page.keyboard.press("Escape")
        for label in ["map", "grid", "taxonomy"]:
            btns = page.locator(".views button", has_text=label)
            if btns.count():
                btns.first.click()
                page.wait_for_timeout(700)
        shot(page, "10-other-views")
        ok("other views clicked")
        b.close()


try:
    run()
finally:
    print("\n=== console errors ==="); print("\n".join(LOG["console"][:20]) or "(none)")
    print("=== page errors ==="); print("\n".join(LOG["pageerrors"][:10]) or "(none)")
    print("=== failed requests ==="); print("\n".join(LOG["reqfail"][:10]) or "(none)")
    print("=== findings ==="); print("\n".join(LOG["findings"]) or "(none)")
    (HERE / "e2e-log.json").write_text(json.dumps(LOG, indent=1))
