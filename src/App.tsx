"use client";

import { motion } from "framer-motion";
import { InputBar } from "./components/InputBar";
import { Orb } from "./components/Orb";
import { RightPanels } from "./components/RightPanels";
import { Sidebar } from "./components/Sidebar";
import { StatusHeader } from "./components/StatusHeader";

export default function App() {
  return (
    <main className="app-frame min-h-screen overflow-hidden text-primaryText">
      <Sidebar />

      <motion.section
        className="center-stage"
        initial={{ opacity: 0, y: 10 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.75, ease: [0.22, 1, 0.36, 1] }}
      >
        <StatusHeader />
        <Orb />
        <InputBar />
      </motion.section>

      <RightPanels />
    </main>
  );
}
