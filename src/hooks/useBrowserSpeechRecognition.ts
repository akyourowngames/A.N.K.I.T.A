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
  start: () => void;
  stop: () => void;
  abort: () => void;
};

type BrowserSpeechRecognitionConstructor = new () => BrowserSpeechRecognition;

type SpeechWindow = Window & {
  SpeechRecognition?: BrowserSpeechRecognitionConstructor;
  webkitSpeechRecognition?: BrowserSpeechRecognitionConstructor;
};

export function useBrowserSpeechRecognition() {
  const recognitionRef = useRef<BrowserSpeechRecognition | null>(null);
  const shouldKeepListening = useRef(false);
  const committedTranscript = useRef("");
  const [supported, setSupported] = useState(false);
  const [isListening, setIsListening] = useState(false);
  const [transcript, setTranscript] = useState("");
  const [error, setError] = useState("");

  useEffect(() => {
    const speechWindow = window as SpeechWindow;
    setSupported(Boolean(speechWindow.SpeechRecognition ?? speechWindow.webkitSpeechRecognition));
    return () => {
      shouldKeepListening.current = false;
      recognitionRef.current?.abort();
    };
  }, []);

  const start = useCallback(() => {
    const speechWindow = window as SpeechWindow;
    const Recognition = speechWindow.SpeechRecognition ?? speechWindow.webkitSpeechRecognition;
    if (!Recognition) {
      setError("Browser speech recognition is not available here.");
      return;
    }

    shouldKeepListening.current = true;
    setError("");
    setTranscript("");
    committedTranscript.current = "";

    const recognition = new Recognition();
    recognition.continuous = true;
    recognition.interimResults = true;
    recognition.lang = navigator.language || "en-US";
    recognition.onresult = (event) => {
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
        setTranscript(nextTranscript);
      }
    };
    recognition.onerror = (event) => {
      setError(event.error ? `Voice input failed: ${event.error}` : "Voice input failed.");
      shouldKeepListening.current = false;
      setIsListening(false);
    };
    recognition.onend = () => {
      if (!shouldKeepListening.current) {
        setIsListening(false);
        return;
      }
      try {
        recognition.start();
      } catch {
        setIsListening(false);
      }
    };
    recognitionRef.current = recognition;
    try {
      recognition.start();
      setIsListening(true);
    } catch {
      setError("Voice input could not start.");
      setIsListening(false);
    }
  }, []);

  const stop = useCallback(() => {
    shouldKeepListening.current = false;
    recognitionRef.current?.stop();
    setIsListening(false);
  }, []);

  return {
    supported,
    isListening,
    transcript,
    error,
    start,
    stop
  };
}
