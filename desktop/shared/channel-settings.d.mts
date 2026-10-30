import type { ChannelPreferences, ChannelUpdate } from './wire';
export const CHANNEL_API_REQUIRED_MESSAGE: string;
export function channelDraft(preferences: ChannelPreferences): Record<string, string | boolean>;
export function channelPatch(preferences: ChannelPreferences, draft: Record<string, string | boolean>, removed?: string[]): ChannelUpdate;
export const CHANNEL_FORM_SECTIONS: Readonly<Record<string, string>>;
export const CAPABILITY_LABELS: Readonly<Record<string, string>>;
