"use client";

/**
 * The help card: a short list of the questions people actually ask, each
 * answered aloud.
 *
 * Not a chatbot, on purpose. A chat box on a fraud tool invites open-ended
 * questions it would then answer from a model with no grounding in this
 * codebase — and the first confidently wrong answer about what the detector
 * does would undo everything the rest of the site is careful about. A fixed set
 * of checked answers cannot hallucinate.
 *
 * The transcript is always visible, never hidden behind the audio. Someone on a
 * silent laptop, someone deaf, and someone who wants to verify a number against
 * the repo all need the words on screen, and speech is the addition rather than
 * the medium.
 */

import { useEffect, useRef, useState } from "react";
import type { Explainer } from "@/lib/explainers";
import { primeVoices, speak, speechSupported, stopSpeaking } from "@/lib/speech";

export default function VoiceGuide({
  topics,
  label = "Ask",
}: {
  topics: Explainer[];
  label?: string;
}) {
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState<string | null>(null);
  const [playing, setPlaying] = useState<string | null>(null);
  const [supported, setSupported] = useState(true);
  const cancelRef = useRef<(() => void) | null>(null);

  useEffect(() => {
    setSupported(speechSupported());
    primeVoices();
    return () => stopSpeaking();
  }, []);

  // Speech must not carry on after the panel is closed — an invisible voice
  // still talking is the single most annoying thing this could do.
  useEffect(() => {
    if (!open) {
      cancelRef.current?.();
      cancelRef.current = null;
      setPlaying(null);
    }
  }, [open]);

  function toggleTopic(t: Explainer) {
    const isOpen = active === t.id;
    setActive(isOpen ? null : t.id);
    if (isOpen) {
      cancelRef.current?.();
      return;
    }
    play(t);
  }

  function play(t: Explainer) {
    cancelRef.current?.();
    if (!speechSupported()) return;
    setPlaying(t.id);
    cancelRef.current = speak(t.text, () => {
      setPlaying(null);
      cancelRef.current = null;
    });
  }

  const activeTopic = topics.find((x) => x.id === active) ?? null;

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

          {/* The question list stays put. It used to sit above the expanded
              transcript inside one scroll region, so opening a long answer
              pushed every other question out of view and the panel had to be
              closed and reopened to ask a second one. */}
          <ul className="rs-guide-list">
            {topics.map((t) => {
              const isActive = active === t.id;
              const isPlaying = playing === t.id;
              return (
                <li key={t.id}>
                  <button
                    onClick={() => toggleTopic(t)}
                    className="rs-focus rs-guide-q"
                    data-active={isActive}
                    aria-expanded={isActive}
                  >
                    <span className="rs-guide-icon" data-playing={isPlaying} aria-hidden="true">
                      {isPlaying ? "❚❚" : "▶"}
                    </span>
                    <span>{t.question}</span>
                  </button>
                </li>
              );
            })}
          </ul>

          {activeTopic && (
            <div className="rs-guide-body">
              <p>{activeTopic.text}</p>
              <div className="rs-guide-meta">
                <span>{activeTopic.source}</span>
                {supported ? (
                  <button
                    onClick={() =>
                      playing === activeTopic.id ? cancelRef.current?.() : play(activeTopic)
                    }
                    className="rs-focus rs-guide-replay"
                  >
                    {playing === activeTopic.id ? "stop" : "play again"}
                  </button>
                ) : (
                  <span style={{ color: "var(--text-faint)" }}>
                    no speech voice on this device — transcript only
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
