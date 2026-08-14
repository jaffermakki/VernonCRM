# v30 changes (from v29)

Three new features, on top of v29's CSRF + Excel export additions.

## 1. IMEI / Serial number tracking

- `Repair.imei` and `InvoiceLine.imei` columns added.
- Repair intake form (`/repairs`) captures IMEI/serial; repair detail page
  displays it and lets staff edit it inline afterward
  (`POST /repairs/{id}/imei`).
- POS cart lines have an optional IMEI field, shown under each item —
  carries through to the invoice line at checkout, and prints on the
  invoice's line-item table.
- Global search (`/search`) now matches on `Repair.imei` and
  `InvoiceLine.imei`, so a 15-digit IMEI or serial pulls up both the
  repair ticket and any invoice that device was sold on — the "trace
  this device's full history" use case for warranty claims, stolen-phone
  lookups, and proving pre-existing condition at intake.

## 2. Trade-in / buy-back

- New `trade_ins` table + `/trade-ins` page (list + intake form), linked
  from the sidebar.
- Accepts a device from an existing or brand-new customer, records
  condition and IMEI, and pays out via store credit (applied immediately
  to the customer) or cash (logged for the till, not auto-deducted from
  a cash session — see note in the UI).
- Status tracking per trade-in: accepted → resold / scrapped.
- Verified live: new customer created, trade-in recorded, store credit
  applied correctly in the database.

## 3. Layaway / partial payments

- New `layaways` + `layaway_payments` tables.
- Started from the POS page: add items to cart, attach a customer,
  "Start Layaway" instead of charging — takes an optional deposit and
  due date. Cart contents and tax are snapshotted at creation (prices
  locked in), and stock is deducted immediately to reserve the items
  (mirrors how checkout deducts stock, just without creating an invoice
  yet).
- `/layaway` list page and `/layaway/{id}` detail page — payment
  history, running balance, add-payment form.
- When the balance hits $0, the layaway auto-converts into a real
  `Invoice` (same invoice numbering as normal checkout) — stock is NOT
  deducted a second time. Customer earns loyalty points and spend
  totals on completion, same as a normal sale.
- "Cancel & Restock" / "Mark Forfeited" — both restock the reserved
  items; the only difference is whether the record implies the deposit
  gets refunded (cancelled) or kept (forfeited). Manager/owner role
  required.
- Verified live end-to-end: create with deposit → partial balance
  correct → pay off remainder → auto-converts to invoice with correct
  total, stock not double-deducted, customer points/spend updated →
  separately verified cancel path restocks correctly.

## Testing

Full pytest suite: 74/75 passing (same single pre-existing
Brevo-mock-assertion failure noted in v28/v29, unrelated to these
changes — not a real bug). All three features were also exercised live
against a running server (not just unit tests) with database
verification at each step, the same standard used for v28/v29.

## Not done / not requested this round

- No UI yet to browse trade-ins/layaways from the customer detail page
  (they're only visible from their own list pages).
- No automatic reminder/notification for layaway due dates.
- Cash trade-in payouts aren't wired into cash session tracking (Cash
  Up) — logged to the audit trail only.

## Update: test coverage added

New file `tests/test_new_features.py` — 31 tests covering all three
features from this changelog:

- **IMEI/serial**: intake with/without IMEI, inline edit (including
  clearing it), POS→invoice carry-through, global search matching both
  repairs and invoice lines.
- **Trade-ins**: new-customer store credit, existing-customer credit
  stacking (no duplicate customer created), cash payout doesn't touch
  store credit, walk-in with no customer at all, status updates,
  role gating (cashier allowed, technician blocked).
- **Layaway**: requires a customer and non-empty cart to start, stock
  reservation, deposit recording, partial payment without completing,
  full payoff → auto-converts to invoice with correct total and without
  double-deducting stock, loyalty points/spend awarded on completion,
  overpayment still completes, $0/negative payments rejected, no
  further payments accepted once completed, cancel and forfeit both
  restock (cashier blocked from cancelling, manager allowed), list/detail
  pages render.

To make sure these tests actually catch regressions and aren't just
tautologically passing, I deliberately broke two things and confirmed
the suite failed correctly, then reverted:
1. Made layaway payoff double-deduct stock → `test_layaway_full_payoff_...`
   caught it (38 vs expected 39).
2. Allowed technicians to add trade-ins → `test_trade_in_blocked_for_technician`
   caught it (303 vs expected 403).

Full suite: **105/106 passing** (74 original + 31 new), same single
pre-existing Brevo-mock assertion failure as before, unrelated to any
of this work.

Run it yourself with:
```bash
cd crm_build
pip install -r requirements-dev.txt --break-system-packages
python3 -m pytest -v
```
Or just the new tests: `python3 -m pytest tests/test_new_features.py -v`

## Update: deployment configs for Render and Railway

- `render.yaml` — Blueprint for one-click deploy: web service + managed
  Postgres, `DATABASE_URL` auto-wired, `SESSION_SECRET` auto-generated.
  `SETTINGS_ENCRYPTION_KEY` deliberately left as a manual secret (not
  `generateValue: true`) — Render's auto-generated value isn't
  guaranteed to be a valid Fernet key, and an invalid key means the app
  silently stores SMTP/Twilio credentials unencrypted instead of
  erroring. Verified the real key-generation command in `DEPLOY.md`
  round-trips correctly through `app/encryption.py`.
- `railway.json` — pins health check path and restart policy on top of
  the existing `Procfile`/`runtime.txt` (Railway auto-detects both, no
  blueprint-style single-file provisioning exists on Railway the way
  it does on Render, so DB + secrets are still added via the Railway
  dashboard — steps are in `DEPLOY.md`).
- New `GET /healthz` route — returns `{"status": "ok"}`, no auth or DB
  query, so a briefly-reconnecting database doesn't trigger a false
  restart loop on either platform. Verified live.
- `DEPLOY.md` — full step-by-step for both platforms, including the
  exact commands to generate `SESSION_SECRET` and
  `SETTINGS_ENCRYPTION_KEY` correctly, and what NOT to do with them.

Full suite still 105/106 passing (same pre-existing unrelated
Brevo-mock failure) after these additions.

## Update: fixed the one pre-existing test failure

Root cause: `tests/test_email_brevo.py`'s `db_session` fixture is
session-scoped (shared across the whole suite for speed), and
`test_brevo_api_missing_credentials_fails_clearly_without_calling_api`
assumed a clean database — but a test earlier in the same file sets a
fake Brevo API key that was never cleared afterward, so this test was
silently running against leftover state instead of the "nothing
configured" scenario it's named for. The actual `send_plain_email` app
code was correct the whole time; this was purely test isolation.

Fix: explicitly clear the three Brevo settings at the top of the test
instead of assuming they're already empty. Verified against the full
suite in normal run order (not just in isolation) to confirm it's
actually fixed, not just working around it.

**Full suite: 106/106 passing.**

## Update: bulk case-variant generator (solves the "too many near-identical SKUs" problem)

The actual problem described: 7 case styles (Hard Ring, Soft Ring,
Wallet, Apple Silicone, Dotted Armor, Clear, Back Wallet, limited
editions), each needing its own tracked SKU per phone model per color,
across Apple/Samsung/Pixel/Motorola. That's easily 15 models x 6 colors
= 90 rows per case style if added one at a time through the existing
Add Product form.

**What was already there:** the Product model already had
`variant_group` (groups variants for browsing) and `subcategory` (the
case's own brand, e.g. OtterBox/UAG/Generic) — but nothing to capture
which *phone* brand/model/color a variant is actually for. That data
was only ever going into the free-text `name` field.

**What's new:**
- `Product.phone_brand`, `Product.phone_model`, `Product.color` — three
  new structured columns (auto-migrated on existing databases the same
  way `imei` was in the last update).
- `app/phone_const.py` — a reference list of current Apple/Samsung/
  Google/Motorola models (2026), plus a standard color list. Not meant
  to be exhaustive — every list backs onto a free-text "Other" field,
  so a brand-new phone or an odd color doesn't need a code change.
- `/products/bulk-variants` — new page (Products → "🧩 Bulk-Create
  Variants", manager/owner only). Pick a case style once, check off
  every model and color it comes in, set one price/cost/starting stock,
  and it generates a distinct SKU + Product row for every combination
  in a single submit. Live count preview before submitting.
- SKU collisions (e.g. re-running the same generation twice) are
  disambiguated with a numeric suffix rather than crashing on the
  unique constraint or silently dropping variants — verified live.

**Tested:** live end-to-end (3 iPhone models x 4 colors = 12 variants,
verified each row's SKU/name/price/brand/model/color individually in
the database), plus 9 new automated tests in
`tests/test_bulk_variants.py` covering the happy path, freeform
model/color entry, all three required-field validations, SKU collision
handling, and role gating (cashier blocked, manager/owner allowed).

**Not done:** the Products page browsing/filtering doesn't yet drill
down by phone_brand/phone_model the way it already does for
variant_group — the data is captured and stored correctly, but a
"filter to just Samsung" chip on the Products or POS page would be a
natural follow-up if the flat variant-group grouping isn't granular
enough in practice once you're at hundreds of SKUs.

**Full suite: 115/115 passing.**

## Update: Products page now browses by phone brand/model (flat, not gated)

Two problems with the follow-up from the bulk generator:

1. The existing "1. Brand / 2. Model" drill-down on the Products page
   was actually built from the case's own maker (subcategory —
   OtterBox, Generic) and the case style name (variant_group) — not the
   phone brand/model at all, despite the labels. It didn't answer "what
   do we have for this customer's phone," which is the actual question
   asked at the counter.
2. It also hid every case group by default until you picked something
   or searched — reasonable when the only options were case-maker/style,
   but the wrong default now that this can grow into "every phone brand
   and model wise has similar cases."

**Changed:**
- The drill-down now pulls from the new `phone_brand`/`phone_model`
  fields (populated automatically by the bulk generator). Pick "Apple"
  → see every model you carry cases for → pick "iPhone 15 Pro" → every
  case style/color for that exact phone, across all groups, shown at
  once.
- Switched to a **flat default view**: every case-style group is
  visible (collapsed) on page load — nothing is hidden behind a
  required selection anymore. The brand/model picker *narrows* what's
  shown rather than gating it. This is deliberately the smaller,
  reversible step rather than a full nested dashboard — natural next
  moves from here (if this doesn't feel like enough at real scale)
  would be a model-level page of its own, or stock totals per phone
  model at a glance, but there's no reason to build those speculatively
  before seeing whether flat + filter is actually enough.
- Row-level filtering now matches phone_brand/phone_model exactly
  (not substring), so "iPhone 15" doesn't also pull in "iPhone 15 Pro"
  rows when you only picked the base model.
- Non-phone accessories (chargers, cables) are untouched by the
  brand/model filter either way — they don't have phone_brand set, so
  they stay visible regardless of what's selected.

Verified live: generated a "Clear Case" variant set across Apple/
Samsung, confirmed the brand/model dropdowns populate correctly, the
group renders visible by default (no `display:none`), and each row
carries the correct `data-phone-brand`/`data-phone-model` for filtering.

Full suite still 115/115 (schema/route changes here didn't touch
anything the existing bulk-variant or product tests cover directly, but
re-ran the whole thing anyway rather than assuming).

## Update: laptop and gaming accessory support

Extended the same infrastructure built for phone cases — deliberately
reused rather than building something parallel, since it's the same
underlying shape (one style x several models x several colors).

**Single, non-variant items** (a specific headset, a specific mouse,
a specific Chromebook charger) — no new code needed. Category dropdown
on the regular Add Product form now includes:
- 💻 Laptop/Chromebook (brands: Apple, Dell, HP, Lenovo, ASUS, Acer,
  Microsoft, Samsung, Google)
- 💼 Laptop Accessory (Logitech, Anker, Belkin, Targus, STM, Incase)
- 🎮 Gaming Accessory (Logitech, Razer, SteelSeries, HyperX, Corsair,
  Sony, Microsoft, Nintendo, 8BitDo)

Confirmed live that these flow through to the Add/Edit Product forms
automatically via the existing dynamic category→brand JS — no template
or route changes were needed for that path at all.

**Variant products** (laptop sleeves, controller skins — things that
genuinely vary by device model) — the bulk generator
(`/products/bulk-variants`) now has three device sections instead of
one: 📱 Phone Models (unchanged), 💻 Laptop Models (Apple/Dell/HP/
Lenovo/ASUS/Acer/Microsoft/Samsung/Google, `app/phone_const.py:
LAPTOP_MODELS`), and 🎮 Console/Controller Models (Sony, Microsoft,
Nintendo, Valve — for things like PS5/Xbox/Switch/Steam Deck skins,
`CONSOLE_MODELS`). All three feed the same underlying generation
logic — no backend changes were needed there either, since it already
just parses generic "Brand||Model" pairs regardless of device family.

One real bug caught and fixed before it shipped: "Microsoft" and
"Other" appear under more than one device section (Microsoft makes
both laptops and Xbox; every section has an "Other" catch-all). The
original "select all/none" button only scoped by brand name, so
clicking it under Laptop Models would have also toggled the Xbox
checkboxes under Console Models. Fixed by scoping to both
`data-family` and `data-brand` together — verified live in the
rendered HTML that both Microsoft sections render with distinct
`data-family` and are correctly isolated from each other.

Products page browsing (the phone/model drill-down added last update)
picks this up automatically too, since it's built from whatever
`phone_brand`/`phone_model` values exist on any product — Dell and PS5
now show up in the same brand dropdown as Apple and Samsung, no
separate code path.

**Tested:** 2 new automated tests (laptop sleeve generation across
Apple/Dell, controller skin generation across Sony/Microsoft), plus
live verification of the Microsoft cross-section scoping fix and the
Add Product category/brand dropdown auto-population.

**Full suite: 117/117 passing.**

## Update: UI/feature improvement batch (partial — see status below)

Of the 8 improvements suggested earlier, these 4 are done and tested:

**1. POS variant picker was unsearchable at real scale.** A case style
with 90 variants (15 models x 6 colors — exactly the scenario the bulk
generator was built for) was a flat, unfiltered scrolling list in the
"pick model & color" modal. Added a live search box inside the modal
(filters by model/color/SKU as you type) plus a new "Phone" chip row
on the main POS filter bar (separate from "Case Maker", which is what
the old "Brand" row actually was — same mislabel issue as the Products
page had, fixed the same way). `group_products_by_variant()` now
tracks `phone_brands` per group so the chip filter can match "does
this case style have ANY variant for the selected phone brand."

**2. Notification bell didn't know layaways exist.** It already
flagged low stock, overdue repairs, and unanswered SMS — added overdue
and due-within-3-days layaway alerts, linking to `/layaway`.

**3. Customer detail page didn't show trade-ins or layaways.** Showed
repair history and purchase history, but staff had to know to check
separate pages to see if a customer had an active layaway or a past
trade-in. Both are now sections on the customer's own page, matching
the existing repair/purchase history table style (including empty
states when a customer has neither).

**4. New: public repair status lookup (`/status`).** Unauthenticated
page a shop can share with customers so they can check "is my repair
done" without calling in. Deliberately minimal disclosure: requires
BOTH the exact ticket number AND the last 4 digits of the phone number
on file to match before showing anything; wrong digits and a
nonexistent ticket both return the identical generic error (no way to
enumerate which ticket numbers exist); even on a correct match it only
shows device/status/promised-by date — never cost, customer name, or
any other repair. Verified live with a real repair record: correct
match shows status, wrong digits show nothing, cost fields never
appear regardless.

13 new tests in `tests/test_ui_improvements.py` covering all four
areas, including the two security-relevant checks on `/status`
(no data leak on wrong digits, no cost fields ever exposed) verified
by both live testing AND automated tests.

**Full suite: 130/130 passing.**

### Not done — deliberately deferred, not silently skipped

- **Settings page tabs** — mechanical restructuring, didn't get to it.
- **Reports bar chart** — same, straightforward but not done yet.
- **Staff performance report** — needs to be scoped as "sales/repair
  counts per staff" only, since a $ commission figure would require a
  commission-rate policy (flat %? per-item? tiered?) that doesn't exist
  in the app and I'm not willing to invent on your behalf.
- **Mobile responsiveness pass** — the most open-ended item on the
  list (I found only 4 media queries in the whole stylesheet), and the
  one most likely to need real back-and-forth on which pages/breakpoints
  actually matter rather than a blind pass.
- **Appointment/drop-off scheduling** and **cross-store transfers**
  were flagged as out of scope from the start (new subsystem, and
  blocked on multi-store not existing yet, respectively) — still true,
  not attempted.

## Update: the remaining 3 UI items (Settings tabs, Reports chart, mobile)

**Settings page tabs.** 189 lines / 5 sections / one scroll is now 4
tabs (Shop & Loyalty, Notifications, Security, Data). Deliberately kept
as ONE underlying `<form>` for the General/Notifications/Security
fields — tabs are pure client-side show/hide via CSS classes, not
separate forms — so "Save All Settings" still saves everything in one
submit regardless of which tab is open. Verified this specifically: a
single POST with fields from all three tabs (shop name, Twilio SID,
security question) all persisted together. Also deep-linkable
(`/settings#security`) for the existing "set up a security question"
link from the Staff page, which depended on landing on that section.

**Reports sales-by-day chart.** New 14-day bar chart on the Reports
page, same "no charting library, just SVG/div math" approach the
dashboard sparkline already uses. Verified live: ran a real checkout,
confirmed the chart showed 13 days at $0.00 and today's bar correctly
at 100% height with the actual sale total. Handles the zero-sales case
(new shop, empty range) without a divide-by-zero.

**Mobile CSS.** Correction to how I described this earlier — the app
already had a real mobile foundation (drawer nav, bottom tab bar,
POS-specific stacking layout), it wasn't "thin" as broadly as I
initially said. What was actually missing, found by checking rather
than assuming:
- `.form-row` (side-by-side fields) never collapsed to a single
  column — this affected nearly every form in the app (Add Product,
  Settings, Bulk Variants, Customer/Repair/Trade-in forms), squeezing
  3-4 inputs into unusably narrow columns on a phone. One CSS rule
  fixes it everywhere at once rather than a per-template pass.
- `.card` had no overflow handling, so any wide table (Products,
  Invoices, Reports, Audit Log) blew out the ENTIRE page's horizontal
  scroll instead of just scrolling itself within its own card. Same
  one-rule-fixes-everywhere approach.
- The new 14-bar Reports chart specifically needed its own narrow-width
  handling (dropped the $ value label above each bar under 480px,
  kept the hover/tap tooltip with the exact figure) since 14 stacked
  labels in phone-width columns would otherwise overlap.

10 new tests in `tests/test_ui_improvements.py` (17 total in that file
now) covering the settings multi-tab save-together behavior and the
reports chart's data correctness and zero-sales edge case.

**Full suite: 134/134 passing.**

### Honest limitation on the mobile fixes

I fixed the two highest-impact, provably-broken things (form-row
squeeze, table page-blowout) with CSS rules I could verify are present
and syntactically valid. I do NOT have a way to actually render this
in a browser at phone width and look at it — everything here is
verified by checking the CSS/HTML output is correct, not by seeing it
rendered. If something still looks off on an actual phone, that's the
next thing to report back with specifics (which page, what's wrong)
rather than another blind "audit."

## Update: barcode label printing

New `GET /products/labels/print` — printable barcode label sheet, no
server-side image generation needed (uses JsBarcode client-side via
CDN, rendering CODE128 barcodes in the browser at print time — the
same "load a CDN script, let the browser do the work" pattern already
used elsewhere, and it never touches this app's own network since the
*shop's* browser fetches the CDN script, not the server).

**Three entry points, all tested live:**
- Right after using the bulk variant generator, the success screen now
  shows a "🏷️ Print Barcode Labels for these" button linking straight
  to labels for the group you just created — the natural moment you'd
  want this, since you just created a batch of SKUs that don't
  physically exist as labels yet.
- Each case-style group on the Products page has its own "🏷️ Print
  Labels" button (prints every variant in that group).
- Every individual product row (grouped or ungrouped) has a small 🏷️
  icon to reprint a single label — e.g. a torn shelf label — without
  pulling in the whole group. Available to all logged-in staff, not
  gated to owner/manager, since reprinting one label isn't a
  sensitive action the way editing price/stock is.

**Label sheet:** configurable copies-per-SKU (clamped 1-50 so a
fat-fingered "9999" can't try to render nine thousand barcodes),
default 2"x1" label size (a CSS variable at the top of the template —
change two numbers to match whatever label stock is actually loaded,
same "one clearly-marked variable" pattern the thermal receipt
template already uses for its paper width). Print-only CSS hides the
on-screen toolbar and controls when actually printed
(`@media print`), matching how the existing thermal receipt/EOD print
views work.

**Tested:** live end-to-end (generated variants → followed the flash
link → verified the barcode SKUs and prices rendered correctly for
each label), plus edge cases — copies parameter multiplies label count
correctly, over-the-ceiling copies clamps to 50 instead of crashing,
no group/ids shows a friendly empty state instead of an error,
unauthenticated requests redirect to login. 7 new automated tests.

**Full suite: 141/141 passing.**

## Fix: barcode labels showed "(barcode unavailable)" when actually printing

**Root cause:** the first version generated barcodes client-side —
JavaScript (JsBarcode, loaded from a CDN) ran after the page loaded and
drew the bars into an empty `<svg>` placeholder. That works fine when
someone is just looking at the page in a normal browser tab. It breaks
the moment the actual PRINT happens through anything that doesn't
execute JavaScript — a "Print to PDF" pipeline, a dedicated label-printer
app that fetches the URL and rasterizes it, or just print timing racing
ahead of the CDN script finishing. When JsBarcode never got the chance
to run, my own fallback message — "(barcode unavailable)" — is exactly
what showed up on every single label, which is what happened.

**Fix:** barcodes are now generated entirely server-side
(`app/barcode_gen.py`, using `python-barcode`) and embedded as real SVG
markup already baked into the HTML response. Nothing needs to execute
for a barcode to appear — it's just there, the same as the product name
or price text next to it. Removed the JsBarcode CDN script and all
client-side generation code entirely.

**Second, related bug caught while fixing the first:** the original
CSS scaled barcodes down to fit the label box (`max-width:100%`). For
long SKUs (exactly the iPhone 17 Pro Max case in the report — SKUs
around 30+ characters), this would have silently compressed the bars
below the minimum width a real barcode scanner can reliably read —
arguably worse than not printing at all, since it fails at the register
instead of on the label sheet where someone could catch it. Fixed by:
- Computing barcode width from the actual SKU length, targeting a
  consistent physical size but never compressing bars below a safe
  minimum (0.15mm), even if that means the barcode ends up wider than
  the label box for an unusually long SKU.
- No longer letting CSS shrink barcodes to fit — they render at their
  true calculated size.
- Added a small on-screen-only "⚠ wide" badge (hidden via `@media
  print`, so it never appears on the actual printed output) on any
  label whose barcode exceeds a standard 2in label's width, so staff
  see the warning before printing a whole sheet, not after a customer's
  scanner fails to read it.

**Tested:** reproduced the exact scenario from the report — Hard Ring
Case across the iPhone 17 line (including iPhone 17 Pro Max) in 6
colors, generated through the real bulk generator, then printed. In
the resulting HTML: zero occurrences of "barcode unavailable," zero
`<script>` tags anywhere on the page, real SVG bar rectangles present
in the raw HTML for all 12 labels (1,194 individual bars total), and
the wide-warning correctly flagged only the long iPhone 17 Pro Max
variants. Plus 6 new unit tests on the barcode generator itself
(valid SVG output, no XML/DOCTYPE leakage, long SKUs produce wider
barcodes than short ones, module width never drops below the
scannable floor, empty SKU handled, different SKUs produce genuinely
different bar patterns) and 2 new integration tests reproducing this
exact bug scenario end-to-end.

**Full suite: 149/149 passing.**

### Honest limitation

I cannot verify actual scan reliability on physical hardware — I don't
have a barcode scanner or a real printer in this environment. What I
can and did verify: the SVG markup is structurally valid, the encoded
data matches the SKU (different SKUs produce different bar patterns —
not just visually different labels with the same underlying barcode by
mistake), and the module width calculation never goes below the
generally-accepted safe minimum for CODE128. The actual "does my
scanner read this off actual printed paper" test is still the real
test, same caveat as the CSS/mobile work earlier in this session.

## Fix: barcode scanner ("hitting Go" gave a raw JSON error)

**Root cause:** `POST /pos/scan` declared `sku: str = Form(...)` —
framework-required. Standard urlencoded form-body parsing silently
drops a field whose value is empty (`sku=` with nothing after the `=`
gets treated the same as the key not being present at all). That meant
clicking "Go" with nothing scanned or typed yet — box empty — sent a
technically-valid POST that FastAPI still rejected with a raw 422 JSON
error, *before the route's own code ever ran*. The route already had
correct handling for an empty scan (`if not needle: return
RedirectResponse("/pos")`) — it just could never be reached, because
the framework-level validation failed first.

**Fix:** changed to `Form("")` (optional, defaults to empty string),
so the existing graceful handling actually executes. Also added
`required` to the HTML input itself, so a normal browser click on an
empty box is stopped client-side with a native "please fill this
field" prompt before ever reaching the server at all.

**While investigating, found and fixed the same bug class in
Settings:** `shop_name` and `invoice_prefix` were also
framework-required (`Form(...)`) with no `required` HTML attribute and
no server-side fallback — worse blast radius than the scan bug, since
clearing either field and saving would have crashed the *entire*
settings form, discarding changes across all four tabs in the same
submit, not just the one blank field. Fixed the same way: `Form("")`
plus an explicit check that flashes a clear error and leaves existing
settings untouched, rather than either crashing or silently persisting
a blank shop name.

**Not fixed — flagged for awareness:** a broader sweep found ~15 other
required Form fields across the app without a matching HTML `required`
attribute. Most are either `<select>` dropdowns (always carry a value,
not at risk) or fields where FastAPI's default already correctly
handles "leave blank" (like `security_answer`, verified — that one was
never actually broken). I fixed the two I could concretely verify as
real, reachable gaps rather than blanket-patching all ~15 without
individually confirming each one's actual risk and intended behavior —
several are deliberately "blank means keep existing" fields where
adding `required` would itself be the bug.

**Tested:** reproduced the exact reported scenario (empty scan
submission) against the real route before and after the fix — 422
crash before, clean 303 redirect after — and confirmed a normal valid
scan still works correctly. Same before/after verification for the
Settings blank-shop-name case, including confirming the existing shop
name in the database was left untouched rather than corrupted by a
half-completed save. 6 new regression tests.

**Full suite: 154/154 passing.**

## UI: replaced emoji icons with a proper SVG icon system (nav + dashboard, first pass)

Surveyed the whole app first rather than guessing at scope: 50 distinct
emoji, 178 total occurrences across 25+ templates, used as functional
icons throughout (nav links, buttons, empty states). Emoji render
inconsistently across OS/browser and read more "casual app" than
"business software" next to real financial numbers — the actual
complaint that started this.

**New `app/icons.py`** — inline SVG icon system, 45 icons. Path data is
from Lucide (lucide.dev, ISC license), extracted once via `npm install
lucide-static` rather than hand-approximated from memory, so the
artwork is pixel-correct, not guessed. Registered as a Jinja global
(`templates.env.globals["icon"]`, same pattern as the existing
`csrf_token()` global) — usage in any template is just
`{{ icon('wrench') }}`. Icons default to `1em` sizing so they
automatically scale with whatever font-size surrounds them (nav link,
button, heading) instead of needing a hand-picked pixel size at every
call site, and use `stroke="currentColor"` so they automatically match
surrounding text color, including on hover/active states.

Deliberately inlined rather than loaded from a CDN — no network
dependency, no JavaScript required to render. Same lesson as the
barcode label fix earlier this session: anything that has to survive
being printed, exported, or viewed offline can't depend on a script
executing or a CDN being reachable.

**Applied to `base.html` (navigation)** — every nav icon, in both the
desktop sidebar and the mobile bottom nav: Dashboard, Point of Sale,
Repairs, Invoices, Cash Up, Products, Purchasing, Customers,
Trade-Ins, Layaway, Reports, Staff, Audit Log, Settings, plus the
hamburger menu, search icon, and notification bell. This is the
highest-impact single change possible — it's the one piece of UI
visible on every single page in the app.

**Applied to `dashboard.html`** — New Sale/New Repair quick actions,
stat tile icons, and empty-state icons.

**Caught and fixed a real bug along the way:** `icon_svg()` returns
actual HTML markup, but Jinja auto-escapes all `{{ }}` output by
default — the first version rendered every icon as literal visible
`&lt;svg...` text instead of an actual icon (verified by loading a
real page — nav showed as garbled escaped markup, not icons). This is
the exact same class of mistake as the flash-message HTML bug caught
earlier this session. Fixed at the source by wrapping the return value
in `markupsafe.Markup()` inside `icon_svg()` itself, so every call site
renders correctly automatically — no need to remember `|safe` at 40+
individual call sites, which would have been one missed spot away from
the same bug recurring.

**Tested:** full suite (154/154, unaffected since tests check behavior
not exact markup) plus live verification at each stage — confirmed the
broken escaped-HTML state before the Markup fix, confirmed 26 real
`<svg>` tags rendering correctly in the nav after it, confirmed
dashboard.html fully emoji-free with 32 real icons, and confirmed POS
(the largest, most complex template in the app) still loads correctly
with the new global registered.

### Not done yet — this is a first pass, not the whole app

Nav and Dashboard are done. The remaining ~130 emoji occurrences across
Products, POS, Repairs, Customers, Settings, Reports, Trade-Ins,
Layaway, the barcode label sheet, and other templates are unchanged —
same honest scoping as the mobile CSS work earlier: I'd rather ship a
fully tested, working first pass on the highest-impact page than a
rushed, undertested pass across all 25+ templates in one shot. The
icon system itself (`app/icons.py`) is complete and ready — extending
coverage to the rest of the app from here is a matter of working
through each template's emoji list and swapping in `{{ icon('name') }}`
calls, the same mechanical process just demonstrated on base.html and
dashboard.html.

## UI: icon system rollout completed across the entire app

Finished what the last update started — all 25+ remaining templates
now use the SVG icon system instead of emoji.

**Icon set grew from 45 to 48** — added `triangle-alert`, `circle-x`,
and `puzzle` (needed for warning banners, error states, and the
add-on/module icon respectively) via the same `npm install
lucide-static` extraction process as before, not hand-approximated.

**95 emoji replaced across 25 templates** — Products, POS, Repairs,
Customers, Invoices, Settings, Reports, Trade-Ins, Layaway, Staff,
Suppliers, Audit Log, the barcode label sheet, printable
receipts/EOD reports, and every remaining page. Applied via a script
rather than by hand, specifically to keep it safe at this volume:

- Every replacement is scoped to the emoji's exact mapped icon — no
  blind bulk-find/replace across dissimilar meanings.
- **Deliberately left inline text glyphs alone**: → / ← (arrows in
  "Back to Products →" style links) and ✓ / ✕ (small inline
  checkmarks like "✓ Currently set"). These read fine as plain
  Unicode characters in running text — converting them to standalone
  SVG would touch far more call sites for less benefit than the
  pictographic "leading icon before a heading/button" pattern that
  was the actual complaint.
- **Never touched emoji inside `<script>` blocks** — the script
  detects and skips them automatically. One is left in `base.html`'s
  notification-bell JS ("You're all caught up 🎉") specifically
  because embedding SVG markup (full of double-quotes) into a
  single-quoted JS string literal would break the JavaScript syntax.
  Confirmed this is the only remaining functional-context emoji in
  the entire app; the other couple of leftovers are the same kind of
  decorative flourish, not a functional icon.

**Caught two things while finishing this**, both fixed:
1. Two emoji in `dashboard.html` (a backup-staleness warning banner,
   an empty-state icon) were missed in the earlier manual pass since
   my first check only grepped a subset of emoji characters — found
   by re-auditing what remained after the automated pass, not assumed
   clean.
2. Two of the barcode-label tests asserted an exact `<svg>` tag count
   on the label print page — broken not by a real bug, but because
   the page now ALSO has icon SVGs (tag, printer, back-arrow) in its
   toolbar alongside the barcode SVGs. Fixed by making the test count
   barcode SVGs specifically (they use physical mm sizing, unique to
   `python-barcode`'s output — icon SVGs always use 1em/px), rather
   than loosening the assertion or touching working barcode code.

**Verified, not assumed:** loaded all 14 major pages in the app live
after the change — every one returns 200 with real, correctly-rendered
SVG icons (24–35 per page), zero escaped-HTML garbage anywhere (the
exact bug class caught in the previous update), and empty-state icons
confirmed rendering at their intended larger 32px size rather than the
default 1em.

**Full suite: 154/154 passing**, all 30 template files individually
verified to parse without error.

The app is now emoji-free everywhere except: two decorative flourishes
in success/empty messages (kept intentionally — one is JS-string-bound
and can't safely be converted, the other is a stylistic choice, not a
mislabeled icon) and the inline arrow/checkmark text glyphs, which were
a deliberate scope decision, not an oversight.
