"use client";

/**
 * The help card: the questions people actually ask, answered aloud, in the
 * language and at the speed they want.
 *
 * Not a chatbot, on purpose. A chat box on a fraud tool invites open-ended
 * questions it would answer from a model with no grounding in this codebase,
 * and the first confidently wrong answer about what the detector does would
 * undo everything the rest of the site is careful about. A fixed set of checked
 * answers cannot hallucinate.
 *
 * Only languages this device has a voice for are offered. Listing a language
 * the browser cannot pronounce would either play silence or read the text in
 * the wrong accent, and both are worse than not offering it.
 *
 * The transcript is always on screen. Someone on a silent laptop, someone deaf,
 * and someone checking a figure against the repo all need the words; speech is
 * the addition, not the medium.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  LANGUAGES,
  RATES,
  type Explainer,
  type LangCode,
} from "@/lib/explainers";
import {
  availableLangs,
  primeVoices,
  speak,
  speechSupported,
  stopSpeaking,
} from "@/lib/speech";

const LANG_KEY = "ringsentinel.voice.lang";
const RATE_KEY = "ringsentinel.voice.rate";

export default function VoiceGuide({
  topics,
  label = "Ask",
  clusterTopics = [],
}: {
  topics: Explainer[];
  label?: string;
  /** Built from the open cluster, if there is one. */
  clusterTopics?: Explainer[];
}) {
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState<string | null>(null);
  const [playing, setPlaying] = useState<string | null>(null);
  const [supported, setSupported] = useState(true);
  const [lang, setLang] = useState<LangCode>("en");
  const [rate, setRate] = useState<number>(1);
  const [ready, setReady] = useState(0); // bumped when the voice list arrives
  const cancelRef = useRef<(() => void) | null>(null);

  useEffect(() => {
    setSupported(speechSupported());
    primeVoices(() => setReady((n) => n + 1));
    try {
      const l = window.localStorage.getItem(LANG_KEY) as LangCode | null;
      if (l && LANGUAGES.some((x) => x.code === l)) setLang(l);
      const r = Number(window.localStorage.getItem(RATE_KEY));
      if (RATES.includes(r as (typeof RATES)[number])) setRate(r);
    } catch {
      /* preferences simply will not persist */
    }
    return () => stopSpeaking();
  }, []);

  // Only offer what the device can actually pronounce. `ready` re-runs this
  // once Chrome delivers its voice list, which is empty on first call.
  const offered = useMemo(() => {
    if (!supported) return LANGUAGES.slice(0, 1);
    const have = availableLangs(LANGUAGES.map((l) => l.code));
    const list = LANGUAGES.filter((l) => have.has(l.code));
    return list.length ? list : LANGUAGES.slice(0, 1);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [supported, ready]);

  // If the stored language has no voice on this machine, fall back rather than
  // leaving a selection that plays nothing.
  useEffect(() => {
    if (offered.length && !offered.some((l) => l.code === lang)) setLang(offered[0].code);
  }, [offered, lang]);

  useEffect(() => {
    if (!open) {
      cancelRef.current?.();
      cancelRef.current = null;
      setPlaying(null);
    }
  }, [open]);

  const play = useCallback(
    (t: Explainer, atRate = rate, inLang = lang) => {
      cancelRef.current?.();
      if (!speechSupported()) return;
      // Untranslated content is always spoken by an English voice — a Hindi
      // voice reading English words produces phonetic nonsense.
      const spokenLang = t.englishOnly ? "en" : inLang;
      const bcp47 =
        LANGUAGES.find((l) => l.code === spokenLang)?.bcp47 ?? "en-US";
      setPlaying(t.id);
      cancelRef.current = speak(
        t.text[spokenLang] ?? t.text.en,
        () => {
          setPlaying(null);
          cancelRef.current = null;
        },
        { rate: atRate, lang: bcp47 },
      );
    },
    [rate, lang],
  );

  const groups = [
    { key: "cluster", heading: "This cluster", items: clusterTopics },
    { key: "general", heading: clusterTopics.length ? "This page" : "", items: topics },
  ].filter((g) => g.items.length);

  const all = [...clusterTopics, ...topics];
  const activeTopic = all.find((x) => x.id === active) ?? null;
  const activeLang: LangCode = activeTopic?.englishOnly ? "en" : lang;
  const dir = LANGUAGES.find((l) => l.code === activeLang)?.dir ?? "ltr";

  function toggleTopic(t: Explainer) {
    if (active === t.id) {
      setActive(null);
      cancelRef.current?.();
      return;
    }
    setActive(t.id);
    play(t);
  }

  function changeLang(code: LangCode) {
    setLang(code);
    try {
      window.localStorage.setItem(LANG_KEY, code);
    } catch {
      /* ignore */
    }
    if (activeTopic) play(activeTopic, rate, code);
  }

  function changeRate(r: number) {
    setRate(r);
    try {
      window.localStorage.setItem(RATE_KEY, String(r));
    } catch {
      /* ignore */
    }
    // Rate cannot be changed mid-utterance, so restart at the new speed.
    if (activeTopic && playing === activeTopic.id) play(activeTopic, r);
  }

  return (
    <div className="rs-guide">
      {open && (
        <div className="rs-guide-panel" role="dialog" aria-label="Spoken explanations">
          <div className="rs-guide-head">
            <span className="rs-label" style={{ color: "var(--accent)" }}>
              Common questions
            </span>
            <button onClick={() => setOpen(false)} className="rs-focus rs-guide-x" aria-label="Close">
              ✕
            </button>
          </div>

          {supported && (
            <div className="rs-guide-controls">
              <select
                className="rs-focus"
                value={lang}
                onChange={(e) => changeLang(e.target.value as LangCode)}
                aria-label="Language"
              >
                {offered.map((l) => (
                  <option key={l.code} value={l.code}>
                    {l.label}
                  </option>
                ))}
              </select>
              <div className="rs-guide-rates" role="group" aria-label="Playback speed">
                {RATES.map((r) => (
                  <button
                    key={r}
                    onClick={() => changeRate(r)}
                    className="rs-focus"
                    data-on={rate === r}
                    aria-pressed={rate === r}
                  >
                    {r}×
                  </button>
                ))}
              </div>
            </div>
          )}

          {/* The question list holds its height; only the transcript scrolls,
              so every question stays one click away while an answer is open. */}
          <div className="rs-guide-groups">
            {groups.map((g) => (
              <div key={g.key}>
                {g.heading && <div className="rs-guide-group-head rs-label">{g.heading}</div>}
                <ul className="rs-guide-list">
                  {g.items.map((t) => (
                    <li key={t.id}>
                      <button
                        onClick={() => toggleTopic(t)}
                        className="rs-focus rs-guide-q"
                        data-active={active === t.id}
                        aria-expanded={active === t.id}
                      >
                        <span
                          className="rs-guide-icon"
                          data-playing={playing === t.id}
                          aria-hidden="true"
                        >
                          {playing === t.id ? "❚❚" : "▶"}
                        </span>
                        <span>{t.question[t.englishOnly ? "en" : lang] ?? t.question.en}</span>
                      </button>
                    </li>
                  ))}
                </ul>
              </div>
            ))}
          </div>

          {activeTopic && (
            <div className="rs-guide-body">
              <p dir={dir} lang={activeLang}>
                {activeTopic.text[activeLang] ?? activeTopic.text.en}
              </p>
              <div className="rs-guide-meta">
                <span>
                  {activeTopic.englishOnly
                    ? "Claude's case file · English only"
                    : "Written by the team · read by your browser"}
                </span>
                {supported ? (
                  <button
                    onClick={() =>
                      playing === activeTopic.id
                        ? cancelRef.current?.()
                        : play(activeTopic)
                    }
                    className="rs-focus rs-guide-replay"
                  >
                    {playing === activeTopic.id ? "stop" : "play again"}
                  </button>
                ) : (
                  <span style={{ color: "var(--text-faint)" }}>
                    no speech voice here — transcript only
                  </span>
                )}
              </div>
            </div>
          )}
        </div>
      )}

      <button
        onClick={() => setOpen((v) => !v)}
        className="rs-focus rs-guide-fab"
        aria-expanded={open}
        aria-label={open ? "Close explanations" : "Open spoken explanations"}
      >
        <span className="rs-guide-fab-dot" data-playing={Boolean(playing)} aria-hidden="true" />
        {open ? "Close" : label}
      </button>
    </div>
  );
}
