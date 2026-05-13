"use client";

import { motion } from "framer-motion";
import { AudioLines } from "lucide-react";
import type { AssistantInputProps } from "./InputBar";
import { MobileHeader } from "./MobileHeader";
import { MobileInputBar } from "./MobileInputBar";
import { MobileQuickActions } from "./MobileQuickActions";
import { Orb } from "./Orb";

export function MobileLayout({
  statusTitle,
  statusDetail,
  inputProps
}: {
  statusTitle: string;
  statusDetail: string;
  inputProps: AssistantInputProps;
}) {
  return (
    <section className="mobile-layout" aria-label="Aurora mobile assistant">
      <MobileHeader />

      <motion.div
        className="mobile-orb-region"
        initial={{ opacity: 0, y: 10 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.7, ease: [0.22, 1, 0.36, 1] }}
      >
        <Orb variant="mobile" />
      </motion.div>

      <motion.div
        className="mobile-listening"
        initial={{ opacity: 0, y: 8 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.65, delay: 0.12, ease: [0.22, 1, 0.36, 1] }}
      >
        <AudioLines size={34} strokeWidth={1.55} />
        <h1>{statusTitle}</h1>
        <p>{statusDetail}</p>
      </motion.div>

      <MobileInputBar {...inputProps} />
      <MobileQuickActions />
      <div className="mobile-home-indicator" aria-hidden="true" />
    </section>
  );
}
