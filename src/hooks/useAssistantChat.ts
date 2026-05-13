"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { fetchEntertainmentContext, streamAssistantReply, type EntertainmentContext } from "../lib/assistantClient";

export type AssistantPhase = "idle" | "thinking" | "responding" | "error";

const SESSION_STORAGE_KEY = "jarvis-web-session";

export function useAssistantChat() {
  const [sessionId, setSessionId] = useState("");
  const [input, setInput] = useState("");
  const [reply, setReply] = useState("");
  const [lastUserText, setLastUserText] = useState("");
  const [phase, setPhase] = useState<AssistantPhase>("idle");
  const [error, setError] = useState("");
  const [entertainmentContext, setEntertainmentContext] = useState<EntertainmentContext | null>(null);

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
      const submittedAt = Date.now();
      setInput("");
      setReply("");
      setError("");
      setEntertainmentContext(null);
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
          try {
            const context = await fetchEntertainmentContext();
            setEntertainmentContext(shouldShowEntertainmentContext(context, submittedAt) ? context : null);
          } catch {
            setEntertainmentContext(null);
          }
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
      entertainmentContext,
      isStreaming: phase === "thinking" || phase === "responding",
      submit,
      resetError
    }),
    [entertainmentContext, error, input, lastUserText, phase, reply, resetError, submit]
  );
}

function shouldShowEntertainmentContext(context: EntertainmentContext | null, submittedAt: number) {
  if (!context?.lastSearchAt) {
    return false;
  }
  const results = context.lastSearchResults ?? [];
  if (results.length === 0) {
    return false;
  }
  const updatedAt = Date.parse(context.lastSearchAt);
  if (!Number.isFinite(updatedAt)) {
    return false;
  }
  return updatedAt >= submittedAt - 1000;
}
