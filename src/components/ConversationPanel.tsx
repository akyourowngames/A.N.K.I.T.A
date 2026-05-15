"use client";

import { Bot, CheckCircle2, Copy, ThumbsDown, ThumbsUp, UserRound } from "lucide-react";
import { motion } from "framer-motion";
import type { ReactNode } from "react";

export function ConversationPanel({
  userText,
  reply,
  isStreaming,
  error
}: {
  userText: string;
  reply: string;
  isStreaming: boolean;
  error: string;
}) {
  return (
    <motion.aside
      className="conversation-panel"
      initial={{ opacity: 0, x: 32, scale: 0.985, filter: "blur(12px)" }}
      animate={{ opacity: 1, x: 0, scale: 1, filter: "blur(0px)" }}
      exit={{ opacity: 0, x: 28, scale: 0.985, filter: "blur(10px)" }}
      transition={{ duration: 0.48, ease: [0.22, 1, 0.36, 1] }}
    >
      <div className="conversation-date">Today</div>

      <div className="conversation-scroll">
        <MessageBlock
          avatar={<UserRound size={19} strokeWidth={1.6} />}
          name="You"
          text={userText || "Listening..."}
          muted={false}
        />

        <MessageBlock
          avatar={<Bot size={19} strokeWidth={1.6} />}
          name="JARVIS"
          text={error || reply || (isStreaming ? "Thinking..." : "")}
          muted={!reply && !error}
          streaming={isStreaming && !error}
        />

      </div>

      <div className="conversation-actions" aria-label="Conversation actions">
        <button type="button" aria-label="Copy response">
          <Copy size={20} />
        </button>
        <button type="button" aria-label="Helpful">
          <ThumbsUp size={20} />
        </button>
        <button type="button" aria-label="Not helpful">
          <ThumbsDown size={20} />
        </button>
        <span>{isStreaming ? "Streaming..." : "Was this helpful?"}</span>
      </div>
    </motion.aside>
  );
}

function MessageBlock({
  avatar,
  name,
  text,
  muted,
  streaming = false
}: {
  avatar: ReactNode;
  name: string;
  text: string;
  muted: boolean;
  streaming?: boolean;
}) {
  return (
    <article className="conversation-message">
      <div className="conversation-avatar" aria-hidden="true">
        {avatar}
      </div>
      <div className="conversation-copy">
        <div className="conversation-speaker">
          <strong>{name}</strong>
          <span>Now</span>
          {streaming ? <CheckCircle2 size={15} strokeWidth={1.7} /> : null}
        </div>
        <p className={muted ? "muted" : ""}>{text}</p>
      </div>
    </article>
  );
}
