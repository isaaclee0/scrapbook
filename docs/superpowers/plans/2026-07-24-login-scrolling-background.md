# Login Page Scrolling Photo Background Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the login page's static purple gradient background with a multi-column grid of curated photos that scroll upward continuously (parallax), behind a frosted-glass login card.

**Architecture:** Pure frontend change confined to `templates/login.html` (inline `<style>` + markup) plus a new folder of bundled static images. No routes, DB, or JS framework involved — the "columns" are plain `<div>`s with duplicated `<img>` lists animated via CSS `@keyframes`.

**Tech Stack:** Flask/Jinja2 template, vanilla CSS (existing inline `<style>` block in `login.html`), no new JS dependencies.

**Design doc:** `docs/superpowers/specs/2026-07-24-login-scrolling-background-design.md`

---

## Curated photo list (locked in, user-approved)

All photos are free-license Unsplash photos fetched directly from `images.unsplash.com` with resize/compress query params (`w=500&q=75&fm=jpg&fit=crop&crop=entropy`), so no local image-processing tooling is needed.

| # | Filename | Source URL (with resize params) | Photographer |
|---|----------|-----------------------------------|---------------|
| 1 | login-bg-01.jpg | `https://images.unsplash.com/photo-1516483638261-f4dbaf036963?w=500&q=75&fm=jpg&fit=crop&crop=entropy` | Jack Ward |
| 2 | login-bg-02.jpg | `https://images.unsplash.com/photo-1469854523086-cc02fe5d8800?w=500&q=75&fm=jpg&fit=crop&crop=entropy` | Dino Reichmuth |
| 3 | login-bg-03.jpg | `https://images.unsplash.com/photo-1507608616759-54f48f0af0ee?w=500&q=75&fm=jpg&fit=crop&crop=entropy` | ian dooley |
| 4 | login-bg-04.jpg | `https://images.unsplash.com/photo-1504754524776-8f4f37790ca0?w=500&q=75&fm=jpg&fit=crop&crop=entropy` | Rachel Park |
| 5 | login-bg-05.jpg | `https://images.unsplash.com/photo-1532980400857-e8d9d275d858?w=500&q=75&fm=jpg&fit=crop&crop=entropy` | Monika Grabkowska |
| 6 | login-bg-06.jpg | `https://images.unsplash.com/photo-1546793665-c74683f339c1?w=500&q=75&fm=jpg&fit=crop&crop=entropy` | Monika Grabkowska |
| 7 | login-bg-07.jpg | `https://images.unsplash.com/photo-1618221195710-dd6b41faaea6?w=500&q=75&fm=jpg&fit=crop&crop=entropy` | Spacejoy |
| 8 | login-bg-08.jpg | `https://images.unsplash.com/photo-1583847268964-b28dc8f51f92?w=500&q=75&fm=jpg&fit=crop&crop=entropy` | Minh Pham |
| 9 | login-bg-09.jpg | `https://images.unsplash.com/photo-1622372738946-62e02505feb3?w=500&q=75&fm=jpg&fit=crop&crop=entropy` | Kam Idris |
| 10 | login-bg-10.jpg | `https://images.unsplash.com/photo-1618588507085-c79565432917?w=500&q=75&fm=jpg&fit=crop&crop=entropy` | Navi |
| 11 | login-bg-11.jpg | `https://images.unsplash.com/photo-1541904563-f637f76a470d?w=500&q=75&fm=jpg&fit=crop&crop=entropy` | Aaron Burden |
| 12 | login-bg-12.jpg | `https://images.unsplash.com/photo-1573399968917-bfc283b885b0?w=500&q=75&fm=jpg&fit=crop&crop=entropy` | Nathan Queloz |
| 13 | login-bg-13.jpg | `https://images.unsplash.com/photo-1613985212734-166ffb5a513d?w=500&q=75&fm=jpg&fit=crop&crop=entropy` | Konstantin Dyadyun |
| 14 | login-bg-14.jpg | `https://images.unsplash.com/photo-1572251328450-19c5082bc582?w=500&q=75&fm=jpg&fit=crop&crop=entropy` | kevin laminto |
| 15 | login-bg-15.jpg | `https://images.unsplash.com/photo-1520367745676-56196632073f?w=500&q=75&fm=jpg&fit=crop&crop=entropy` | Clem Onojeghuo |
| 16 | login-bg-16.jpg | `https://images.unsplash.com/photo-1485570661444-73b3f0ff9d2f?w=500&q=75&fm=jpg&fit=crop&crop=entropy` | Clem Onojeghuo |

**Column assignment** (5 desktop columns, uneven split since 16 isn't divisible by 5):

| Column | Photos (by #) |
|---|---|
| 1 | 1, 2, 3, 4 |
| 2 | 5, 6, 7 |
| 3 | 8, 9, 10 |
| 4 | 11, 12, 13 |
| 5 | 14, 15, 16 |

---

## File structure

| File | Change |
|---|---|
| `static/images/login-bg/login-bg-01.jpg` … `login-bg-16.jpg` | New — curated background photos |
| `static/images/login-bg/CREDITS.md` | New — Unsplash photographer attribution |
| `templates/login.html` | Modified — background layer markup/CSS, frosted-glass card, responsive + reduced-motion handling |

---

### Task 1: Download curated background photos

**Files:**
- Create: `static/images/login-bg/login-bg-01.jpg` … `login-bg-16.jpg`
- Create: `static/images/login-bg/CREDITS.md`

- [ ] **Step 1: Create the directory and download all 16 photos**

```bash
mkdir -p static/images/login-bg

curl -sL "https://images.unsplash.com/photo-1516483638261-f4dbaf036963?w=500&q=75&fm=jpg&fit=crop&crop=entropy" -o static/images/login-bg/login-bg-01.jpg
curl -sL "https://images.unsplash.com/photo-1469854523086-cc02fe5d8800?w=500&q=75&fm=jpg&fit=crop&crop=entropy" -o static/images/login-bg/login-bg-02.jpg
curl -sL "https://images.unsplash.com/photo-1507608616759-54f48f0af0ee?w=500&q=75&fm=jpg&fit=crop&crop=entropy" -o static/images/login-bg/login-bg-03.jpg
curl -sL "https://images.unsplash.com/photo-1504754524776-8f4f37790ca0?w=500&q=75&fm=jpg&fit=crop&crop=entropy" -o static/images/login-bg/login-bg-04.jpg
curl -sL "https://images.unsplash.com/photo-1532980400857-e8d9d275d858?w=500&q=75&fm=jpg&fit=crop&crop=entropy" -o static/images/login-bg/login-bg-05.jpg
curl -sL "https://images.unsplash.com/photo-1546793665-c74683f339c1?w=500&q=75&fm=jpg&fit=crop&crop=entropy" -o static/images/login-bg/login-bg-06.jpg
curl -sL "https://images.unsplash.com/photo-1618221195710-dd6b41faaea6?w=500&q=75&fm=jpg&fit=crop&crop=entropy" -o static/images/login-bg/login-bg-07.jpg
curl -sL "https://images.unsplash.com/photo-1583847268964-b28dc8f51f92?w=500&q=75&fm=jpg&fit=crop&crop=entropy" -o static/images/login-bg/login-bg-08.jpg
curl -sL "https://images.unsplash.com/photo-1622372738946-62e02505feb3?w=500&q=75&fm=jpg&fit=crop&crop=entropy" -o static/images/login-bg/login-bg-09.jpg
curl -sL "https://images.unsplash.com/photo-1618588507085-c79565432917?w=500&q=75&fm=jpg&fit=crop&crop=entropy" -o static/images/login-bg/login-bg-10.jpg
curl -sL "https://images.unsplash.com/photo-1541904563-f637f76a470d?w=500&q=75&fm=jpg&fit=crop&crop=entropy" -o static/images/login-bg/login-bg-11.jpg
curl -sL "https://images.unsplash.com/photo-1573399968917-bfc283b885b0?w=500&q=75&fm=jpg&fit=crop&crop=entropy" -o static/images/login-bg/login-bg-12.jpg
curl -sL "https://images.unsplash.com/photo-1613985212734-166ffb5a513d?w=500&q=75&fm=jpg&fit=crop&crop=entropy" -o static/images/login-bg/login-bg-13.jpg
curl -sL "https://images.unsplash.com/photo-1572251328450-19c5082bc582?w=500&q=75&fm=jpg&fit=crop&crop=entropy" -o static/images/login-bg/login-bg-14.jpg
curl -sL "https://images.unsplash.com/photo-1520367745676-56196632073f?w=500&q=75&fm=jpg&fit=crop&crop=entropy" -o static/images/login-bg/login-bg-15.jpg
curl -sL "https://images.unsplash.com/photo-1485570661444-73b3f0ff9d2f?w=500&q=75&fm=jpg&fit=crop&crop=entropy" -o static/images/login-bg/login-bg-16.jpg
```

- [ ] **Step 2: Verify all 16 files downloaded and are valid non-empty JPEGs**

```bash
ls -la static/images/login-bg/*.jpg | wc -l
file static/images/login-bg/*.jpg | grep -c "JPEG image data"
find static/images/login-bg -name "*.jpg" -size -1k
```

Expected: first two commands both print `16`; the `find` command (which
catches truncated/empty downloads) prints nothing.

- [ ] **Step 3: Write the credits file**

```markdown
# Login background photo credits

All photos are from [Unsplash](https://unsplash.com), used under the
[Unsplash License](https://unsplash.com/license) (free to use, no
attribution required — listed here anyway for reference).

| File | Photographer | Source |
|---|---|---|
| login-bg-01.jpg | Jack Ward | https://images.unsplash.com/photo-1516483638261-f4dbaf036963 |
| login-bg-02.jpg | Dino Reichmuth | https://images.unsplash.com/photo-1469854523086-cc02fe5d8800 |
| login-bg-03.jpg | ian dooley | https://images.unsplash.com/photo-1507608616759-54f48f0af0ee |
| login-bg-04.jpg | Rachel Park | https://images.unsplash.com/photo-1504754524776-8f4f37790ca0 |
| login-bg-05.jpg | Monika Grabkowska | https://images.unsplash.com/photo-1532980400857-e8d9d275d858 |
| login-bg-06.jpg | Monika Grabkowska | https://images.unsplash.com/photo-1546793665-c74683f339c1 |
| login-bg-07.jpg | Spacejoy | https://images.unsplash.com/photo-1618221195710-dd6b41faaea6 |
| login-bg-08.jpg | Minh Pham | https://images.unsplash.com/photo-1583847268964-b28dc8f51f92 |
| login-bg-09.jpg | Kam Idris | https://images.unsplash.com/photo-1622372738946-62e02505feb3 |
| login-bg-10.jpg | Navi | https://images.unsplash.com/photo-1618588507085-c79565432917 |
| login-bg-11.jpg | Aaron Burden | https://images.unsplash.com/photo-1541904563-f637f76a470d |
| login-bg-12.jpg | Nathan Queloz | https://images.unsplash.com/photo-1573399968917-bfc283b885b0 |
| login-bg-13.jpg | Konstantin Dyadyun | https://images.unsplash.com/photo-1613985212734-166ffb5a513d |
| login-bg-14.jpg | kevin laminto | https://images.unsplash.com/photo-1572251328450-19c5082bc582 |
| login-bg-15.jpg | Clem Onojeghuo | https://images.unsplash.com/photo-1520367745676-56196632073f |
| login-bg-16.jpg | Clem Onojeghuo | https://images.unsplash.com/photo-1485570661444-73b3f0ff9d2f |
```

Save this as `static/images/login-bg/CREDITS.md`.

- [ ] **Step 4: Commit**

```bash
git add static/images/login-bg/
git commit -m "Add curated background photos for login page"
```

---

### Task 2: Add the background layer markup (static grid, no motion yet)

**Files:**
- Modify: `templates/login.html:156-158` (opening of `<body>`, before `.login-container`)

- [ ] **Step 1: Insert the background layer markup right after `<body>`**

In `templates/login.html`, find:

```html
<body>
    <div class="login-container">
```

Replace with (5 columns, photos per the column-assignment table above, each
column's image list written twice back-to-back so the loop added in Task 3
is seamless):

```html
<body>
    <div class="bg-scroll" aria-hidden="true">
        <div class="bg-col">
            <img src="{{ url_for('static', filename='images/login-bg/login-bg-01.jpg') }}" alt="">
            <img src="{{ url_for('static', filename='images/login-bg/login-bg-02.jpg') }}" alt="">
            <img src="{{ url_for('static', filename='images/login-bg/login-bg-03.jpg') }}" alt="">
            <img src="{{ url_for('static', filename='images/login-bg/login-bg-04.jpg') }}" alt="">
            <img src="{{ url_for('static', filename='images/login-bg/login-bg-01.jpg') }}" alt="">
            <img src="{{ url_for('static', filename='images/login-bg/login-bg-02.jpg') }}" alt="">
            <img src="{{ url_for('static', filename='images/login-bg/login-bg-03.jpg') }}" alt="">
            <img src="{{ url_for('static', filename='images/login-bg/login-bg-04.jpg') }}" alt="">
        </div>
        <div class="bg-col">
            <img src="{{ url_for('static', filename='images/login-bg/login-bg-05.jpg') }}" alt="">
            <img src="{{ url_for('static', filename='images/login-bg/login-bg-06.jpg') }}" alt="">
            <img src="{{ url_for('static', filename='images/login-bg/login-bg-07.jpg') }}" alt="">
            <img src="{{ url_for('static', filename='images/login-bg/login-bg-05.jpg') }}" alt="">
            <img src="{{ url_for('static', filename='images/login-bg/login-bg-06.jpg') }}" alt="">
            <img src="{{ url_for('static', filename='images/login-bg/login-bg-07.jpg') }}" alt="">
        </div>
        <div class="bg-col">
            <img src="{{ url_for('static', filename='images/login-bg/login-bg-08.jpg') }}" alt="">
            <img src="{{ url_for('static', filename='images/login-bg/login-bg-09.jpg') }}" alt="">
            <img src="{{ url_for('static', filename='images/login-bg/login-bg-10.jpg') }}" alt="">
            <img src="{{ url_for('static', filename='images/login-bg/login-bg-08.jpg') }}" alt="">
            <img src="{{ url_for('static', filename='images/login-bg/login-bg-09.jpg') }}" alt="">
            <img src="{{ url_for('static', filename='images/login-bg/login-bg-10.jpg') }}" alt="">
        </div>
        <div class="bg-col">
            <img src="{{ url_for('static', filename='images/login-bg/login-bg-11.jpg') }}" alt="">
            <img src="{{ url_for('static', filename='images/login-bg/login-bg-12.jpg') }}" alt="">
            <img src="{{ url_for('static', filename='images/login-bg/login-bg-13.jpg') }}" alt="">
            <img src="{{ url_for('static', filename='images/login-bg/login-bg-11.jpg') }}" alt="">
            <img src="{{ url_for('static', filename='images/login-bg/login-bg-12.jpg') }}" alt="">
            <img src="{{ url_for('static', filename='images/login-bg/login-bg-13.jpg') }}" alt="">
        </div>
        <div class="bg-col">
            <img src="{{ url_for('static', filename='images/login-bg/login-bg-14.jpg') }}" alt="">
            <img src="{{ url_for('static', filename='images/login-bg/login-bg-15.jpg') }}" alt="">
            <img src="{{ url_for('static', filename='images/login-bg/login-bg-16.jpg') }}" alt="">
            <img src="{{ url_for('static', filename='images/login-bg/login-bg-14.jpg') }}" alt="">
            <img src="{{ url_for('static', filename='images/login-bg/login-bg-15.jpg') }}" alt="">
            <img src="{{ url_for('static', filename='images/login-bg/login-bg-16.jpg') }}" alt="">
        </div>
    </div>
    <div class="bg-overlay"></div>
    <div class="login-container">
```

Don't forget to add the matching closing structure — the existing
`</div>` that currently closes `.login-container` at the end of the file
is unaffected; only the opening tags change.

- [ ] **Step 2: Add base CSS for the background layer (static, no animation)**

In the `<style>` block, find:

```css
        body {
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            min-height: 100vh;
            display: flex;
            align-items: center;
            justify-content: center;
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, Ubuntu, Cantarell, sans-serif;
        }
```

Replace with:

```css
        body {
            background-color: #1a1a2e;
            min-height: 100vh;
            display: flex;
            align-items: center;
            justify-content: center;
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, Ubuntu, Cantarell, sans-serif;
            overflow: hidden;
        }
        .bg-scroll {
            position: fixed;
            inset: 0;
            z-index: 0;
            display: flex;
            gap: 8px;
            padding: 8px;
            overflow: hidden;
        }
        .bg-col {
            flex: 1;
            display: flex;
            flex-direction: column;
            gap: 8px;
        }
        .bg-col img {
            width: 100%;
            border-radius: 8px;
            display: block;
            object-fit: cover;
        }
        .bg-overlay {
            position: fixed;
            inset: 0;
            z-index: 1;
            background: rgba(10, 10, 20, 0.15);
            pointer-events: none;
        }
```

- [ ] **Step 3: Verify the static grid renders**

Start the app (see Task 7 for the full dev-server recipe if it's not
already running) and load `/auth/login` in the browser. Expected: five
columns of photos fill the viewport, no animation yet, login card sits on
top (it will look visually broken/overlapping until Task 4 restyles the
card — that's expected at this point).

- [ ] **Step 4: Commit**

```bash
git add templates/login.html
git commit -m "Add static photo grid background to login page"
```

---

### Task 3: Add the parallax scroll animation

**Files:**
- Modify: `templates/login.html` (`<style>` block)

- [ ] **Step 1: Duplicate each column's photo list a second time in the markup**

The seamless-loop trick requires each column to render its photo list
**twice** back-to-back so `translateY(-50%)` always has matching content
scrolled into view. Task 2 already wrote each column's list twice — verify
this is the case (re-check the markup from Task 2, Step 1: each `.bg-col`
should contain 6–8 `<img>` tags, exactly two copies of its assigned
photos). No markup change needed here if Task 2 was followed exactly.

- [ ] **Step 2: Add the keyframes and per-column animation**

In the `<style>` block, add after the `.bg-overlay` rule:

```css
        @keyframes scrollUp {
            from { transform: translateY(0); }
            to   { transform: translateY(-50%); }
        }
        .bg-col { animation: scrollUp linear infinite; }
        .bg-col:nth-child(1) { animation-duration: 22s; }
        .bg-col:nth-child(2) { animation-duration: 28s; }
        .bg-col:nth-child(3) { animation-duration: 19s; }
        .bg-col:nth-child(4) { animation-duration: 25s; }
        .bg-col:nth-child(5) { animation-duration: 31s; }
```

(This adds `animation` to the existing `.bg-col` rule block from Task 2 —
either extend that rule or add a new one; both are equivalent in CSS.)

- [ ] **Step 3: Verify smooth, seamless looping motion**

Reload `/auth/login`. Expected: all five columns drift upward
continuously at visibly different speeds, and the loop point is not
noticeable (no visible jump/snap). Watch for at least one full loop of the
fastest column (~19s) to confirm no seam.

- [ ] **Step 4: Commit**

```bash
git add templates/login.html
git commit -m "Animate login background columns with staggered parallax scroll"
```

---

### Task 4: Frosted-glass login card

**Files:**
- Modify: `templates/login.html` (`<style>` block, `.login-container` rule)

- [ ] **Step 1: Update `.login-container`**

Find:

```css
        .login-container {
            background: white;
            border-radius: 16px;
            box-shadow: 0 20px 60px rgba(0, 0, 0, 0.3);
            padding: 48px;
            max-width: 450px;
            width: 90%;
        }
```

Replace with:

```css
        .login-container {
            position: relative;
            z-index: 2;
            background: white;
            border-radius: 16px;
            box-shadow: 0 20px 60px rgba(0, 0, 0, 0.3);
            padding: 48px;
            max-width: 450px;
            width: 90%;
        }
        @supports (backdrop-filter: blur(1px)) or (-webkit-backdrop-filter: blur(1px)) {
            .login-container {
                background: rgba(255, 255, 255, 0.72);
                backdrop-filter: blur(10px);
                -webkit-backdrop-filter: blur(10px);
            }
        }
```

(Base rule keeps solid white as the universal fallback; the `@supports`
block upgrades to frosted glass only where the browser can actually blur,
so text never sits on an under-blurred semi-transparent panel.)

- [ ] **Step 2: Verify legibility**

Reload `/auth/login`. Expected: card is semi-transparent with a visible
blur of the photos behind it; all text (title, subtitle, labels, info box)
remains clearly readable against the blurred background at every point in
the scroll cycle (watch through one full loop).

- [ ] **Step 3: Commit**

```bash
git add templates/login.html
git commit -m "Make login card frosted glass over the scrolling background"
```

---

### Task 5: Responsive column count

**Files:**
- Modify: `templates/login.html` (`<style>` block)

- [ ] **Step 1: Add breakpoints hiding columns on narrower viewports**

Add to the `<style>` block:

```css
        @media (max-width: 900px) {
            .bg-scroll .bg-col:nth-child(n+4) { display: none; }
        }
        @media (max-width: 600px) {
            .bg-scroll .bg-col:nth-child(n+3) { display: none; }
        }
```

- [ ] **Step 2: Verify at mobile and tablet widths**

Using the browser's resize/viewport tool, check:
- ~1280px wide: 5 columns visible.
- ~800px wide: 3 columns visible (4th/5th hidden), remaining 3 stretch to
  fill the width.
- ~400px wide: 2 columns visible, login card still fully legible and not
  clipped.

- [ ] **Step 3: Commit**

```bash
git add templates/login.html
git commit -m "Reduce login background to fewer columns on narrow viewports"
```

---

### Task 6: Respect `prefers-reduced-motion`

**Files:**
- Modify: `templates/login.html` (`<style>` block)

- [ ] **Step 1: Add the media query**

Add to the `<style>` block:

```css
        @media (prefers-reduced-motion: reduce) {
            .bg-col { animation-play-state: paused; }
        }
```

- [ ] **Step 2: Verify by reading the rule back**

There's no OS-level "reduced motion" toggle available in the dev browser
tooling used for this project, so verify by confirming the rule is present
and correctly scoped (targets `.bg-col`, matches the animation property
name from Task 3) rather than by simulating the OS setting. If the
engineer's own OS has reduced-motion enabled system-wide, loading the page
directly should show a static (paused) first frame instead of motion —
useful as a real-world sanity check if available.

- [ ] **Step 3: Commit**

```bash
git add templates/login.html
git commit -m "Pause login background animation for prefers-reduced-motion"
```

---

### Task 7: Full manual verification pass

**Files:** none (verification only)

- [ ] **Step 1: Ensure the dev stack is running**

```bash
docker compose ps
```

If it's not running: make sure Docker Desktop is open (`open -a Docker` on
macOS, then wait for it to finish starting), then:

```bash
docker compose up -d
```

- [ ] **Step 2: Load the login page in the browser at desktop width**

Navigate to `http://localhost:8000/auth/login` (adjust host/port if your
`.env` differs) at a desktop viewport (~1280×800). Confirm:
- Photo columns scroll continuously with visibly staggered speeds.
- No layout jump/seam at the loop point.
- Frosted-glass card is legible throughout the scroll cycle.
- No broken image icons (all 16 files load — check the browser's network
  panel or console for 404s).

- [ ] **Step 3: Resize to mobile width and re-check**

Resize to ~375×812. Confirm 2 columns show, card remains centered and
fully legible, no horizontal scrollbar/overflow introduced by the
background layer.

- [ ] **Step 4: Functional smoke test — the OTP form still works**

Confirm the existing login flow (email submission → OTP form swap) is
visually unaffected — the background/card styling changes shouldn't have
touched `#emailForm`/`#otpForm` behavior, but click through the "Send
Code" button once to confirm the form still submits and the JS (unchanged
in this plan) still runs without console errors.

- [ ] **Step 5: Report results**

Note any visual issues found (contrast problems on specific photos,
jank, overflow) — if any surface, they're small CSS follow-ups on the
same files, not new tasks against other parts of the app.
