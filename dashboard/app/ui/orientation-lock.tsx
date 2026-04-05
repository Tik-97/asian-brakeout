"use client";

import { useEffect, useState } from "react";

const CHUNK_RELOAD_KEY = "dead-market-chunk-reload";

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

  useEffect(() => {
    const reloadOnChunkFailure = () => {
      const alreadyRetried = window.sessionStorage.getItem(CHUNK_RELOAD_KEY);
      if (alreadyRetried === "1") {
        return;
      }
      window.sessionStorage.setItem(CHUNK_RELOAD_KEY, "1");
      window.location.reload();
    };

    const clearRetryFlag = () => {
      window.sessionStorage.removeItem(CHUNK_RELOAD_KEY);
    };

    const onError = (event: ErrorEvent) => {
      const message = String(event.message ?? "");
      if (message.includes("ChunkLoadError") || message.includes("Loading chunk")) {
        reloadOnChunkFailure();
      }
    };

    const onUnhandledRejection = (event: PromiseRejectionEvent) => {
      const reasonText =
        typeof event.reason === "string"
          ? event.reason
          : String(event.reason?.message ?? event.reason ?? "");
      if (reasonText.includes("ChunkLoadError") || reasonText.includes("Loading chunk")) {
        reloadOnChunkFailure();
      }
    };

    clearRetryFlag();
    window.addEventListener("error", onError);
    window.addEventListener("unhandledrejection", onUnhandledRejection);

    return () => {
      window.removeEventListener("error", onError);
      window.removeEventListener("unhandledrejection", onUnhandledRejection);
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
