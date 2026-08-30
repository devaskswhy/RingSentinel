<p align="center">
  <img src="docs/img/banner.svg" alt="RingSentinel — coordinated fraud, seen as a graph" width="100%">
</p>

# RingSentinel

**Razorpay AI Buildathon · AI Risk Manager track**

[**Live site**](https://ring-sentinel-khaki.vercel.app) · [**API**](https://ringsentinel.onrender.com/docs) · [Architecture](ARCHITECTURE.md) · [Where it's weak](BLINDSPOTS.md) · [How it makes money](MONETIZATION.md) · [Deploying](DEPLOY.md)

> Most fraud tools score one payment at a time. That works for a stolen card and
> cannot work for a ring, because **coordination does not exist inside a single
> transaction — it exists between them.**
>
> RingSentinel builds a graph of which accounts share a device, an address, or a
> card, scores the *cluster*, has Claude explain it in plain language, and puts a
> human in front of every decision. **Nothing auto-blocks. Ever.**

---

## The one-minute version

|  |  |
|---|---|
| **Problem** | Card-testing, promo-farming and return-abuse crews are invisible per transaction. Each order is small, valid, in policy — and the coordination only shows up as a shape across accounts. |
| **Approach** | Graph the shared attributes. Cluster. Score with four named signals. Explain with Claude. Gate on a human. |
| **On our corpus** | **12/12 rings found, 0 false flags** — including 4/4 on a held-out split opened once |
| **On real data** | **1.62× top-decile lift** on 590,540 IEEE-CIS transactions we did not generate |
| **What it will never do** | Block, freeze or decline anyone. No code path exists; a Postgres trigger enforces it |
| **Cost** | **$0.07/month** of model spend at 100k transactions — 2,137× cheaper than scoring each one |

---

## Why this track, and why this idea

The AI Risk Manager brief asks for *"a working detector… with measured precision
and recall on a held-out test set"* and sets one hard rule: **"strictly
defense-only: anything offense-capable is disqualified."** It lists
*"abuse-ring sentinel"* as an example direction.

Most entries to a track like this will build a per-transaction classifier. That
is the obvious move and it cannot solve the stated problem, because a single
transaction contains no evidence of coordination — however good the model is.
This is not an argument about model quality. It is definitional.

So RingSentinel makes the opposite bet: **the unit of detection is the cluster,
never the payment.** Everything else follows from that one decision — why the
score decomposes into named signals, why the cost is three orders of magnitude
lower, why a human can actually review the output, and why the same design would
extend across merchants in a way no single merchant could replicate.

---

## How it works

```
Razorpay test-mode orders          real orders, real order_… ids
        │
        ▼
POST /webhooks/razorpay            HMAC-SHA256 over the raw body
        │
        ▼
app/ingest.py                      entities · entity_links · transactions
        │                          idempotent: ON CONFLICT DO NOTHING
        ▼
detection/                         NetworkX graph → clusters → four-signal score
        │                          deterministic; reads a label-free view only
        ▼
app/case_files.py                  Claude writes the explanation
        │                          allowed_tools=[] — no function to call
        ▼
app/routers/clusters.py            ▐ THE HUMAN GATE
                                   approve / dismiss, written reason required
                                   enforced by a Postgres trigger
        ▼
audit_log                          append-only, hash-chained
```

### The four signals

Every weight lives in one file (`detection/config.py`). Nothing numeric is
buried in the scoring code.

| Signal | Weight | Question it asks |
|---|---|---|
| Attribute reuse | **0.45** | How many separate accounts funnel through one card, device or address? |
| Timing regularity | **0.25** | Do the gaps look like a person, or a script? |
| Concentration | **0.15** | How much of the cluster's volume runs through the shared attribute? |
| Account shallowness | **0.15** | Do these accounts have real histories, or exist for one discounted order? |

**Attribute type weights are the point**: instrument `1.00`, device `0.85`,
address **`0.40`**. A shared delivery address is a household far more often than
a crew, so address overlap alone cannot flag a cluster. That weight is what
keeps a family from being treated as a ring — and it has a measured cost, which
is reported rather than defended.

---

## The results, including the ones that hurt

### On the seeded corpus

1,499 transactions built from **real Razorpay test-mode orders** — every row
traces to a genuine `order_…` id fetchable from Razorpay.

| Metric | Held-out (rings 9–12) | Tuning (rings 1–8) |
|---|---|---|
| Rings detected | **4/4 (100%)** | 8/8 (100%) |
| Cadence classified correctly | **4/4** | 8/8 |
| False flags | **0** | 0 |
| Clean accounts swept in | 0 of 105 | 0 of 105 |
| Runtime | 0.04s, deterministic | — |

Rings 9–12 were sealed from generation and opened once, with the config verified
byte-identical to the commit that produced it. Nothing was tuned afterwards.

> ⚠️ **What this does and does not mean.** This is a synthetic corpus *this
> project generated*, and it is separable by construction: the busiest benign
> attribute is shared by 3 accounts while rings reach 9. So 100% means the
> detector does what it was designed to do on data of this shape. It is not a
> claim about production accuracy, and anyone quoting it should say so.

### On real data we did not create

Because the caveat above is not good enough on its own, the same detector was
run unmodified against **IEEE-CIS Fraud Detection** — 590,540 real transactions
with a 3.50% fraud base rate, where a single card carries 14,112 of them.

**The first result was a failure, and it is committed before any attempt to fix
it.** At the calibrated threshold the detector flagged **99% of the dataset**
with a lift of **1.01×**. The diagnostics say why: attribute reuse saturated at
0.97 because real clusters run 50–282 accounts, and the assumption that sharing
above a small floor is suspicious does not survive real payment data.

Digging further produced the useful finding:

| Slice by score | Fraud rate | Lift |
|---|---|---|
| top 2% | 3.43% | **1.61×** |
| top 10% | 3.23% | **1.52×** |
| top 25% | 3.13% | 1.47× |
| top 50% | 2.45% | 1.15× |
| everything | 2.17% | 1.02× |

**The score ranks real fraud risk. The absolute threshold does not transfer.**
Selecting by review capacity instead of a fixed cut recovers **1.43×** on the
same data. 1.5× is modest and is reported as modest — but it is real, measured,
reproducible, and on data this project did not build.

```bash
docker compose exec backend python -m scripts.evaluate_ieee --limit 100000 --budget 25
```

### Does the scorer beat a one-line heuristic?

Nothing in the repo answered this until it was measured. Same graph, same
clustering, same candidates — only the flagging rule changes.

| Rule | Recall | Precision | False flags |
|---|---|---|---|
| **RingSentinel** | 100% | **100%** | 0 |
| Naive: any attribute shared by ≥3 accounts | 100% | 92% | 1 |
| Attribute reuse alone | 92% | 92% | 1 |
| Largest clusters | 92% | 92% | 1 |
| Random | 75% | 75% | 3 |

Honest reading: **on this corpus the four signals buy one avoided false positive
over a rule that fits on one line.** That is a weak justification, and it is
published rather than hidden.

### So does each signal earn its weight?

| Weighting | Seeded recall | Real-data top-decile lift |
|---|---|---|
| All four signals | 100% | **1.62×** |
| without attribute reuse | 67% | 1.35× |
| without timing regularity | **100%** (no cost) | 1.35× |
| without concentration | **100%** (no cost) | 1.37× |
| without account shallowness | 92% | 1.51× |

**The two signals that look like dead weight on synthetic data are among the
most valuable on real data.** The seeded corpus is separable by attribute reuse
alone, so the behavioural signals never get a chance to matter; on real data,
where sharing a card is ubiquitous and uninformative, timing and concentration
are what discriminate.

That is the strongest available answer to *"why four signals?"* — and it could
only be obtained by testing on data this project did not generate.

---

## What it deliberately cannot do

This is the part enforced by the database, not by good intentions.

| Guarantee | How it is enforced |
|---|---|
| **No automated blocking, freezing or declining** | No code path exists to call. Clusters only ever change `status`, and only from a human review action |
| **Every decision is human-made** | `trg_clusters_status_human_only` rejects any status change outside a transaction carrying `ringsentinel.human_review` **and** a written reason of ≥5 characters |
| **A decision is never revised** | The same trigger refuses to move a cluster *out* of a decided state, even inside a review — otherwise the audit log would contradict the row |
| **The audit log is never rewritten** | Append-only trigger raises on UPDATE / DELETE / TRUNCATE |
| **Tampering is detectable, not merely blocked** | Every row stores `sha256(prev_hash ‖ row)`. Someone with raw database access can drop a trigger; they cannot make the arithmetic add up afterwards |
| **The detector never sees ground truth** | Detection reads `v_transactions_detector`, a view without the label column. An AST walk fails the build if any module under `detection/` names it |
| **Claude explains, never decides** | Prompt says so; `allowed_tools=[]` means no function exists; the trigger refuses it anyway. Three independent layers |

Hand this to anyone who wants to check rather than be told — it exits non-zero
the moment a guarantee breaks:

```bash
docker compose exec backend python -m scripts.verify_human_gate
```

Both tamper paths were tested by actually breaking them. Rewriting a decided
row's reason was caught as *"the row's contents no longer hash to its recorded
hash"*; dropping the guard trigger was caught as a missing trigger.

---

## Where AI is used, and where it deliberately is not

Built on the **Claude Agent SDK** — the same SDK Razorpay used for Agent Studio.

Claude does exactly two things, and neither is detection:

1. **Writes the case file** that explains a flagged cluster to the analyst.
2. **Designs the blind-spot tests.** BLINDSPOTS.md carried a caveat it could not
   answer for itself — *"the cases share an author with the detector"* — so
   Claude, which has never seen the source, designs cases from the published
   description alone. It returns a *specification*; our code realises it.

Detection itself is deterministic graph and statistics work. No model output
influences whether a cluster is flagged, what it scores, or what happens to it.

**That split is the point.** An LLM asked to score 1,499 transactions would be
slower, more expensive, non-reproducible and impossible to audit — and worse at
the task, because the signal lives in the graph rather than in any transaction's
text. Using a model for the part that needs language, and refusing to use it for
the part that needs determinism, is what "AI applied appropriately" means here.

### What Claude found that we did not

Given only the published design, it produced five cases. **The detector handled
none of them** — three rings missed, and two innocent cases wrongly flagged:

| Case | Outcome |
|---|---|
| Ring rotating instruments in pairs | missed — every attribute sits under the 3-account floor |
| Reshipping ring sharing only addresses | missed — exploits the deliberate 0.40 address weight |
| Aged mule pool, k held at 3 | missed — sits where the saturation curve is weakest |
| Family sharing card, device and address | **wrongly flagged at 0.55** |
| Campus kiosk cohort on scheduled top-ups | **wrongly flagged at 0.57** |

We then built the obvious fix — a `linkage` signal that counts attributes below
the evidence floor — measured it, and **left it switched off**:

| linkage weight | address-only ring | family (innocent) |
|---|---|---|
| 0.00 *(shipped)* | missed | flagged 0.547 |
| 0.20 | **caught** | **worse: 0.747** |
| 0.35 | caught | much worse: 0.897 |

A household sharing a card, a device and an address is the most tightly-joined
thing in any graph, so a signal rewarding joinedness cannot separate one from a
crew. Enabling it would trade a missed ring for a wrongly flagged family. **For
a system whose entire claim is that it does not act on people, that is the worse
error.** The capability exists, is measured, and is documented as *not adopted*.

---

## The two surfaces

### The landing page

Four beats: the problem → the mechanism → the flag → the gate. The scroll
sequence is **every one of the 1,499 real transactions** on a canvas: 900 stay
scattered, 599 migrate into the twelve real rings. With eighteen hand-placed
dots, *"nothing is added, the data was always this shape"* is a claim. At real
scale it is a demonstration.

Section 06 is a **threshold scrubber**: drag the flag threshold and watch rings
drop out, with every tick a real cluster score. It states the calibration
argument as you move it — *nothing changes anywhere between 0.300 and 0.370* —
and refuses to go below 0.30, because the detector stores nothing there and
inventing a number would be fabrication.

### The review console

Land on the queue. Pick a cluster and its full case opens below in seven
numbered steps: case file → four signals → how close it was → the graph →
your decision → the audit trail → **verify the chain**, which rebuilds the
evidence pack and re-checks all 1,879 rows live.

Spoken explanations in eight languages sit behind a help card — real
translations, not an English script read by a foreign voice. A cluster's case
file is read aloud in Claude's own words, labelled *"Claude's case file ·
English only"*, because machine-translating an artefact the audit log records
would make the spoken version differ from the recorded one.

---

## Running it

```bash
cp .env.example .env
docker compose up                                        # db + backend + frontend
```

Frontend → http://localhost:3000 · API docs → http://localhost:8000/docs

```bash
# the corpus — real Razorpay test-mode orders
docker compose exec backend python -m scripts.seed_rings --reset

# detect, explain, measure
docker compose exec backend python -m scripts.detect
docker compose exec backend python -m scripts.generate_case_files
docker compose exec backend python -m scripts.report --split holdout

# the proofs
docker compose exec backend python -m scripts.verify_human_gate
docker compose exec backend python -m scripts.verify_detector_isolation
docker compose exec backend python -m scripts.verify_resilience
docker compose exec backend python -m scripts.verify_explanation_grader

# the measurements that made this honest
docker compose exec backend python -m scripts.compare_baselines
docker compose exec backend python -m scripts.ablate_signals --ieee 20000
docker compose exec backend python -m scripts.evaluate_ieee --budget 25
docker compose exec backend python -m scripts.adversarial_cases
docker compose exec backend python -m scripts.monetization --merchants 50 --transactions 2000
```

---

## Defence-only

No evasion guidance is produced anywhere in this repository, and all traffic
runs against a local test-mode instance only. The synthetic and diagnostic
generators exist to **trigger** detection so it can be measured — never to
defeat it. Adversarial cases are inserted, measured and rolled back in a
`finally`; results are reported as weakness classes, never as a reproducible
recipe. Nothing in the codebase can block, freeze or decline a customer.

---

## Honest limits

Stated here rather than discovered by someone else:

- **The corpus is synthetic and self-generated.** Separable by construction.
  The IEEE-CIS run exists because that caveat is not good enough alone.
- **1.5× lift is modest.** It is real and reproducible; it is not a production
  claim, and the account proxy it rests on (card + address) is a modelling
  choice, not a fact in the data.
- **The adversarial realiser is imperfect.** Twelve accounts over six
  instruments becomes six disjoint pairs, so some cases test something adjacent
  to their design. Recorded rather than quietly re-run until it looked better.
- **No unit test suite.** Six `verify_*` scripts prove the invariants; the
  scoring maths has no unit tests.
- **RBI's 2026 draft Model Risk Management guidance is a *draft*, non-binding,
  and its scope covers banks, NBFCs and payments banks — not payment
  aggregators.** Razorpay is an aggregator and is *not* bound by it. The honest
  claim is that this is the direction the regulation is heading and many of
  Razorpay's own merchants would be on the hook.

---

## Screenshots

<!-- Add captures to docs/img/ and they will render here. -->

| | |
|---|---|
| ![Landing](docs/img/landing-hero.png) | ![Transaction field](docs/img/landing-field.png) |
| **The landing page** — 1,499 real transactions, the corpus donut, the measured result | **The field mid-scroll** — 599 transactions migrating into the twelve real rings |
| ![Threshold scrubber](docs/img/scrubber.png) | ![Console queue](docs/img/console-queue.png) |
| **Section 06** — drag the threshold; every tick is a real cluster score | **The review console** — the queue, and what to do on the page |
| ![Cluster case](docs/img/console-case.png) | ![Evidence pack](docs/img/console-evidence.png) |
| **One cluster** — four named signals, the graph with its callouts | **Verify the chain** — 1,879 audit rows re-checked live |

---

<p align="center">
  <sub>
    Built for the Razorpay AI Buildathon · AI Risk Manager track.<br>
    Razorpay has not reviewed or endorsed this project. Razorpay is referenced
    because the project is built on their test-mode API and the same Agent SDK.
  </sub>
</p>
