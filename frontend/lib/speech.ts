"use client";

/**
 * Spoken explanations, using the browser's own speech synthesiser.
 *
 * Why not ElevenLabs or a hosted TTS: this has to work during a recorded demo
 * on a laptop, with no API key, no per-call cost, and no network round trip
 * that can fail while someone is watching. `speechSynthesis` is built into
 * every current browser, starts instantly, and costs nothing. The voice is less
 * polished than a paid service and that is the right trade here.
 *
 * Two quirks it works around, both real and both easy to be caught by:
 *
 *   1. `getVoices()` is empty on first call in Chrome — voices load
 *      asynchronously and arrive on a `voiceschanged` event.
 *   2. Chrome silently stops an utterance at roughly fifteen seconds. Long text
 *      has to be split into sentence-sized utterances and queued, which also
 *      makes pausing and cancelling behave sensibly.
 */

export type SpeechState = "idle" | "speaking" | "unsupported";

export function speechSupported(): boolean {
  return typeof window !== "undefined" && "speechSynthesis" in window;
}

/** Split on sentence ends, keeping chunks short enough for Chrome's cutoff. */
function chunk(text: string, max = 180): string[] {
  const sentences = text.replace(/\s+/g, " ").trim().match(/[^.!?]+[.!?]*/g) ?? [text];
  const out: string[] = [];
  let buf = "";
  for (const s of sentences) {
    if ((buf + s).length > max && buf) {
      out.push(buf.trim());
      buf = s;
    } else {
      buf += s;
    }
  }
  if (buf.trim()) out.push(buf.trim());
  return out;
}

/**
 * Prefer a natural English voice when the platform offers one. Windows and
 * macOS both ship several; the ordering below picks the better ones first and
 * falls through to whatever exists.
 */
function pickVoice(voices: SpeechSynthesisVoice[]): SpeechSynthesisVoice | null {
  if (!voices.length) return null;
  const english = voices.filter((v) => v.lang?.toLowerCase().startsWith("en"));
  const pool = english.length ? english : voices;
  const preferred = [
    /natural/i, /neural/i, /google uk english female/i, /google us english/i,
    /samantha/i, /aria/i, /jenny/i, /libby/i, /sonia/i,
  ];
  for (const re of preferred) {
    const hit = pool.find((v) => re.test(v.name));
    if (hit) return hit;
  }
  return pool[0] ?? null;
}

let cachedVoice: SpeechSynthesisVoice | null = null;

export function primeVoices(): void {
  if (!speechSupported()) return;
  const load = () => {
    cachedVoice = pickVoice(window.speechSynthesis.getVoices());
  };
  load();
  // Chrome populates the list asynchronously; without this the first play uses
  // the default voice and every later one uses the good one, which is worse
  // than just always using the default.
  window.speechSynthesis.addEventListener("voiceschanged", load, { once: true });
}

export function stopSpeaking(): void {
  if (!speechSupported()) return;
  window.speechSynthesis.cancel();
}

/**
 * Speak `text`, calling `onEnd` when it finishes or is cancelled. Returns a
 * cancel function so a caller can stop it without touching the global queue.
 */
export function speak(text: string, onEnd: () => void): () => void {
  if (!speechSupported()) {
    onEnd();
    return () => {};
  }
  const synth = window.speechSynthesis;
  synth.cancel();

  const parts = chunk(text);
  let cancelled = false;
  let index = 0;

  const next = () => {
    if (cancelled || index >= parts.length) {
      if (!cancelled) onEnd();
      return;
    }
    const u = new SpeechSynthesisUtterance(parts[index++]);
    if (cachedVoice) u.voice = cachedVoice;
    u.rate = 1.0;
    u.pitch = 1.0;
    u.onend = next;
    // A failed utterance must not strand the UI in a "speaking" state.
    u.onerror = () => {
      if (!cancelled) onEnd();
    };
    synth.speak(u);
  };

  next();

  return () => {
    cancelled = true;
    synth.cancel();
    onEnd();
  };
}
