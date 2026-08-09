import { useEffect, useRef } from "react";
import { normalizeMedicalMonitoringScrollTop } from "./medicalMonitoringScrollState.mjs";

function schedule(callback, delay = 0) {
  if (typeof window === "undefined") return 0;
  if (delay > 0) return window.setTimeout(callback, delay);
  if (typeof window.requestAnimationFrame === "function") {
    return window.requestAnimationFrame(callback);
  }
  return window.setTimeout(callback, 0);
}

function cancel(handle, delay = 0) {
  if (!handle || typeof window === "undefined") return;
  if (delay > 0) {
    window.clearTimeout(handle);
    return;
  }
  if (typeof window.cancelAnimationFrame === "function") {
    window.cancelAnimationFrame(handle);
  } else {
    window.clearTimeout(handle);
  }
}

/**
 * Persist only the browser's desktop scroll position for the monitoring
 * checklist. It never writes risk, batch, source or medical state.
 */
export function useMedicalMonitoringScrollRestoration({
  enabled = false,
  scrollTop = 0,
  restoreKey = "",
  onScrollTopChange,
}) {
  const latestScrollTop = useRef(normalizeMedicalMonitoringScrollTop(scrollTop));
  const callbackRef = useRef(onScrollTopChange);
  const pendingNotify = useRef(0);
  const pendingRestore = useRef(0);
  callbackRef.current = onScrollTopChange;

  useEffect(() => {
    latestScrollTop.current = normalizeMedicalMonitoringScrollTop(scrollTop);
  }, [scrollTop]);

  useEffect(() => {
    if (!enabled || typeof window === "undefined") return undefined;
    const target = normalizeMedicalMonitoringScrollTop(scrollTop);
    const restore = () => {
      pendingRestore.current = 0;
      latestScrollTop.current = target;
      if (typeof window.scrollTo === "function") {
        window.scrollTo({ top: target, left: 0, behavior: "auto" });
      }
    };
    restore();
    pendingRestore.current = schedule(restore);
    return () => {
      cancel(pendingRestore.current);
      pendingRestore.current = 0;
    };
  }, [enabled, restoreKey]);

  useEffect(() => {
    if (!enabled || typeof window === "undefined") return undefined;
    const notify = () => {
      pendingNotify.current = 0;
      const next = normalizeMedicalMonitoringScrollTop(window.scrollY);
      if (next === latestScrollTop.current) return;
      latestScrollTop.current = next;
      callbackRef.current?.(next);
    };
    const handleScroll = () => {
      if (pendingNotify.current) return;
      pendingNotify.current = schedule(notify, 120);
    };
    window.addEventListener("scroll", handleScroll, { passive: true });
    return () => {
      window.removeEventListener("scroll", handleScroll);
      cancel(pendingNotify.current, 120);
      pendingNotify.current = 0;
    };
  }, [enabled]);
}
