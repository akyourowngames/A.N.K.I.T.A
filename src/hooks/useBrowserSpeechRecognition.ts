"use client";

import { useCallback, useEffect, useRef, useState } from "react";

type SpeechAlternative = {
  transcript: string;
};

type SpeechResult = {
  isFinal: boolean;
  length: number;
  [index: number]: SpeechAlternative;
};

type SpeechResultList = {
  length: number;
  [index: number]: SpeechResult;
};

type SpeechRecognitionEventLike = {
  resultIndex: number;
  results: SpeechResultList;
};

type BrowserSpeechRecognition = {
  continuous: boolean;
  interimResults: boolean;
  lang: string;
  onresult: ((event: SpeechRecognitionEventLike) => void) | null;
  onerror: ((event: { error?: string }) => void) | null;
  onend: (() => void) | null;
  onnomatch: (() => void) | null;
  onsoundend: (() => void) | null;
  onspeechend: (() => void) | null;
  start: () => void;
  stop: () => void;
  abort: () => void;
};

type BrowserSpeechRecognitionConstructor = new () => BrowserSpeechRecognition;

type SpeechWindow = Window & {
  SpeechRecognition?: BrowserSpeechRecognitionConstructor;
  webkitSpeechRecognition?: BrowserSpeechRecognitionConstructor;
};

const NO_SPEECH_TIMEOUT_MS = 4200;
const SILENCE_SUBMIT_TIMEOUT_MS = 850;

export function useBrowserSpeechRecognition() {
  const recognitionRef = useRef<BrowserSpeechRecognition | null>(null);
  const shouldKeepListening = useRef(false);
  const committedTranscript = useRef("");
  const liveTranscript = useRef("");
  const noSpeechTimer = useRef<number | null>(null);
  const silenceTimer = useRef<number | null>(null);
  const [supported, setSupported] = useState(false);
  const [isListening, setIsListening] = useState(false);
  const [transcript, setTranscript] = useState("");
  const [finalTranscript, setFinalTranscript] = useState("");
  const [finalTurn, setFinalTurn] = useState(0);
  const [error, setError] = useState("");

  const clearTimers = useCallback(() => {
    if (noSpeechTimer.current !== null) {
      window.clearTimeout(noSpeechTimer.current);
      noSpeechTimer.current = null;
    }
    if (silenceTimer.current !== null) {
      window.clearTimeout(silenceTimer.current);
      silenceTimer.current = null;
    }
  }, []);

  const finishListening = useCallback(
    (text: string) => {
      clearTimers();
      shouldKeepListening.current = false;
      const cleanText = text.trim();
      const recognition = recognitionRef.current;
      recognitionRef.current = null;
      if (recognition) {
        try {
          recognition.stop();
        } catch {
          recognition.abort();
        }
      }
      setIsListening(false);
      if (!cleanText) {
        setError("No speech detected.");
        return;
      }
      setError("");
      setTranscript(cleanText);
      setFinalTranscript(cleanText);
      setFinalTurn((turn) => turn + 1);
    },
    [clearTimers]
  );

  const scheduleSilenceSubmit = useCallback(() => {
    if (silenceTimer.current !== null) {
      window.clearTimeout(silenceTimer.current);
    }
    silenceTimer.current = window.setTimeout(() => {
      finishListening(liveTranscript.current);
    }, SILENCE_SUBMIT_TIMEOUT_MS);
  }, [finishListening]);

  useEffect(() => {
    const speechWindow = window as SpeechWindow;
    setSupported(Boolean(speechWindow.SpeechRecognition ?? speechWindow.webkitSpeechRecognition));
    return () => {
      shouldKeepListening.current = false;
      clearTimers();
      recognitionRef.current?.abort();
    };
  }, [clearTimers]);

  const start = useCallback(() => {
    const speechWindow = window as SpeechWindow;
    const Recognition = speechWindow.SpeechRecognition ?? speechWindow.webkitSpeechRecognition;
    if (!Recognition) {
      setError("Browser speech recognition is not available here.");
      return;
    }

    shouldKeepListening.current = true;
    clearTimers();
    setError("");
    setTranscript("");
    setFinalTranscript("");
    committedTranscript.current = "";
    liveTranscript.current = "";

    const recognition = new Recognition();
    recognition.continuous = false;
    recognition.interimResults = true;
    recognition.lang = navigator.language || "en-US";
    noSpeechTimer.current = window.setTimeout(() => {
      finishListening("");
    }, NO_SPEECH_TIMEOUT_MS);
    recognition.onresult = (event) => {
      if (noSpeechTimer.current !== null) {
        window.clearTimeout(noSpeechTimer.current);
        noSpeechTimer.current = null;
      }
      let finalText = "";
      let interimText = "";
      for (let index = event.resultIndex; index < event.results.length; index += 1) {
        const result = event.results[index];
        if (!result || result.length === 0) {
          continue;
        }
        const text = result[0].transcript;
        if (result.isFinal) {
          finalText += text;
        } else {
          interimText += text;
        }
      }
      if (finalText.trim()) {
        committedTranscript.current = `${committedTranscript.current} ${finalText}`.trim();
      }
      const nextTranscript = `${committedTranscript.current} ${interimText}`.trim();
      if (nextTranscript) {
        liveTranscript.current = nextTranscript;
        setTranscript(nextTranscript);
      }
      if (finalText.trim()) {
        finishListening(committedTranscript.current);
      } else if (nextTranscript) {
        scheduleSilenceSubmit();
      }
    };
    recognition.onerror = (event) => {
      clearTimers();
      const errorText = event.error === "no-speech" ? "No speech detected." : event.error ? `Voice input failed: ${event.error}` : "Voice input failed.";
      setError(errorText);
      shouldKeepListening.current = false;
      setIsListening(false);
    };
    recognition.onnomatch = () => finishListening("");
    recognition.onsoundend = scheduleSilenceSubmit;
    recognition.onspeechend = scheduleSilenceSubmit;
    recognition.onend = () => {
      if (!shouldKeepListening.current) {
        setIsListening(false);
        return;
      }
      finishListening(liveTranscript.current);
    };
    recognitionRef.current = recognition;
    try {
      recognition.start();
      setIsListening(true);
    } catch {
      setError("Voice input could not start.");
      setIsListening(false);
    }
  }, [clearTimers, finishListening, scheduleSilenceSubmit]);

  const stop = useCallback(() => {
    finishListening(liveTranscript.current);
  }, [finishListening]);

  return {
    supported,
    isListening,
    transcript,
    finalTranscript,
    finalTurn,
    error,
    start,
    stop
  };
}
