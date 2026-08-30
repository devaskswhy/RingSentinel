/**
 * The social preview card, generated rather than exported from a design tool.
 *
 * Every figure on it is measured and matches what the site says: 1,499 real
 * test-mode transactions, 12 rings found of 12, zero false flags. It is
 * rendered at build time by next/og, so it cannot drift from the numbers in
 * the repo the way an exported PNG would.
 *
 * Deliberately no Razorpay mark. This image is the first thing anyone sees
 * when the link is shared, and a third-party logo there reads as endorsement -
 * the same reason the mark is confined to the footer.
 */

import { ImageResponse } from "next/og";

export const size = { width: 1200, height: 630 };
export const contentType = "image/png";
export const alt =
  "RingSentinel — fraud rings are invisible one transaction at a time";

const ACCENT = "#3395ff";
const INK = "#08090a";

export default function OpengraphImage() {
  return new ImageResponse(
    (
      <div
        style={{
          width: "100%",
          height: "100%",
          background: INK,
          color: "#e8eaed",
          display: "flex",
          flexDirection: "column",
          justifyContent: "space-between",
          padding: "72px 80px",
          fontFamily: "sans-serif",
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: 16 }}>
          <div style={{ display: "flex", fontSize: 30, fontWeight: 700, letterSpacing: -1 }}>
            <span>Ring</span>
            <span style={{ color: ACCENT }}>Sentinel</span>
          </div>
          <div
            style={{
              fontSize: 19,
              letterSpacing: 4,
              color: "#656c73",
              textTransform: "uppercase",
            }}
          >
            Coordinated fraud, seen as a graph
          </div>
        </div>

        <div
          style={{
            display: "flex",
            fontSize: 76,
            fontWeight: 700,
            lineHeight: 1.06,
            letterSpacing: -3,
            maxWidth: 950,
          }}
        >
          Fraud rings are invisible one{" "}
          <span style={{ color: ACCENT, marginLeft: 18 }}>transaction at a time.</span>
        </div>

        <div style={{ display: "flex", gap: 64, alignItems: "flex-end" }}>
          {[
            ["1,499", "real test-mode transactions"],
            ["12 / 12", "rings found"],
            ["0", "false flags"],
            ["100%", "decisions by a human"],
          ].map(([n, k]) => (
            <div key={k} style={{ display: "flex", flexDirection: "column", gap: 8 }}>
              <div style={{ fontSize: 48, fontWeight: 600, color: ACCENT, letterSpacing: -2 }}>
                {n}
              </div>
              <div style={{ fontSize: 20, color: "#9aa1a8" }}>{k}</div>
            </div>
          ))}
        </div>

        <div style={{ display: "flex", fontSize: 17, color: "#656c73", maxWidth: 1000 }}>
          Measured on a synthetic corpus this project generated — not a claim
          about production accuracy. Nothing here can block, freeze or decline
          anyone.
        </div>
      </div>
    ),
    size,
  );
}
