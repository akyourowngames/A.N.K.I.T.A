import type { SubagentActivity } from '../../../shared/subagent-state.mjs';
import { SUBAGENT_PARENT_TARGET, SUBAGENT_MESSAGE_LABELS } from '../../../shared/subagent-state.mjs';

export function SubagentMessages({ messages = [] }: { messages?: SubagentActivity['messages'] }) {
  if (!messages.length) return null;
  return <section className="subagent-messages subagent-panel-section" aria-label="Agent messages">
    <div className="subagent-panel-section-head"><span>Messages</span><small>{messages.length}</small></div>
    {messages.map(message => <div key={message.messageId}>
      <span className="tool-section-label">{message.from === SUBAGENT_PARENT_TARGET ? SUBAGENT_MESSAGE_LABELS.toChild : SUBAGENT_MESSAGE_LABELS.toParent}</span>
      <pre className="subagent-message-body">{message.message}</pre>
    </div>)}
  </section>;
}
