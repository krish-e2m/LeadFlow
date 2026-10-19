"use client";

import React, { useEffect, useRef, useState } from "react";
import { useReducedMotion } from "motion/react";

interface CountUpProps {
  value: number;
  format?: (n: number) => string;
  durationMs?: number;
}

/** Animates from its previous value to `value` with an eased count-up, so a KPI refresh or a
 * filter change reads as a number moving rather than a flicker. Jumps straight to the final
 * value under prefers-reduced-motion. Plain requestAnimationFrame — no chart/number library. */
export const CountUp: React.FC<CountUpProps> = ({ value, format = (n) => String(n), durationMs = 600 }) => {
  const reduceMotion = useReducedMotion();
  const [display, setDisplay] = useState(value);
  const fromRef = useRef(value);
  const rafRef = useRef<number | null>(null);

  useEffect(() => {
    if (reduceMotion) {
      setDisplay(value);
      fromRef.current = value;
      return;
    }
    const from = fromRef.current;
    const to = value;
    if (from === to) return;

    const start = performance.now();
    const easeOutExpo = (t: number) => (t >= 1 ? 1 : 1 - Math.pow(2, -10 * t));

    const step = (now: number) => {
      const t = Math.min(1, (now - start) / durationMs);
      setDisplay(Math.round(from + (to - from) * easeOutExpo(t)));
      if (t < 1) {
        rafRef.current = requestAnimationFrame(step);
      } else {
        fromRef.current = to;
      }
    };
    rafRef.current = requestAnimationFrame(step);
    return () => {
      if (rafRef.current !== null) cancelAnimationFrame(rafRef.current);
    };
    // Only the target value should restart the animation; `from` is read via the ref on purpose.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [value, durationMs, reduceMotion]);

  return <>{format(display)}</>;
};
