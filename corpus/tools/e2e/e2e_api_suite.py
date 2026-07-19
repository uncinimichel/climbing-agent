"""End-to-end suite against the DEPLOYED Studio API (Cognito + HTTP API +
Lambda over S3). Exercises the flows the browser drives, at the API layer so
it's fast and deterministic — every scenario is self-cleaning and asserts the
corpus returns to its starting route count.

Run:  STUDIO_PW=... [DAN_PW=...] agent/.venv/bin/python corpus/tools/e2e/e2e_api_suite.py
"""
import json
import os
import sys
import time
import urllib.error
import urllib.request

REGION = "eu-west-2"
CLIENT = "2h89p8mhb0qbv6s2dfndnnehtc"
API = "https://1lm4oxrzc2.execute-api.eu-west-2.amazonaws.com"
BUCKET = "climbing-agent-db-backups-166832185275"
PHOTO = os.path.join(os.path.dirname(__file__), "user-photo.jpg")

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"  {'✓' if cond else '✗ FAIL'}  {name}{'' if cond else '  — '+detail}")
    return cond


def cognito_token(email, pw):
    body = json.dumps({"AuthFlow": "USER_PASSWORD_AUTH", "ClientId": CLIENT,
                       "AuthParameters": {"USERNAME": email, "PASSWORD": pw}}).encode()
    req = urllib.request.Request(f"https://cognito-idp.{REGION}.amazonaws.com/", data=body,
        headers={"Content-Type": "application/x-amz-json-1.1",
                 "X-Amz-Target": "AWSCognitoIdentityProviderService.InitiateAuth"})
    return json.load(urllib.request.urlopen(req))["AuthenticationResult"]["IdToken"]


def api(tok, path, method="GET", body=None, expect=200, raw=False):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(API + path, data=data, method=method,
        headers={"Authorization": "Bearer " + tok,
                 **({"Content-Type": "application/json"} if data else {})})
    try:
        r = urllib.request.urlopen(req, timeout=30)
        code, payload = r.status, r.read()
    except urllib.error.HTTPError as e:
        code, payload = e.code, e.read()
    if raw:
        return code, payload
    assert code == expect, f"{method} {path} -> {code} (wanted {expect}): {payload[:160]}"
    return json.loads(payload) if payload else {}


def total_routes(tok):
    d = api(tok, "/api/queue?status=all")
    return sum(d["counts"].get(k, 0) for k in ("draft", "publish", "quarantined"))


def main():
    email = os.environ.get("STUDIO_EMAIL", "uncini.michel@gmail.com")
    tok = cognito_token(email, os.environ["STUDIO_PW"])
    start = total_routes(tok)
    print(f"\nbaseline: {start} routes\n")

    # ── S1 · auth gate ──────────────────────────────────────────────
    print("S1 · auth gate")
    code, _ = api("bogus.token.here", "/api/queue", expect=None, raw=True)
    check("no/invalid token is rejected (401)", code == 401, f"got {code}")
    check("valid token reads the queue", isinstance(api(tok, "/api/queue").get("rows"), list))

    # ── S2 · create → edit tags → persistence → delete ──────────────
    print("S2 · create, tag, persist, delete")
    rid = api(tok, "/api/route", "POST", {"name": "Suite Tag Test (E2E)", "area_id": 20})["id"]
    api(tok, f"/api/route/{rid}", "PATCH",
        {"tags": {"features": ["crack", "arête"], "character": ["exposed"], "hazards": ["loose"]}})
    r = api(tok, f"/api/route/{rid}")             # re-read: did tags persist through the store?
    tg = r.get("tags", {})
    check("features persisted", set(tg.get("features", [])) == {"crack", "arête"}, str(tg.get("features")))
    check("character persisted", tg.get("character") == ["exposed"], str(tg.get("character")))
    check("hazard recorded (surfaced as tags.hazards for the UI)",
          tg.get("hazards") == ["loose"], str(tg.get("hazards")))
    check("off-vocabulary tag is rejected (schema gate)",
          api(tok, f"/api/route/{rid}", "PATCH", {"tags": {"features": ["not-a-real-feature"]}},
              expect=None, raw=True)[0] in (400, 422))
    api(tok, f"/api/route/{rid}", "DELETE")
    check("delete removed the climb", api(tok, f"/api/route/{rid}", expect=None, raw=True)[0] == 404)

    # ── S3 · publish/quarantine status flip persists ────────────────
    print("S3 · status flip")
    rid = api(tok, "/api/route", "POST", {"name": "Suite Status Test (E2E)", "area_id": 20})["id"]
    check("new climb starts as draft", api(tok, f"/api/route/{rid}")["status"] == "draft")
    api(tok, f"/api/route/{rid}/status/quarantined", "POST")
    check("quarantine persisted", api(tok, f"/api/route/{rid}")["status"] == "quarantined")
    check("quarantined climb shows in the quarantined queue",
          any(x["id"] == rid for x in api(tok, "/api/queue?status=quarantined")["rows"]))
    api(tok, f"/api/route/{rid}", "DELETE")

    # ── S4 · photo upload → S3 (presign → PUT → finalize) → topo → cleanup ──
    print("S4 · photo upload lands on S3, topo, cleanup")
    rid = api(tok, "/api/route", "POST", {"name": "Suite Upload Test (E2E)", "area_id": 20})["id"]
    pre = api(tok, "/api/topomedia/presign", "POST", {"area_id": 20, "filename": "crag.jpg"})
    key = pre["key"]
    with open(PHOTO, "rb") as f:
        put = urllib.request.urlopen(urllib.request.Request(pre["upload_url"], data=f.read(), method="PUT"), timeout=30)
    check("browser→S3 presigned PUT accepted (200)", put.status == 200, str(put.status))
    fin = api(tok, "/api/topomedia/finalize", "POST",
              {"key": key, "area_id": 20, "credit": "Dan Knight / multi-pitch.com", "license": "owned"})
    tid = fin.get("topo_id")
    check("finalize registered the topo", isinstance(tid, int), str(fin))
    # topo now visible on the route's topoinfo, with a presigned thumb that actually loads
    ti = api(tok, f"/api/route/{rid}/topoinfo")
    topo = next((t for t in ti["topos"] if t["id"] == tid), None)
    check("topo appears on the route's crag", topo is not None)
    if topo:
        tc, tb = api(tok, "", raw=True) if False else (None, None)
        thumb = topo.get("thumb_url", "")
        try:
            tb = urllib.request.urlopen(thumb, timeout=20)
            check("presigned thumb loads as an image", tb.status == 200 and "image" in tb.headers.get("Content-Type", ""),
                  f"{tb.status} {tb.headers.get('Content-Type')}")
        except Exception as e:
            check("presigned thumb loads as an image", False, str(e)[:80])
    # draw a line, then clean up topo (removes S3 media) + climb
    api(tok, f"/api/topo/{tid}/line/{rid}", "PUT",
        {"line": [[0.5, 0.9], [0.5, 0.5], [0.5, 0.1]], "pitches": [], "descent": None})
    check("line saved on the topo", any(l["route_id"] == rid for l in api(tok, f"/api/topo/{tid}")["lines"]))
    api(tok, f"/api/topo/{tid}", "DELETE")
    api(tok, f"/api/route/{rid}", "DELETE")

    # ── S5 · second curator (Dan) can sign in and read ──────────────
    print("S5 · multi-user")
    dan_pw = os.environ.get("DAN_PW")
    if dan_pw:
        dtok = cognito_token("me@danknight.name", dan_pw)
        check("Dan's Cognito login works", len(dtok) > 100)
        check("Dan can read the corpus", isinstance(api(dtok, "/api/queue").get("rows"), list))
    else:
        print("  (skipped — DAN_PW not provided)")

    # ── S6 · corpus intact ──────────────────────────────────────────
    print("S6 · corpus left as found")
    end = total_routes(tok)
    check(f"route count back to baseline ({start})", end == start, f"start {start} != end {end}")

    print(f"\n{'='*46}\n  {len(PASS)} passed · {len(FAIL)} failed")
    if FAIL:
        print("  FAILED:", ", ".join(FAIL))
    return not FAIL


if __name__ == "__main__":
    sys.exit(0 if main() else 1)
