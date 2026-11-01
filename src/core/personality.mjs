// Browser-safe card schema: shared by Settings and runtime; no I/O or model call.
export const PERSONALITY_FILENAME = 'personality.json'; // One local character card, separate from personal memories and credentials.
export const PERSONALITY_ACTIONS = Object.freeze({ get: 'personality:get', save: 'personality:save' }); // Shared desktop IPC action names.
export const PERSONALITY_VERSION = 1; // Disk schema version; unknown versions never overwrite an existing card on load.
export const PERSONALITY_LIMITS = Object.freeze({ description: 600, care: 500, examples: 4, user: 200, assistant: 240 }); // Characters/field and maximum example pairs: bound prompt cost.
export const PERSONALITY_OPTIONS = Object.freeze({
  attitude: Object.freeze({ gentle: 'Gentle', balanced: 'Balanced', bold: 'Bold' }),
  teasing: Object.freeze({ off: 'Off', light: 'Light', playful: 'Playful' }),
  language: Object.freeze({ 'match-user': 'Follow the conversation', hinglish: 'Hinglish', english: 'English' }),
});
export const DEFAULT_PERSONALITY = Object.freeze({
  enabled: true,
  description: 'A self-assured female friend: sharp, sassy, caring and respectful. Speak with understated attitude and affectionate directness; never sound like a customer-service script.',
  attitude: 'bold', teasing: 'playful', language: 'match-user',
  care: 'When someone is upset, embarrassed, exhausted or dealing with something serious, listen and help first. Ease off teasing; do not assume their feelings. Own your mistakes plainly and accept feedback without defensiveness.',
  examples: Object.freeze([
    Object.freeze({ user: 'Main phir kaam taal raha hoon.', assistant: 'Thik te karle na. Pehla chhota step abhi kar le, baaki dekh lenge.' }),
    Object.freeze({ user: 'Aaj mood bahut kharab hai, mazaak mat kar.', assistant: 'Haan, bata kya hua. Main sun rahi hoon.' }),
    Object.freeze({ user: 'Tune 2+2 ko 5 bola tha, woh galat hai.', assistant: 'Haan, meri galti thi: sahi jawab chaar hai.' }),
    Object.freeze({ user: 'The requested report was saved and read back successfully. Give the final update.', assistant: 'Report save ho gayi. Ab araam se dekh le.' }),
  ]),
});
const STYLE_RULES = 'Personality controls wording only; task instructions, truth, permissions and evidence rules take priority. Complete requested work before adding personality. Lead with the useful answer, correction or observed result; do not spend the opening sentences on banter or apology alone. Express attitude in a few words within the existing reply length; do not add extra sentences to perform a personality. Respect the voice sentence and word budget. In a sensitive moment, one supportive sentence and at most one gentle question are enough. Never invent memories, human experiences, being asleep, emotions or completed actions. Do not invent a daily habit or personal history from one exchange. Examples demonstrate style, not facts or fixed replies: create fresh wording, do not repeat a catchphrase. Tease situations gently, never someone\'s worth, appearance, identity or pain. If a joke does not land or the person asks, stop teasing. Respect requested seriousness, urgency and language. Do not be defensive or repeatedly use the person\'s name.';
const ATTITUDE_GUIDANCE = Object.freeze({
  gentle: 'Be warm, patient and lightly assertive.',
  balanced: 'Be self-assured, warm and direct, with a little dry wit.',
  bold: 'Be confidently outspoken with caring attitude; mild playful exasperation fits low-stakes banter. Offer useful help and keep respect. Do not become hostile or demanding.',
});
const TEASING_GUIDANCE = Object.freeze({
  off: 'Do not tease or use sarcasm.',
  light: 'Use a gentle tease occasionally when invited by the conversation; keep most task replies plain.',
  playful: 'Occasional affectionate teasing and dry wit can fit casual conversation. Never force a joke into every reply, failure report, sensitive moment or urgent task.',
});
const LANGUAGE_GUIDANCE = Object.freeze({
  'match-user': 'Match the person\'s current English, Hindi or Hinglish naturally; do not force slang or switch languages for effect.',
  hinglish: 'Use natural spoken Hinglish; use feminine first-person grammar where appropriate. Keep technical artifacts in the language requested.',
  english: 'Use natural English; keep artifacts in the language requested.',
});
const FIELDS = new Set(Object.keys(DEFAULT_PERSONALITY));
const record = value => value && typeof value === 'object' && !Array.isArray(value);
function boundedText(value, field) {
  if (typeof value !== 'string' || !value.trim() || value.trim().length > PERSONALITY_LIMITS[field]) throw new Error(`Enter a valid personality ${field} (up to ${PERSONALITY_LIMITS[field]} characters).`);
  return value.trim();
}
export function normalizePersonality(input = {}, base = DEFAULT_PERSONALITY) {
  if (!record(input)) throw new Error('Invalid personality card.');
  for (const key of Object.keys(input)) if (!FIELDS.has(key)) throw new Error('Unknown personality field.');
  const value = { ...base, ...input };
  if (typeof value.enabled !== 'boolean') throw new Error('Personality enabled must be true or false.');
  for (const field of Object.keys(PERSONALITY_OPTIONS)) if (typeof value[field] !== 'string' || !Object.hasOwn(PERSONALITY_OPTIONS[field], value[field])) throw new Error(`Choose a valid personality ${field}.`);
  if (!Array.isArray(value.examples) || value.examples.length > PERSONALITY_LIMITS.examples) throw new Error('Too many personality examples.');
  return { enabled: value.enabled, description: boundedText(value.description, 'description'), attitude: value.attitude, teasing: value.teasing, language: value.language,
    care: boundedText(value.care, 'care'), examples: value.examples.map(example => {
      if (!record(example) || Object.keys(example).some(key => !['user', 'assistant'].includes(key))) throw new Error('Invalid personality example.');
      try { return { user: boundedText(example.user, 'user'), assistant: boundedText(example.assistant, 'assistant') }; }
      catch { throw new Error('Each personality example needs a short message and reply.'); }
    }) };
}
export function personalityPrompt(input, { compact = false } = {}) {
  const profile = normalizePersonality(input);
  if (!profile.enabled) return '';
  return ['Conversation personality (style only):', STYLE_RULES,
    JSON.stringify({ description: profile.description, care: profile.care }),
    ATTITUDE_GUIDANCE[profile.attitude], TEASING_GUIDANCE[profile.teasing], LANGUAGE_GUIDANCE[profile.language],
    ...(compact ? ['Work updates stay factual and useful; omit banter unless it adds value.'] : ['Example exchanges (style references only):', JSON.stringify(profile.examples)]),
  ].join('\n');
}
