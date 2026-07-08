# Notifications & Push

**Status: not built (research only).** This doc captures the options for a **push/alert
delivery mechanism** so the daily job can reach Michel *off the page* — no polling the
dashboard. It's the delivery side of several roadmap items:
[Stage 0 #2 price-drop alerting](../roadmap/roadmap.md), Stage 0 #8 digest, and
[Stage 2 contingency alerting](../roadmap/roadmap.md). Pick a channel when the first of
those actually ships.

## What we'd notify about

Ordered by likely value — each is a *change worth interrupting the day for*, not a daily
"still fine" ping (constrain alerts to when Michel can act, per
[multi-pitch-site-plan §1.4](../roadmap/multi-pitch-site-plan.md)):

1. **Flight change** — `flights-latest.json` price drop below a threshold, or a schedule
   change on the locked combo (Stage 0 #2 / #3).
2. **Weather / seepage alert** — the chosen venue's forecast turns bad, with the top-3 dry
   alternatives (Stage 2 contingency engine).
3. **Trip daily check** — an opt-in digest: today's top pick + cheapest fare (Stage 0 #8).
4. **Build health** — the daily Action failed / a page didn't deploy (ops hygiene).

## The one hard constraint

**GitHub Pages is static — it cannot send anything.** But the **daily GitHub Action is a
server-side environment** that already runs at 06:00 UTC and after every push. So *the
Action is the sender*: any channel below is a step at the end of the workflow (a `curl` or
a small Python call), gated on `if: success()`/`failure()` and given secrets from the repo.
No extra always-on server, no cost. See [deployment.md](deployment.md) for the job shape.

> Ownership note: the send step lives in `.github/workflows/weather.yml`, which is the
> concurrent process's lane — this doc specifies *what* to wire, not a change to that file.

## Channel options (all have a free tier)

| Channel | Setup | Reaches phone closed? | Notes |
|---|---|---|---|
| **GitHub native email** | Zero — toggle in Settings → Notifications → Actions | Email only | Free, no code. Good for *build failure* only; can't customise body; noisy on daily success. |
| **SMTP email** (`dawidd6/action-send-mail`) | Gmail **app password** as a repo secret | Email only | Full control of subject/body (e.g. link to live page). The standard free custom-email path. |
| **Telegram bot** | `@BotFather` → bot token + chat id (2 secrets) | ✅ push | Official free API, one `curl` to `api.telegram.org`, no relay, very reliable. **Lowest-friction real push.** |
| **ntfy.sh** | Install ntfy app, pick a topic | ✅ push (native app) | One `curl -d "msg" ntfy.sh/<topic>`. No keys, no accounts. Sidesteps the iOS web-push limitation via its own app. Topic is a shared secret — don't send sensitive data. |
| **CallMeBot (WhatsApp)** | Message their number once → personal API key | ✅ push (WhatsApp) | Free `curl`. Third-party relay — fine for "build done" pings, not for secrets. |
| **WhatsApp Cloud API** | Meta Business account + app | ✅ push (WhatsApp) | Official, free low-volume tier, but heavy setup — overkill for a personal ping. |
| **Web push (own PWA)** | Service worker + VAPID keys + subscription store + `pywebpush` send step | ✅ push (from our own page) | Most moving parts; only choose if it must come from *our* page with no third party. See below. |
| **OneSignal** | Drop-in web-push SDK + dashboard | ✅ push | Middle ground: branded web push without rolling your own; free tier. |

## Web push, specifically (the "notification from our own page" route)

A true browser push (fires even when the page is closed) needs three parts:
1. The page registers a **service worker**; the user allows notifications → the browser
   returns a **subscription** (endpoint + encryption keys).
2. That subscription is **stored** where the build can read it (a committed JSON / gist).
3. The Action **signs and sends** the push with a **VAPID** key pair (`pywebpush` fits our
   Python stack) to the browser's push service.

Caveats: **on iPhone** it only works if the site is **Added to Home Screen** (iOS 16.4+) —
no install, no push. This is why ntfy (its own app) or Telegram is the pragmatic pick for a
personal alert, and self-hosted web push is reserved for the productised multi-user surface
(Stage 6), where "from our own brand, no third party" actually matters.

## Recommendation

- **Now / personal alerts:** **Telegram** (no app-store friction on any device, no relay) or
  **ntfy** (if a native app icon is preferred, esp. on iPhone). Either is ~5 minutes and one
  `curl`.
- **Build-failure only:** GitHub native email — zero code.
- **Later / product surface:** web push via `pywebpush`, or OneSignal, once notifications go
  multi-user and need to come from multi-pitch.com itself.
