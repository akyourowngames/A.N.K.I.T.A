import { formatToolResult, toolResultText } from './mcp-client.mjs';

export const MAX_MCP_IMAGES_PER_TURN = 6; // Images/request; keeps repeated desktop captures inside the existing context budget.
export const MAX_MCP_IMAGES_PER_TOOL_RESULT = 6; // Images/one native MCP result; later screenshots are separate verification observations.
export const MAX_MCP_IMAGE_BYTES = 8 * 1024 * 1024; // Decoded bytes/image; permits a desktop PNG while bounding untrusted MCP data.
const MCP_IMAGE_TYPES = new Set(['image/png', 'image/jpeg', 'image/webp', 'image/gif']); // OpenAI-compatible vision wire formats.
const BASE64_IMAGE_DATA = /^[A-Za-z0-9+/]+={0,2}$/; // MCP image blocks carry base64, never executable or remote content.
const TEXT_ONLY_IMAGE_NOTE = '[Image omitted for this text-only model. Visual state is unavailable; use accessibility observations.]';
const IMAGE_CONTENT_TYPE = 'image_url'; // Existing OpenAI-compatible image message discriminator.
const TEXT_CONTENT_TYPE = 'text'; // Existing OpenAI-compatible text message discriminator.
const BASE64_INPUT_BYTES = 3; // Base64 encodes groups of three input bytes.
const BASE64_OUTPUT_CHARS = 4; // Each input group produces four characters, including padding.

/** The same data bounds apply to API image projection and native MCP publication. */
export function validMcpImage(part) {
  return MCP_IMAGE_TYPES.has(part.mimeType) && typeof part.data === 'string' &&
    part.data.length <= Math.ceil(MAX_MCP_IMAGE_BYTES / BASE64_INPUT_BYTES) * BASE64_OUTPUT_CHARS &&
    BASE64_IMAGE_DATA.test(part.data) && Buffer.byteLength(part.data, 'base64') <= MAX_MCP_IMAGE_BYTES;
}

/** Capabilities belong to the receiving model, including a tool-model handoff or fallback. Keep original history intact. */
export function messagesForModel(messages, vision) {
  if (vision !== false) return messages;
  return messages.map(message => Array.isArray(message.content)
    ? { ...message, content: message.content.map(part => part?.type === IMAGE_CONTENT_TYPE ? { type: TEXT_CONTENT_TYPE, text: TEXT_ONLY_IMAGE_NOTE } : part) }
    : message);
}

/** Keep the tool wire text-only; attach images using ANKITA's existing user-image format. */
export function attachMcpImages(result, { messages, callId, toolName, vision, remaining = MAX_MCP_IMAGES_PER_TURN } = {}) {
  const raw = result?.raw ?? result; // McpClient preserves provider content in its raw envelope.
  const isError = Boolean(result?.isError || raw?.isError);
  const text = formatToolResult({ isError, text: result?.text ?? toolResultText(raw) });
  if (isError) return { text, attached: 0 };
  const images = (Array.isArray(raw?.content) ? raw.content : []).filter(part => part?.type === 'image');
  if (!images.length) return { text, attached: 0 };
  if (vision === false) return { text: `${text}\nImages omitted: this model is text-only. Use accessibility observations; visual state is unverified.`, attached: 0 };
  const request = messages?.findLast(message => message.role === 'user');
  if (!request) return { text: `${text}\nImages could not be attached without a user request; visual state is unverified.`, attached: 0 };
  const parts = []; let omitted = 0;
  for (const part of images) {
    if (!validMcpImage(part) || parts.length >= remaining) { omitted++; continue; }
    parts.push({ type: IMAGE_CONTENT_TYPE, image_url: { url: `data:${part.mimeType};base64,${part.data}` } });
  }
  if (parts.length) {
    const content = Array.isArray(request.content) ? request.content : [{ type: TEXT_CONTENT_TYPE, text: String(request.content || '') }];
    request.content = [...content, { type: TEXT_CONTENT_TYPE, text: `Observation images from ${toolName}, call ${callId}. Use only the latest observation for its target.` }, ...parts];
  }
  return { text: `${text}\n${parts.length} observation image(s) attached for call ${callId}.${omitted ? ' Unsupported, oversized, or image-limit content omitted; do not infer its visual state.' : ''}`, attached: parts.length };
}
