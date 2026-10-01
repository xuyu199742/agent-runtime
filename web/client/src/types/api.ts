export interface Page<T> {
  items: T[];
  page: number;
  page_size: number;
  total: number;
}

export interface User {
  id: string;
  username: string;
  display_name: string;
}

export interface Agent {
  id: string;
  name: string;
  description: string;
  avatar?: string | null;
  capabilities: string[];
}

export interface Conversation {
  id: string;
  title: string;
  agent: { id: string; name: string };
  last_message: string | null;
  last_active_at: string;
  created_at: string;
}

export interface Message {
  id: string;
  role: string;
  content: string;
  created_at: string;
}

export interface Run {
  id: string;
  conversation_id: string;
  status: string;
  answer: string | null;
  error: string | null;
  created_at: string;
  started_at: string | null;
  waiting_at: string | null;
  completed_at: string | null;
}

export interface Approval {
  id: string;
  run_id: string;
  title: string;
  description: string;
  risk: string;
  tool_name: string;
  status: string;
}

export interface Artifact {
  id: string;
  conversation_id: string;
  run_id: string;
  name: string;
  type: string;
  mime_type: string;
  size: number;
  created_at: string;
}

export interface AcceptedMessage {
  message: { id: string };
  run: { id: string; status: string };
}
