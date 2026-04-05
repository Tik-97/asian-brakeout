"use client";

import { useEffect, useState } from "react";

function shouldBlockLandscape() {
  if (typeof window === "undefined") {
    return false;
  }

  const isLandscape = window.innerWidth > window.innerHeight;
  const isTouchDevice = window.matchMedia("(hover: none) and (pointer: coarse)").matches;

  return isLandscape && isTouchDevice;
}

export function OrientationLock() {
  const [blocked, setBlocked] = useState(false);

  useEffect(() => {
    const sync = () => setBlocked(shouldBlockLandscape());

    sync();
    window.addEventListener("resize", sync);
    window.addEventListener("orientationchange", sync);

    return () => {
      window.removeEventListener("resize", sync);
      window.removeEventListener("orientationchange", sync);
    };
  }, []);

  return (
    <div
      className={`orientation-lock${blocked ? " active" : ""}`}
      aria-live="polite"
      aria-label="Rotate device notice"
    >
      <div className="orientation-lock-card">
        <span className="orientation-lock-icon">↻</span>
        <h2>Keep Screen Vertical</h2>
        <p>Please rotate your phone back to portrait mode to view the trading house.</p>
      </div>
    </div>
  );
}
