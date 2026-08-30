/**
 * The spoken explanations, as text.
 *
 * Every number in here is checked against the repo — the four signal weights
 * against `detection/config.py`, the sweep against §5b, the thresholds against
 * the detector. A spoken explanation is *harder* to fact-check than a written
 * one, because a listener cannot scan back, so these are held to the same
 * standard as the page copy and the transcript is always shown beside the
 * audio.
 *
 * `source` is not decoration. It is the difference between "Claude wrote this
 * about this cluster" and "we wrote this and the browser is reading it aloud",
 * and this project does not blur that line anywhere else either.
 */

export interface Explainer {
  id: string;
  question: string;
  /** Where the words came from. Shown to the listener, verbatim. */
  source: string;
  text: string;
}

export const LANDING_EXPLAINERS: Explainer[] = [
  {
    id: "why",
    question: "Why RingSentinel?",
    source: "Written by the team · read by your browser",
    text: `Most fraud tools score one payment at a time. That works for a stolen card, and it cannot work for a ring, because coordination does not exist inside a single payment. It exists between them. RingSentinel builds a graph of which accounts share a device, an address, or a card, and scores the cluster instead of the payment. On the seeded corpus that found twelve rings out of twelve, with no false flags. Every score breaks into four named signals, so a reviewer can argue with the number rather than trust it. And nothing here can block, freeze, or decline anyone. A database trigger makes that a property of the schema rather than a promise in a document.`,
  },
  {
    id: "flagging",
    question: "How does flagging work?",
    source: "Written by the team · read by your browser",
    text: `Four signals, each measured and weighted. Attribute reuse, at forty-five percent, asks how many separate accounts funnel through one card, device, or address. Timing regularity, at twenty-five percent, asks whether the gaps between payments look like a person or a script. Concentration asks how much of the cluster's volume runs through the shared attribute. Account shallowness asks whether these accounts have real histories, or exist only to place one discounted order. A shared address counts for less than a shared card, deliberately. Households share addresses. A weight of nought point four is what keeps a family from being flagged as a crew.`,
  },
  {
    id: "calibration",
    question: "How was the threshold chosen?",
    source: "Written by the team · read by your browser",
    text: `The threshold is nought point three, and it was measured rather than chosen. Sweeping it across the tuning split, anything between nought point two five and nought point three five found all eight rings with zero false flags. Below that band a false flag appears. Above nought point four, real rings start being missed. Nought point three sits in the centre of the flat region, and that is the whole point. The weakest cluster scores nought point three seven, so the threshold could move seven hundredths and nothing at all would change. A threshold in the middle of a plateau is a measurement. One perched on a cliff edge is a fit.`,
  },
];

export const CONSOLE_EXPLAINERS: Explainer[] = [
  {
    id: "page",
    question: "What is this page?",
    source: "Written by the team · read by your browser",
    text: `This is the review queue. Every row is a cluster of accounts the detector flagged as possibly coordinated. Never a single payment, always a group. Nothing on this page has been acted on. A flag is a request for your attention, not a decision, and no code path in this system can block, freeze, or decline anyone. Select any cluster and its full case opens below: what Claude wrote about it, the four signals behind the score, the accounts and what they share, and the decision, which is yours to make.`,
  },
  {
    id: "workflow",
    question: "What should I do here?",
    source: "Written by the team · read by your browser",
    text: `Seven steps, numbered down the panel. Read Claude's case file first. It is plain language, and it is advisory only. Then check the four signals, because the score is a sum of named parts rather than a model output. Step three tells you how close it was: the smallest change that would have flipped the verdict. Step four is the graph of accounts and what they share. Step five is your decision, and it needs a written reason. The database refuses a decision without one. Step six is the audit trail, which cannot be rewritten. Step seven rebuilds the evidence pack and re-verifies the hash chain, live.`,
  },
  {
    id: "states",
    question: "Pending, ambiguous — what's the difference?",
    source: "Written by the team · read by your browser",
    text: `Three states, and the difference matters. Pending means flagged, and the detector is confident. Ambiguous means flagged, but the score landed between nought point three and nought point four five. The detector is telling you it is unsure, rather than forcing a binary it cannot support. Both still mean a human has to look. Approved and dismissed are decisions, and only a human review action can set them. Once recorded, a decision is never revised. The trigger refuses it even inside a review, because otherwise the audit log would disagree with the row it describes.`,
  },
];
