"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { streamAssistantReply } from "../lib/assistantClient";

export type AssistantPhase = "idle" | "thinking" | "responding" | "error";

const SESSION_STORAGE_KEY = "jarvis-web-session";

export function useAssistantChat() {
  const [sessionId, setSessionId] = useState("");
  const [input, setInput] = useState("");
  const [reply, setReply] = useState("");
  const [lastUserText, setLastUserText] = useState("");
  const [phase, setPhase] = useState<AssistantPhase>("idle");
  const [error, setError] = useState("");

  useEffect(() => {
    const stored = window.localStorage.getItem(SESSION_STORAGE_KEY);
    if (stored) {
      setSessionId(stored);
    }
  }, []);

  const submit = useCallback(
    async (overrideText?: string) => {
      const text = (overrideText ?? input).trim();
      if (!text || phase === "thinking" || phase === "responding") {
        return;
      }
      setInput("");
      setReply("");
      setError("");
      setLastUserText(text);
      setPhase("thinking");
      let streamedReply = "";

      await streamAssistantReply(text, sessionId, {
        onToken(content) {
          if (!content) {
            return;
          }
          streamedReply += content;
          setReply(streamedReply);
          setPhase("responding");
        },
        async onDone(nextSessionId, finalReply) {
          if (nextSessionId) {
            setSessionId(nextSessionId);
            window.localStorage.setItem(SESSION_STORAGE_KEY, nextSessionId);
          }
          setReply(streamedReply || finalReply);
          setPhase("idle");
        },
        onError(message) {
          setError(message);
          setPhase("error");
        }
      });
    },
    [input, phase, sessionId]
  );

  const resetError = useCallback(() => {
    if (phase === "error") {
      setPhase("idle");
      setError("");
    }
  }, [phase]);

  return useMemo(
    () => ({
      input,
      setInput,
      reply,
      lastUserText,
      phase,
      error,
      isStreaming: phase === "thinking" || phase === "responding",
      submit,
      resetError
    }),
    [error, input, lastUserText, phase, reply, resetError, submit]
  );
}
