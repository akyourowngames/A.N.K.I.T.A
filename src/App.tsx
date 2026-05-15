"use client";

import { AnimatePresence, motion } from "framer-motion";
import { useEffect, useMemo, useRef, useState } from "react";
import { ConversationPanel } from "./components/ConversationPanel";
import { InputBar } from "./components/InputBar";
import { MemoryGraphView } from "./components/MemoryGraphView";
import { MobileLayout } from "./components/MobileLayout";
import { Orb } from "./components/Orb";
import { RightPanels } from "./components/RightPanels";
import { Sidebar } from "./components/Sidebar";
import { StatusHeader } from "./components/StatusHeader";
import { useAssistantChat } from "./hooks/useAssistantChat";
import { useBrowserSpeechRecognition } from "./hooks/useBrowserSpeechRecognition";

export default function App() {
  const assistant = useAssistantChat();
  const speech = useBrowserSpeechRecognition();
  const [activeView, setActiveView] = useState<"chat" | "memory">("chat");
  const submittedSpeechTurn = useRef(0);
  const conversationActive = Boolean(assistant.lastUserText || assistant.reply || assistant.isStreaming);

  useEffect(() => {
    if (!speech.finalTurn || submittedSpeechTurn.current === speech.finalTurn) {
      return;
    }
    submittedSpeechTurn.current = speech.finalTurn;
    if (speech.finalTranscript) {
      assistant.submit(speech.finalTranscript);
    }
  }, [assistant, speech.finalTranscript, speech.finalTurn]);

  const status = useMemo(() => {
    if (speech.isListening) {
      return {
        title: "Listening...",
        detail: speech.transcript ? `Transcribing: ${speech.transcript}` : "Speak now. I will send it when you pause."
      };
    }
    if (assistant.phase === "thinking") {
      return {
        title: "Thinking...",
        detail: "Opening conversation."
      };
    }
    if (assistant.phase === "responding") {
      return {
        title: "Responding...",
        detail: "Streaming in the chat window."
      };
    }
    if (assistant.phase === "error") {
      return {
        title: "Connection issue",
        detail: assistant.error || speech.error || "The assistant server is not reachable."
      };
    }
    if (assistant.reply) {
      return {
        title: "Ready.",
        detail: "Response is ready."
      };
    }
    if (speech.error) {
      return {
        title: "Listening...",
        detail: speech.error
      };
    }
    return {
      title: "Listening...",
      detail: "Ready when you are."
    };
  }, [assistant.error, assistant.phase, assistant.reply, speech.error, speech.isListening, speech.transcript]);

  const inputProps = {
    value: assistant.input,
    onChange: assistant.setInput,
    onSubmit: assistant.submit,
    onVoiceToggle: speech.isListening ? speech.stop : speech.start,
    voiceActive: speech.isListening,
    voiceSupported: speech.supported,
    disabled: assistant.isStreaming,
    placeholder: assistant.isStreaming ? "Jarvis is responding..." : speech.isListening ? "Listening..." : "Ask anything..."
  };

  return (
    <main className="app-frame min-h-screen overflow-hidden text-primaryText">
      <div className="hidden h-full md:block">
        <Sidebar activeView={activeView} onViewChange={setActiveView} />

        {activeView === "memory" ? (
          <MemoryGraphView />
        ) : (
          <>
            <motion.section
              className="center-stage"
              initial={{ opacity: 0, y: 10 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.75, ease: [0.22, 1, 0.36, 1] }}
            >
              <StatusHeader title={status.title} detail={status.detail} />
              <Orb />
              <InputBar {...inputProps} />
            </motion.section>

            <AnimatePresence mode="wait">
              {conversationActive ? (
                <ConversationPanel
                  key="conversation"
                  userText={assistant.lastUserText}
                  reply={assistant.reply}
                  isStreaming={assistant.isStreaming}
                  error={assistant.error}
                />
              ) : (
                <RightPanels key="cards" />
              )}
            </AnimatePresence>
          </>
        )}
      </div>

      <div className="block h-full md:hidden">
        <MobileLayout statusTitle={status.title} statusDetail={status.detail} inputProps={inputProps} />
      </div>
    </main>
  );
}
