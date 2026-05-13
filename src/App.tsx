"use client";

import { AnimatePresence, motion } from "framer-motion";
import { useEffect, useMemo } from "react";
import { ConversationPanel } from "./components/ConversationPanel";
import { InputBar } from "./components/InputBar";
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
  const setAssistantInput = assistant.setInput;
  const conversationActive = Boolean(assistant.lastUserText || assistant.reply || assistant.isStreaming);

  useEffect(() => {
    if (speech.isListening && speech.transcript) {
      setAssistantInput(speech.transcript);
    }
  }, [setAssistantInput, speech.isListening, speech.transcript]);

  const status = useMemo(() => {
    if (speech.isListening) {
      return {
        title: "Listening...",
        detail: assistant.input ? `Transcribing: ${assistant.input}` : "Speak now. I am transcribing in the browser."
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
  }, [assistant.error, assistant.input, assistant.phase, assistant.reply, speech.error, speech.isListening]);

  const inputProps = {
    value: assistant.input,
    onChange: assistant.setInput,
    onSubmit: assistant.submit,
    onVoiceToggle: speech.isListening ? speech.stop : speech.start,
    voiceActive: speech.isListening,
    voiceSupported: speech.supported,
    disabled: assistant.isStreaming,
    placeholder: assistant.isStreaming ? "Jarvis is responding..." : "Ask anything..."
  };

  return (
    <main className="app-frame min-h-screen overflow-hidden text-primaryText">
      <div className="hidden h-full md:block">
        <Sidebar />

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
      </div>

      <div className="block h-full md:hidden">
        <MobileLayout statusTitle={status.title} statusDetail={status.detail} inputProps={inputProps} />
      </div>
    </main>
  );
}
