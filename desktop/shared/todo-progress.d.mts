import type { ChatMessage } from './wire';

export type TodoProgressItem = {
  id: string;
  content: string;
  activeForm: string;
  status: 'pending' | 'in_progress' | 'completed' | 'cancelled';
};

export function todoProgress(messages: ChatMessage[]): TodoProgressItem[];
