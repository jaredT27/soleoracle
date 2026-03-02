const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

async function apiFetch<T>(path: string, options?: RequestInit): Promise<T> {
  const url = `${API_BASE}${path}`;
  const res = await fetch(url, {
    ...options,
    headers: { "Content-Type": "application/json", ...options?.headers },
    cache: "no-store",
  });
  if (!res.ok) {
    const text = await res.text().catch(() => "");
    throw new Error(`API error ${res.status}: ${text}`);
  }
  return res.json();
}

export interface Drop {
  id: number;
  name: string;
  brand: string;
  colorway: string;
  style_code: string;
  retail_price: number | null;
  release_date: string | null;
  release_time: string;
  image_url: string;
  where_to_buy: string;
  raffle_links: string;
  production_number: number | null;
  production_confidence: string;
  production_source: string;
  rarity_tier: string;
  heat_index: number;
  hype_score: number;
  scarcity_score: number;
  resale_multiple: number;
  velocity_score: number;
  stockx_price: number | null;
  goat_price: number | null;
  stockx_url: string;
  goat_url: string;
  source: string;
  created_at: string | null;
  updated_at: string | null;
}

export interface PortfolioItem {
  id: number;
  name: string;
  brand: string;
  size: string;
  purchase_price: number;
  purchase_date: string | null;
  condition: string;
  image_url: string;
  current_value: number | null;
  style_code: string;
  notes: string;
  sell_signal: string;
  created_at: string | null;
  updated_at: string | null;
}

export interface Leak {
  id: number;
  shoe_name: string;
  production_number: number;
  source_url: string;
  confidence: string;
  submitted_by: string;
  created_at: string | null;
}

export interface PortfolioStats {
  total_invested: number;
  current_value: number;
  total_pnl: number;
  pnl_pct: number;
  best_performer: { name: string; pnl: number; roi: number } | null;
  count: number;
}

export interface DropStats {
  total_drops: number;
  brands: Record<string, number>;
  rarity_distribution: Record<string, number>;
  avg_heat_index: number;
  avg_retail_price: number;
}

export interface Raffle {
  shoe_name: string;
  store: string;
  url: string;
  deadline: string;
}

export interface OracleVerdict {
  verdict: "COP" | "WAIT" | "PASS";
  confidence: number;
  score: number;
  risk_tier: string;
  projected_resale_low: number | null;
  projected_resale_high: number | null;
  roi_low: number | null;
  roi_high: number | null;
  production_estimate: number;
  production_confidence: string;
  reasoning: string[];
  signals: {
    scarcity: number;
    hype: number;
    resale_multiple: number;
    velocity: number;
    heat_index: number;
  };
  drop_id: number | null;
  drop_name: string;
  matched?: boolean;
  brand?: string;
  retail_price?: number | null;
  release_date?: string | null;
  image_url?: string;
  rarity_tier?: string;
}

// Drops
export const getDrops = (params?: Record<string, string>) => {
  const q = params ? "?" + new URLSearchParams(params).toString() : "";
  return apiFetch<Drop[]>(`/api/drops${q}`);
};
export const getHotDrops = (limit = 5) => apiFetch<Drop[]>(`/api/drops/hot?limit=${limit}`);
export const getDropStats = () => apiFetch<DropStats>("/api/drops/stats");

// Portfolio
export const getPortfolio = () => apiFetch<PortfolioItem[]>("/api/portfolio");
export const addPortfolioItem = (item: Record<string, unknown>) =>
  apiFetch<PortfolioItem>("/api/portfolio", { method: "POST", body: JSON.stringify(item) });
export const deletePortfolioItem = (id: number) =>
  apiFetch<{ deleted: boolean }>(`/api/portfolio/${id}`, { method: "DELETE" });
export const getPortfolioStats = () => apiFetch<PortfolioStats>("/api/portfolio/stats");
export const getPortfolioSnapshots = (days = 90) =>
  apiFetch<{ date: string; value: number; cost: number }[]>(`/api/portfolio/snapshots?days=${days}`);

// Leaks
export const getLeaks = () => apiFetch<Leak[]>("/api/leaks");
export const addLeak = (leak: Record<string, unknown>) =>
  apiFetch<Leak>("/api/leaks", { method: "POST", body: JSON.stringify(leak) });
export const getRarityDistribution = () => apiFetch<Record<string, number>>("/api/leaks/rarity-distribution");

// Raffles
export const getRaffles = () => apiFetch<Raffle[]>("/api/raffles");

// Cop tools
export const generateBookmarklet = (params: Record<string, string>) =>
  apiFetch<{ bookmarklet: string }>(`/api/cop/bookmarklet?${new URLSearchParams(params)}`, { method: "POST" });
export const getRaffleTemplates = (name: string, size: string) =>
  apiFetch<{ discord: string; instagram: string }>(`/api/cop/raffle-templates?name=${name}&size=${size}`);

// Scrapers
export const triggerScrapers = (target = "all") =>
  apiFetch<{ triggered: string; status: string }>(`/api/scrapers/run?target=${target}`, { method: "POST" });
export const getScraperLogs = () =>
  apiFetch<{ id: number; scraper: string; status: string; message: string; items_found: number; run_at: string }[]>(
    "/api/scrapers/logs"
  );

// Digest
export const getDigest = () => apiFetch<Record<string, unknown>>("/api/digest");

// Oracle
export const getOracleBatch = (limit = 20) =>
  apiFetch<OracleVerdict[]>(`/api/oracle/batch?limit=${limit}`);
export const getOracleVerdict = (dropId: number) =>
  apiFetch<OracleVerdict>(`/api/oracle/verdict/${dropId}`);
export const getOracleVerdictByName = (name: string, brand?: string, retailPrice?: number) => {
  const params = new URLSearchParams({ name });
  if (brand) params.set("brand", brand);
  if (retailPrice) params.set("retail_price", String(retailPrice));
  return apiFetch<OracleVerdict>(`/api/oracle/verdict?${params}`, { method: "POST" });
};

// Export
export const exportData = () => apiFetch<Record<string, unknown>>("/api/export");
export const getHealth = () => apiFetch<{ status: string; service: string; timestamp: string }>("/api/health");
