"use client";

import { motion } from "framer-motion";

export function Orb({ variant = "desktop" }: { variant?: "desktop" | "mobile" }) {
  return (
    <motion.div
      className={variant === "mobile" ? "orb-shell mobile-orb-shell" : "orb-shell"}
      animate={{ scale: [1, 1.025, 1] }}
      transition={{ duration: 5.8, repeat: Infinity, ease: "easeInOut" }}
      aria-label="Listening assistant orb"
    >
      <div className="orb-glow" aria-hidden="true" />
      <motion.img
        src="/assets/orb.gif"
        alt=""
        className="orb-asset"
        draggable={false}
        animate={{ opacity: [0.9, 1, 0.94] }}
        transition={{ duration: 4.8, repeat: Infinity, ease: "easeInOut" }}
      />
      <div className="orb-stars" aria-hidden="true" />
      <div className="orb-core" aria-hidden="true" />
      <div className="orb-rim" aria-hidden="true" />
    </motion.div>
  );
}
