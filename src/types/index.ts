export interface SeenContent {
  id: string;
  user_id: string;
  url: string;
  title: string;
  content_hash?: string;
  favicon?: string;
  seen_at: string;
  hide_similar: boolean;
}

export interface User {
  id: string;
  email: string;
}

export interface TabInfo {
  url: string;
  title: string;
  favicon?: string;
}
