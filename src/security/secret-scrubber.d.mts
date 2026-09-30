export type SecretMatch = { type: string; start: number; end: number };
export function detect(text: string): SecretMatch[];
export function redact(text: string): string;
export function containsSecret(text: string): boolean;
export function secretValues(text: string): { type: string; value: string }[];
export function redactValue<T>(value: T): T;
