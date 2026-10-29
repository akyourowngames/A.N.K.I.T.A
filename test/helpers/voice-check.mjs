import { VOICE_RESULT_CHECK } from '../../src/core/voice-completion.mjs';

export const isVoiceCheck = body => body.messages?.[0]?.content?.startsWith(VOICE_RESULT_CHECK) === true;
export const checkMessage = (content = 'ANSWER') => ({ role: 'assistant', content });
