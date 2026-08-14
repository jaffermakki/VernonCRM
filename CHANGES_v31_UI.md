# v31 — Full UI rebuild ("Anodized Bench")

Complete visual overhaul of every screen. **No routes, forms, field names,
JavaScript hooks, database calls, or business logic were changed.** The full
existing test suite (154 tests) passes unmodified.

---

## Design direction

Grounded in the shop the software actually runs in — anodized-aluminium
greys, hi-vis tool amber for anything you act on, and a single instrument
teal reserved for the Shop Pulse and nothing else.

| | |
|---|---|
| **Surfaces** | `#0B0D12` base → `#12151D` cards → `#181C26` raised → `#212633` hover, hairline `#232936` borders |
| **Accent** | Tool amber `#FFC53D` (dark) / `#F0A81E` (light) |
| **Telemetry** | Teal `#4FD8C4` — Shop Pulse only |
| **Display / UI type** | Archivo (400–800) |
| **Data type** | IBM Plex Mono, tabular figures — money, SKUs, ticket numbers |

Both fonts load from Google Fonts with `display=swap` and a full system
fallback stack, so a shop with no internet still gets correct layout and
weights — just the fallback face.

---

## What changed

### Theming
- Complete design-token system in `static/style.css`: semantic colour,
  type scale, radii, shadows, and motion timing.
- **Light theme added** alongside dark, both first-class. Toggle sits in
  the top bar. Choice persists in `localStorage` and is applied by a tiny
  inline script in `<head>` before first paint, so there is no flash of
  the wrong theme on load.
- Dark remains the default for a fresh install — the counter machine
  lives in dark.
- ~500 hardcoded hex colours across the templates were converted to
  theme tokens, so both themes flow through inline styles too.

### Navigation
- Sidebar regrouped into **Counter / Workshop / Inventory / People /
  Business** with section labels, a brand mark, and a staff avatar block
  pinned to the bottom.
- Active item gets a tinted pill plus an accent rail; role-gated links
  behave exactly as before.
- Mobile: frosted top bar and bottom tab bar, off-canvas drawer with a
  scrim. Duplicate controls (two theme toggles, the `Ctrl K` hint) are
  hidden on small screens.

### Components rebuilt
Cards, tables (uppercase micro-headers, row hover, tabular numerics),
forms and focus rings, the full button set, badges, chips, the kanban
repair board, tabs and range tabs, checklist, activity feed, empty
states, notification dropdown, and the PIN lock screen.

### Shop Pulse
The signature element, kept and upgraded. It now carries a scope-style
readout — **peak day** and **daily average**, both computed from the same
real series the trace is drawn from. Trace, fill gradient, and glow are
all theme-driven, so it reads correctly on white as well as black.

### Keyboard
- `Ctrl` / `Cmd` + `K` focuses global search.
- `Esc` closes the drawer and the notification dropdown, and blurs search.

### Print
A global print stylesheet now hides app chrome (sidebar, top bar, bottom
nav, util bar, action buttons) and resets the page to black on white.
Printing from any page behaves. The paper invoice, thermal receipt, EOD
report, and label sheet templates were deliberately left untouched.

---

## Bugs fixed along the way

**1. The POS depended on `cdn.tailwindcss.com` at runtime.**
With no internet the entire till rendered as unstyled text — and that CDN
build is explicitly not intended for production. Every utility class the
POS relied on is now defined natively in section 21 of `style.css` and the
`<script>` tag is gone. The POS renders identically with the network
unplugged, and loads faster.

**2. Broken search inputs on Products, Customers, and Invoices.**
An inline SVG icon was being interpolated into a `placeholder=""`
attribute (`placeholder="{{ icon('search') }} Search by…"`). The `<svg`
broke out of the attribute and leaked raw markup onto the page. All three
are now proper search fields with the icon as a sibling element.

**3. PWA manifest colours** still referenced the old palette; updated,
along with light/dark `theme-color` meta tags.

---

## Files touched

| File | Change |
|---|---|
| `static/style.css` | Rewritten |
| `static/manifest.json` | Colours |
| `templates/base.html` | New app shell |
| `templates/login.html` | New lock screen |
| `templates/pos.html` | Tailwind CDN removed, tokenised |
| `templates/products.html`, `customers.html`, `invoices.html` | Search field bug fixed, tokenised |
| `templates/dashboard.html` | Pulse readout added, tokenised |
| `cashup / customer_detail / eod_report / layaway_detail / reports / settings / smtp_diagnose / staff` | Tokenised |
| `app/icons.py` | Added `sun` and `moon` icons |

`app/icons.py` is the only Python file changed, and the change is purely
additive — two new entries in the `ICONS` dict.

---

## Notes for deployment

- The stylesheet link carries `?v=31` so shop machines pick up the new CSS
  without a hard refresh.
- The service worker does not cache assets, so nothing else is stale.
- If you would rather the app follow the operating system's light/dark
  setting instead of defaulting to dark, change one line in the head
  script of `templates/base.html`:

  ```js
  if(!t) t = window.matchMedia('(prefers-color-scheme: light)').matches ? 'light' : 'dark';
  ```

- To reskin the whole app to a different accent, edit `--accent`,
  `--accent-hover`, `--on-accent`, `--accent-text`, `--accent-soft`,
  `--accent-border`, and `--accent-glow` in the two theme blocks at the
  top of `style.css`. Nothing else needs touching.

---

## Brand assets (v31.1)

The real **tech-pro+** wordmark is now in the product, not a stand-in
wrench glyph.

### Two colourways, one artwork

The supplied logo is white-and-red on a solid black field. Shipping that
file as-is only works on a black background, so the black was keyed out
(brightest-channel alpha, un-premultiplied so the antialiased edges don't
fringe grey) and two transparent colourways were produced:

| File | Marks | Used by |
|---|---|---|
| `static/logo-light.png` | White + red plus | Dark theme UI |
| `static/logo-dark.png` | Ink `#101520` + red plus | Light theme UI, invoices, receipts |

Both are in the page; CSS shows exactly one based on `data-theme`, so the
logo switches with the theme and never disappears into its background.
The red plus is untouched in both.

### Where it appears

- Sidebar header (links to the dashboard), above a "Repair & Retail" line
- Mobile top bar
- PIN lock screen
- A4 invoice and thermal receipt

### App icons regenerated

The old `icon-192.png` / `icon-512.png` were the wordmark squeezed into a
square — it cropped mid-word to "ech-pr" and was unreadable at any size.
Replaced with the distinctive plug-**e** glyph, extracted from the
wordmark by column-profiling the artwork, set on a `#0B0D12` tile with the
red plus, and sized to sit inside the maskable safe circle.

### Print fix

The invoice and thermal receipt were both pulling `static/logo.jpg` — the
black-background version. On white paper that printed as a solid black
rectangle, and on a thermal printer it burned a full-width black band on
every single receipt. Both now use the ink colourway on transparency.
`logo.jpg` is left in place, unused, in case anything else references it.

---

## v32 — POS: no more full-page reloads

Every cart-mutating action on the POS screen — add, remove, change qty,
apply a discount, attach a customer, redeem points/credit, hold/recall a
cart, scan a barcode — used to be a full page `POST` → `303 redirect` →
full `GET` reload. That's now a `fetch()` that swaps just the cart panel
back in. Verified end-to-end in a real browser: **zero page navigations**
across a full session (add → qty → discount → payment switch → remove →
scan success → scan failure → hold → recall).

**Checkout and "Start Layaway" still do a real navigation** — on purpose,
since they take you to a different page (the invoice, the layaway) to
show the result of the sale. Nothing else about POS behavior changed:
same routes, same validation, same session model, same audit logging.

### How it works
- `templates/partials/pos_cart.html` is the cart/payment column, rendered
  from a new shared `pos_cart_context()` helper in `app/main.py`.
- Every mutating POS route now ends in `pos_response(request, db)`
  instead of an unconditional redirect: if the request carries an
  `X-Pos-Ajax` header (the till's own JS sets this), it returns just that
  partial as HTML; otherwise it does the exact original full-page
  redirect. **This means the app works identically with JavaScript off**
  — nothing here is JS-only, the AJAX path is additive.
- The front-end is a single delegated `submit` listener (survives every
  DOM swap without re-binding), plus a `posAjaxSubmit()` that does the
  fetch, swaps `#cart-panel`, and resyncs the handful of client-side-only
  state that lives outside the swapped markup: the `TOTAL` JS variable,
  the active payment-pill highlight, and (new, wasn't preserved even
  before) the tendered/split-payment amounts and cart scroll position.

### Bug caught during this pass
The qty +/- buttons carry their value via `<button name="qty"
value="...">`, not a real input field — that's normal for a plain HTML
form submit, but a bare `new FormData(form)` in JS does **not** include a
clicked button's name/value (only real fields). Missing that would have
sent qty updates with no `qty` field, silently falling back to a real
navigation on every single tap of the + or − button — i.e., the exact
thing this change was meant to eliminate, on the single most-used control
on the screen. Fixed by capturing the native `SubmitEvent.submitter` and
folding its name/value into the FormData manually.

---

## v37 — Scan now opens a price-check step, not a direct add

Scanning a barcode used to add straight to the cart at whatever price was
on file — no chance to catch a wrong price, and no way to apply an
on-the-spot discount without going back and editing the line afterward.
It now hands the scanned product to the exact same price-check modal a
tapped tile already opens: price field pre-selected and editable, "Add to
Cart" only fires once confirmed. A customer asking for a better price on
a case is now a normal part of the scan flow, not a workaround.

This only changes the AJAX (JS-enabled) path — the real, everyday one.
The non-AJAX fallback (JS failed, a stale tab, curl) still adds directly,
unchanged, since there's no way to show a modal at all without JS.

**Also included in this build:** every round of work from this project so
far — v31 through v36 (full UI redesign, real branding, instant POS,
payment reconciliation, the checkout-order reminder, the error-handling
sweep, and the embedded email receipt logo) — confirmed present via a
full recursive content diff against the working copy before packaging,
not just a filename check (a filename-only check is exactly what let a
stale copy slip through once already this round).

### Files touched
| File | Change |
|---|---|
| `app/main.py` | `/pos/scan` forks on the AJAX header — JSON lookup response instead of a direct cart mutation for the JS path; non-AJAX path unchanged |
| `templates/pos.html` | New `#scan-feedback` banner, `handleScanSubmit()`, delegated listener special-cases the scan form, dead `isScan` branch in `posAjaxSubmit()` removed |
| `tests/test_ui_improvements.py` | 4 new tests covering the AJAX scan path specifically, since every existing scan test only ever exercised the non-AJAX fallback |
