export type Sentiment = "positive" | "negative" | "neutral";
export type Store = "play" | "app_store";

export type ThemeRow = {
  name: string;
  count: number;
  share: number;
  avg_rating: number;
  severity: string;
  sentiment: Record<Sentiment, number>;
};

export type ReviewRow = {
  review_id: string;
  store: Store;
  rating: number;
  title: string | null;
  text: string;
  date: string;
  theme: string;
  sentiment: Sentiment;
};

export type Insights = {
  run_id: string;
  weeks: number;
  window: { start: string; end: string };
  iso_week: string;
  year: number;
  product: string;
  overview: {
    total_reviews: number;
    avg_rating: number;
    sentiment: Record<Sentiment, number>;
    rating_distribution: Record<string, number>;
    top_themes: { name: string; count: number; share: number }[];
  };
  themes: ThemeRow[];
  reviews: ReviewRow[];
  pulse: {
    title: string;
    body: string;
    words: number;
    executive_summary: string;
    themes: {
      theme: string;
      summary: string;
      quote: string;
      rating: number;
      store: Store;
      date: string;
      sentiment: Sentiment;
    }[];
    actions: {
      title: string;
      rationale: string;
      theme: string;
      owner_hint: string;
    }[];
  } | null;
  status: string;
  warnings: string[];
};

export type MailStatus = {
  connected: boolean;
  sender: string;
  subscribers: number;
};

export type SubscribeResult = {
  ok: boolean;
  email: string;
  include_quotes: boolean;
  sent: boolean;
  warning: string | null;
  subscribers: number;
};
