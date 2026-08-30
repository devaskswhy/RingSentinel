# Static assets

## razorpay.png — not committed, and optional

Drop Razorpay's official logo here as `razorpay.png` and the landing page
footer will render it in the "Built for the Razorpay AI Buildathon" credit. If
the file is absent the credit falls back to a plain wordmark, so nothing
breaks — see `BuildathonCredit` in `app/page.tsx`.

Download it from https://razorpay.com/newsroom/brand-assets/

**Use the reversed (light-on-dark) variant.** The footer sits on a near-black
background, so the standard navy wordmark is close to invisible there. Brand
kits ship a white/reversed version for exactly this case — use that one rather
than recolouring the standard mark, which brand guidelines generally prohibit.

Two constraints worth keeping:

- **Footer only.** The logo must not appear in the nav, the hero, or the
  favicon. Those are RingSentinel's own branding positions, and a third-party
  mark there reads as endorsement. `ARCHITECTURE.md` states that Razorpay has
  not reviewed or endorsed this project; the interface should not contradict
  the documentation.
- **It is their trademark, not ours.** Razorpay's brand assets are subject to a
  Usage Agreement that is not published on the brand-assets page. It is not
  committed to this repository for that reason — the file stays local.
