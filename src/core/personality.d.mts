export type PersonalityProfile = {
  enabled: boolean; description: string; care: string;
  attitude: 'gentle' | 'balanced' | 'bold';
  teasing: 'off' | 'light' | 'playful';
  language: 'match-user' | 'hinglish' | 'english';
  examples: { user: string; assistant: string }[];
};
export type PersonalityView = { profile: PersonalityProfile; notice: string | null };
export const PERSONALITY_FILENAME: string;
export const PERSONALITY_VERSION: number;
export const PERSONALITY_LIMITS: Readonly<{ description: number; care: number; examples: number; user: number; assistant: number }>;
export const PERSONALITY_OPTIONS: { attitude: Record<PersonalityProfile['attitude'], string>; teasing: Record<PersonalityProfile['teasing'], string>; language: Record<PersonalityProfile['language'], string> };
export const DEFAULT_PERSONALITY: Readonly<PersonalityProfile>;
export function normalizePersonality(input?: Partial<PersonalityProfile>, base?: PersonalityProfile): PersonalityProfile;
export function personalityPrompt(input?: Partial<PersonalityProfile>, options?: { compact?: boolean }): string;
export const PERSONALITY_ACTIONS: Readonly<{ get: string; save: string }>;
