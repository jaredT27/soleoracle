"use client";

import { useState, useEffect, useCallback } from "react";
import {
  LayoutDashboard, CalendarDays, Diamond, Briefcase,
  Bot, FileText, RefreshCw, ChevronLeft, Menu, Sun, Moon,
  TrendingUp, TrendingDown, Clock, ExternalLink, Copy,
  Plus, Trash2, Search, Filter, Download, Flame, Zap,
} from "lucide-react";
import {
  getDrops, getHotDrops, getDropStats, getPortfolio,
  getPortfolioStats, getPortfolioSnapshots, addPortfolioItem,
  deletePortfolioItem, getLeaks, addLeak, getRarityDistribution,
  getRaffles, generateBookmarklet, getRaffleTemplates,
  triggerScrapers, getScraperLogs, getDigest, exportData,
  type Drop, type PortfolioItem, type Leak, type PortfolioStats,
  type DropStats, type Raffle,
} from "@/lib/api";
import {
  BarChart, Bar, LineChart, Line, XAxis, YAxis, CartesianGrid,
  Tooltip, ResponsiveContainer, PieChart, Pie, Cell, Legend,
} from "recharts";

function cn(...classes: (string | boolean | undefined)[]) {
  return classes.filter(Boolean).join(" ");
}

function formatPrice(n: number | null | undefined): string {
  if (n == null) return "—";
  return "$" + n.toLocaleString("en-US", { minimumFractionDigits: 0, maximumFractionDigits: 0 });
}

function formatDate(d: string | null): string {
  if (!d) return "TBD";
  const date = new Date(d);
  return date.toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" });
}

function countdown(dateStr: string | null): string {
  if (!dateStr) return "TBD";
  const diff = new Date(dateStr).getTime() - Date.now();
  if (diff <= 0) return "DROPPED";
  const d = Math.floor(diff / 86400000);
  const h = Math.floor((diff % 86400000) / 3600000);
  const m = Math.floor((diff % 3600000) / 60000);
  if (d > 0) return `${d}d ${h}h`;
  return `${h}h ${m}m`;
}

function heatColor(h: number): string {
  if (h >= 9) return "text-heat-fire";
  if (h >= 7) return "text-heat-high";
  if (h >= 5) return "text-heat-mid";
  return "text-heat-low";
}

function heatBg(h: number): string {
  if (h >= 9) return "bg-heat-fire/20 border-heat-fire/50";
  if (h >= 7) return "bg-heat-high/20 border-heat-high/50";
  if (h >= 5) return "bg-heat-mid/20 border-heat-mid/50";
  return "bg-heat-low/20 border-heat-low/50";
}

function rarityColor(tier: string): string {
  switch (tier) {
    case "Ultra-Rare": return "bg-rarity-ultra/20 text-rarity-ultra border-rarity-ultra/40";
    case "Limited": return "bg-rarity-limited/20 text-rarity-limited border-rarity-limited/40";
    case "Semi-Limited": return "bg-rarity-semi/20 text-rarity-semi border-rarity-semi/40";
    case "Mass Release": return "bg-rarity-mass/20 text-rarity-mass border-rarity-mass/40";
    default: return "bg-gray-800 text-gray-400 border-gray-600/40";
  }
}

const RARITY_COLORS: Record<string, string> = {
  "Ultra-Rare": "#ef4444", "Limited": "#f97316",
  "Semi-Limited": "#3b82f6", "Mass Release": "#6b7280", "Unknown": "#4b5563",
};

type Tab = "dashboard" | "drops" | "rarity" | "portfolio" | "cop" | "digest";
const TABS: { id: Tab; label: string; icon: typeof LayoutDashboard }[] = [
  { id: "dashboard", label: "Dashboard", icon: LayoutDashboard },
  { id: "drops", label: "Drops Calendar", icon: CalendarDays },
  { id: "rarity", label: "Rarity Intel", icon: Diamond },
  { id: "portfolio", label: "Portfolio", icon: Briefcase },
  { id: "cop", label: "Cop Assistant", icon: Bot },
  { id: "digest", label: "Digest", icon: FileText },
];

export default function SoleOracle() {
  const [tab, setTab] = useState<Tab>("dashboard");
  const [sidebarOpen, setSidebarOpen] = useState(true);
  const [darkMode, setDarkMode] = useState(true);
  const [clock, setClock] = useState("");

  useEffect(() => {
    const tick = () => setClock(new Date().toLocaleTimeString("en-US", { hour: "2-digit", minute: "2-digit", second: "2-digit" }));
    tick();
    const id = setInterval(tick, 1000);
    return () => clearInterval(id);
  }, []);

  return (
    <div className={cn("flex h-screen overflow-hidden", darkMode ? "dark" : "")}>
      <aside className={cn(
        "flex flex-col bg-bg-card border-r border-white/5 transition-all duration-300 z-20",
        sidebarOpen ? "w-56" : "w-16"
      )}>
        <div className="flex items-center gap-2 p-4 border-b border-white/5">
          <div className="w-8 h-8 bg-accent rounded-lg flex items-center justify-center flex-shrink-0">
            <Flame size={18} className="text-black" />
          </div>
          {sidebarOpen && <span className="font-display text-lg font-bold tracking-tight">SoleOracle</span>}
        </div>

        <nav className="flex-1 py-2">
          {TABS.map(t => (
            <button
              key={t.id}
              onClick={() => setTab(t.id)}
              className={cn(
                "w-full flex items-center gap-3 px-4 py-2.5 text-sm transition-colors",
                tab === t.id
                  ? "bg-accent text-black font-semibold"
                  : "text-gray-400 hover:text-white hover:bg-white/5"
              )}
            >
              <t.icon size={18} />
              {sidebarOpen && t.label}
            </button>
          ))}
        </nav>

        <button
          onClick={() => setSidebarOpen(!sidebarOpen)}
          className="p-4 border-t border-white/5 text-gray-500 hover:text-white flex items-center gap-2 text-sm"
        >
          <ChevronLeft size={16} className={cn("transition-transform", !sidebarOpen && "rotate-180")} />
          {sidebarOpen && "Collapse"}
        </button>
      </aside>

      <div className="flex-1 flex flex-col overflow-hidden">
        <header className="flex items-center justify-between px-6 py-3 border-b border-white/5 bg-bg-card/80 backdrop-blur">
          <div className="flex items-center gap-3">
            <button onClick={() => setSidebarOpen(!sidebarOpen)} className="md:hidden">
              <Menu size={20} />
            </button>
            <h1 className="font-display text-xl font-bold">
              {TABS.find(t => t.id === tab)?.label}
            </h1>
            <span className="text-xs text-gray-500">Live data</span>
          </div>

          <div className="flex items-center gap-3">
            <span className="text-sm tabular-nums text-gray-400">{clock}</span>
            <button
              onClick={() => triggerScrapers("all")}
              className="p-2 rounded-lg hover:bg-white/5 text-gray-400 hover:text-white"
              title="Refresh data"
            >
              <RefreshCw size={16} />
            </button>
            <button
              onClick={async () => {
                const data = await exportData();
                const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
                const url = URL.createObjectURL(blob);
                const a = document.createElement("a");
                a.href = url; a.download = "soleoracle-backup.json"; a.click();
              }}
              className="p-2 rounded-lg hover:bg-white/5 text-gray-400 hover:text-white"
              title="Export data"
            >
              <Download size={16} />
            </button>
            <button
              onClick={() => setDarkMode(!darkMode)}
              className="p-2 rounded-lg hover:bg-white/5 text-gray-400 hover:text-white"
            >
              {darkMode ? <Sun size={16} /> : <Moon size={16} />}
            </button>
          </div>
        </header>

        <main className="flex-1 overflow-y-auto p-6">
          {tab === "dashboard" && <DashboardTab />}
          {tab === "drops" && <DropsTab />}
          {tab === "rarity" && <RarityTab />}
          {tab === "portfolio" && <PortfolioTab />}
          {tab === "cop" && <CopTab />}
          {tab === "digest" && <DigestTab />}
        </main>
      </div>
    </div>
  );
}


function DashboardTab() {
  const [stats, setStats] = useState<PortfolioStats | null>(null);
  const [dropStats, setDropStats] = useState<DropStats | null>(null);
  const [hotDrops, setHotDrops] = useState<Drop[]>([]);
  const [logs, setLogs] = useState<{ scraper: string; status: string; message: string; run_at: string }[]>([]);

  useEffect(() => {
    getPortfolioStats().then(setStats).catch(() => {});
    getDropStats().then(setDropStats).catch(() => {});
    getHotDrops(6).then(setHotDrops).catch(() => {});
    getScraperLogs().then(setLogs).catch(() => {});
  }, []);

  return (
    <div className="space-y-6">
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
        <KpiCard label="PORTFOLIO VALUE" value={formatPrice(stats?.current_value)} sub={stats ? `from ${formatPrice(stats.total_invested)} invested` : ""} />
        <KpiCard
          label="TOTAL P&L"
          value={stats ? `${stats.total_pnl >= 0 ? "+" : ""}${formatPrice(stats.total_pnl)}` : "—"}
          sub={stats ? `${stats.pnl_pct >= 0 ? "+" : ""}${stats.pnl_pct}%` : ""}
          accent={stats != null ? stats.total_pnl >= 0 : undefined}
        />
        <KpiCard
          label="NEXT HOT DROP"
          value={hotDrops[0]?.name?.slice(0, 30) || "Loading..."}
          sub={hotDrops[0] ? countdown(hotDrops[0].release_date) : ""}
        />
        <KpiCard
          label="TRACKED DROPS"
          value={String(dropStats?.total_drops || 0)}
          sub={`Avg Heat: ${dropStats?.avg_heat_index || 0}`}
        />
      </div>

      <section>
        <h2 className="text-lg font-display font-bold mb-4">Hot Drops This Week</h2>
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {hotDrops.map(drop => (
            <DropCard key={drop.id} drop={drop} />
          ))}
          {hotDrops.length === 0 && (
            <div className="col-span-3 text-center py-12 text-gray-500">
              <RefreshCw className="mx-auto mb-2 animate-spin" size={24} />
              Scrapers running — data loading...
            </div>
          )}
        </div>
      </section>

      <section>
        <h2 className="text-lg font-display font-bold mb-4">Scraper Activity</h2>
        <div className="bg-bg-card border border-white/5 rounded-xl overflow-hidden">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-white/5 text-gray-500 text-xs uppercase">
                <th className="text-left p-3">Scraper</th>
                <th className="text-left p-3">Status</th>
                <th className="text-left p-3">Message</th>
                <th className="text-left p-3">Time</th>
              </tr>
            </thead>
            <tbody>
              {logs.slice(0, 5).map((l, i) => (
                <tr key={i} className="border-b border-white/5 last:border-0">
                  <td className="p-3 font-medium">{l.scraper}</td>
                  <td className="p-3">
                    <span className={cn("px-2 py-0.5 rounded text-xs font-medium",
                      l.status === "success" ? "bg-green-500/20 text-green-400" : "bg-red-500/20 text-red-400"
                    )}>{l.status}</span>
                  </td>
                  <td className="p-3 text-gray-400 max-w-xs truncate">{l.message}</td>
                  <td className="p-3 text-gray-500 tabular-nums">{l.run_at ? new Date(l.run_at).toLocaleTimeString() : ""}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
}


function DropsTab() {
  const [drops, setDrops] = useState<Drop[]>([]);
  const [loading, setLoading] = useState(true);
  const [brand, setBrand] = useState("");
  const [search, setSearch] = useState("");
  const [sort, setSort] = useState("date");

  const load = useCallback(() => {
    setLoading(true);
    const params: Record<string, string> = { sort, limit: "100" };
    if (brand) params.brand = brand;
    if (search) params.search = search;
    getDrops(params).then(setDrops).catch(() => {}).finally(() => setLoading(false));
  }, [brand, search, sort]);

  useEffect(() => { load(); }, [load]);

  const brands = ["All Brands", "Nike", "Jordan", "adidas", "New Balance", "Converse", "ASICS"];

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap gap-3 items-center">
        <div className="relative flex-1 max-w-md">
          <Search size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-500" />
          <input
            type="text"
            placeholder="Search drops..."
            value={search}
            onChange={e => setSearch(e.target.value)}
            className="w-full pl-10 pr-4 py-2 bg-bg-card border border-white/10 rounded-lg text-sm focus:border-accent focus:outline-none"
          />
        </div>

        <div className="flex gap-1">
          {brands.map(b => (
            <button
              key={b}
              onClick={() => setBrand(b === "All Brands" ? "" : b)}
              className={cn(
                "px-3 py-1.5 rounded-lg text-xs font-medium transition",
                (brand === "" && b === "All Brands") || brand === b
                  ? "bg-accent text-black"
                  : "bg-bg-card border border-white/10 text-gray-400 hover:text-white"
              )}
            >{b}</button>
          ))}
        </div>

        <select
          value={sort}
          onChange={e => setSort(e.target.value)}
          className="px-3 py-1.5 rounded-lg text-xs bg-bg-card border border-white/10 text-gray-400"
        >
          <option value="date">Sort: Date</option>
          <option value="heat">Sort: Heat</option>
          <option value="price">Sort: Price</option>
          <option value="name">Sort: Name</option>
        </select>
      </div>

      {loading ? (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {[1,2,3,4,5,6].map(i => (
            <div key={i} className="bg-bg-card border border-white/5 rounded-xl h-64 animate-pulse" />
          ))}
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {drops.map(drop => (
            <DropCard key={drop.id} drop={drop} expanded />
          ))}
          {drops.length === 0 && (
            <div className="col-span-3 text-center py-16 text-gray-500">
              No drops found matching your filters.
            </div>
          )}
        </div>
      )}

      <p className="text-xs text-gray-600 text-center">{drops.length} drops loaded from live scrapers</p>
    </div>
  );
}


function RarityTab() {
  const [leaks, setLeaks] = useState<Leak[]>([]);
  const [rarity, setRarity] = useState<Record<string, number>>({});
  const [form, setForm] = useState({ shoe_name: "", production_number: "", source_url: "", confidence: "Estimated" });

  useEffect(() => {
    getLeaks().then(setLeaks).catch(() => {});
    getRarityDistribution().then(setRarity).catch(() => {});
  }, []);

  const handleAddLeak = async () => {
    if (!form.shoe_name || !form.production_number) return;
    try {
      const leak = await addLeak({
        shoe_name: form.shoe_name,
        production_number: parseInt(form.production_number),
        source_url: form.source_url,
        confidence: form.confidence,
      });
      setLeaks(prev => [leak, ...prev]);
      setForm({ shoe_name: "", production_number: "", source_url: "", confidence: "Estimated" });
    } catch {}
  };

  const pieData = Object.entries(rarity).map(([name, value]) => ({ name, value }));

  return (
    <div className="space-y-6">
      <div className="grid grid-cols-1 lg:grid-cols-5 gap-6">
        <div className="lg:col-span-3 bg-bg-card border border-white/5 rounded-xl p-5">
          <h3 className="font-display font-bold mb-4">Production Leaderboard</h3>
          <table className="w-full text-sm">
            <thead>
              <tr className="text-gray-500 text-xs uppercase border-b border-white/5">
                <th className="text-left p-2">Shoe</th>
                <th className="text-left p-2">Production</th>
                <th className="text-left p-2">Confidence</th>
                <th className="text-left p-2">Source</th>
              </tr>
            </thead>
            <tbody>
              {leaks.map(l => (
                <tr key={l.id} className="border-b border-white/5 last:border-0">
                  <td className="p-2 font-medium">{l.shoe_name}</td>
                  <td className="p-2 tabular-nums">{l.production_number.toLocaleString()} pairs</td>
                  <td className="p-2">
                    <span className={cn("px-2 py-0.5 rounded text-xs font-medium border",
                      l.confidence === "Confirmed" ? "bg-green-500/20 text-green-400 border-green-500/30" :
                      l.confidence === "Rumored" ? "bg-yellow-500/20 text-yellow-400 border-yellow-500/30" :
                      "bg-red-500/20 text-red-400 border-red-500/30"
                    )}>{l.confidence}</span>
                  </td>
                  <td className="p-2">
                    {l.source_url ? (
                      <a href={l.source_url} target="_blank" rel="noopener noreferrer" className="text-accent hover:underline text-xs flex items-center gap-1">
                        Source <ExternalLink size={10} />
                      </a>
                    ) : <span className="text-gray-600 text-xs">{l.submitted_by}</span>}
                  </td>
                </tr>
              ))}
              {leaks.length === 0 && (
                <tr><td colSpan={4} className="p-8 text-center text-gray-500">No production leaks yet</td></tr>
              )}
            </tbody>
          </table>
        </div>

        <div className="lg:col-span-2 bg-bg-card border border-white/5 rounded-xl p-5">
          <h3 className="font-display font-bold mb-4">Rarity Distribution</h3>
          {pieData.length > 0 ? (
            <ResponsiveContainer width="100%" height={250}>
              <PieChart>
                <Pie data={pieData} cx="50%" cy="50%" innerRadius={50} outerRadius={90} dataKey="value" paddingAngle={3}>
                  {pieData.map((entry, i) => (
                    <Cell key={i} fill={RARITY_COLORS[entry.name] || "#4b5563"} />
                  ))}
                </Pie>
                <Legend />
                <Tooltip />
              </PieChart>
            </ResponsiveContainer>
          ) : (
            <div className="flex items-center justify-center h-64 text-gray-500">Loading distribution...</div>
          )}
        </div>
      </div>

      <div className="bg-bg-card border border-white/5 rounded-xl p-5">
        <h3 className="font-display font-bold mb-4">Add Custom Leak</h3>
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-5 gap-3">
          <input placeholder="Shoe name" value={form.shoe_name}
            onChange={e => setForm(f => ({ ...f, shoe_name: e.target.value }))}
            className="px-3 py-2 bg-bg border border-white/10 rounded-lg text-sm" />
          <input placeholder="Production number" type="number" value={form.production_number}
            onChange={e => setForm(f => ({ ...f, production_number: e.target.value }))}
            className="px-3 py-2 bg-bg border border-white/10 rounded-lg text-sm" />
          <input placeholder="Source URL" value={form.source_url}
            onChange={e => setForm(f => ({ ...f, source_url: e.target.value }))}
            className="px-3 py-2 bg-bg border border-white/10 rounded-lg text-sm" />
          <select value={form.confidence}
            onChange={e => setForm(f => ({ ...f, confidence: e.target.value }))}
            className="px-3 py-2 bg-bg border border-white/10 rounded-lg text-sm">
            <option>Estimated</option><option>Rumored</option><option>Confirmed</option>
          </select>
          <button onClick={handleAddLeak}
            className="bg-accent text-black font-semibold px-4 py-2 rounded-lg flex items-center justify-center gap-2 hover:bg-accent/90">
            <Plus size={16} /> Add Leak
          </button>
        </div>
      </div>
    </div>
  );
}


function PortfolioTab() {
  const [items, setItems] = useState<PortfolioItem[]>([]);
  const [stats, setStats] = useState<PortfolioStats | null>(null);
  const [snapshots, setSnapshots] = useState<{ date: string; value: number; cost: number }[]>([]);
  const [showAdd, setShowAdd] = useState(false);
  const [form, setForm] = useState({ name: "", brand: "Nike", size: "10", purchase_price: "", purchase_date: "", condition: "DS", style_code: "" });

  const load = useCallback(() => {
    getPortfolio().then(setItems).catch(() => {});
    getPortfolioStats().then(setStats).catch(() => {});
    getPortfolioSnapshots().then(setSnapshots).catch(() => {});
  }, []);

  useEffect(() => { load(); }, [load]);

  const handleAdd = async () => {
    if (!form.name || !form.purchase_price) return;
    try {
      await addPortfolioItem({ ...form, purchase_price: parseFloat(form.purchase_price) });
      setShowAdd(false);
      setForm({ name: "", brand: "Nike", size: "10", purchase_price: "", purchase_date: "", condition: "DS", style_code: "" });
      load();
    } catch {}
  };

  const handleDelete = async (id: number) => {
    try { await deletePortfolioItem(id); load(); } catch {}
  };

  return (
    <div className="space-y-6">
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
        <KpiCard label="TOTAL INVESTED" value={formatPrice(stats?.total_invested)} />
        <KpiCard label="CURRENT VALUE" value={formatPrice(stats?.current_value)} />
        <KpiCard
          label="TOTAL P&L"
          value={stats ? `${stats.total_pnl >= 0 ? "+" : ""}${formatPrice(stats.total_pnl)}` : "—"}
          sub={stats ? `${stats.pnl_pct >= 0 ? "+" : ""}${stats.pnl_pct}%` : ""}
          accent={stats ? stats.total_pnl >= 0 : false}
        />
        <KpiCard
          label="BEST PERFORMER"
          value={stats?.best_performer?.name?.slice(0, 25) || "—"}
          sub={stats?.best_performer ? `+${formatPrice(stats.best_performer.pnl)} (${stats.best_performer.roi}%)` : ""}
        />
      </div>

      <div className="flex items-center justify-between">
        <h2 className="text-lg font-display font-bold">My Collection</h2>
        <button onClick={() => setShowAdd(!showAdd)}
          className="bg-accent text-black font-semibold px-4 py-2 rounded-lg flex items-center gap-2 text-sm hover:bg-accent/90">
          <Plus size={16} /> Add Pair
        </button>
      </div>

      {showAdd && (
        <div className="bg-bg-card border border-white/5 rounded-xl p-5 grid grid-cols-1 md:grid-cols-4 gap-3">
          <input placeholder="Shoe name" value={form.name} onChange={e => setForm(f => ({...f, name: e.target.value}))}
            className="px-3 py-2 bg-bg border border-white/10 rounded-lg text-sm" />
          <input placeholder="Purchase price" type="number" value={form.purchase_price}
            onChange={e => setForm(f => ({...f, purchase_price: e.target.value}))}
            className="px-3 py-2 bg-bg border border-white/10 rounded-lg text-sm" />
          <input placeholder="Size" value={form.size} onChange={e => setForm(f => ({...f, size: e.target.value}))}
            className="px-3 py-2 bg-bg border border-white/10 rounded-lg text-sm" />
          <input placeholder="Style code" value={form.style_code} onChange={e => setForm(f => ({...f, style_code: e.target.value}))}
            className="px-3 py-2 bg-bg border border-white/10 rounded-lg text-sm" />
          <select value={form.brand} onChange={e => setForm(f => ({...f, brand: e.target.value}))}
            className="px-3 py-2 bg-bg border border-white/10 rounded-lg text-sm">
            {["Nike","Jordan","adidas","New Balance","Puma","Converse","ASICS","Reebok"].map(b => <option key={b}>{b}</option>)}
          </select>
          <select value={form.condition} onChange={e => setForm(f => ({...f, condition: e.target.value}))}
            className="px-3 py-2 bg-bg border border-white/10 rounded-lg text-sm">
            <option value="DS">Deadstock</option><option value="VNDS">VNDS</option><option value="Used">Used</option>
          </select>
          <input type="date" value={form.purchase_date} onChange={e => setForm(f => ({...f, purchase_date: e.target.value}))}
            className="px-3 py-2 bg-bg border border-white/10 rounded-lg text-sm" />
          <button onClick={handleAdd} className="bg-accent text-black font-semibold rounded-lg">Save</button>
        </div>
      )}

      <div className="bg-bg-card border border-white/5 rounded-xl overflow-hidden">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-white/5 text-gray-500 text-xs uppercase">
              <th className="text-left p-3">Shoe</th>
              <th className="text-left p-3">Size</th>
              <th className="text-right p-3">Bought</th>
              <th className="text-right p-3">Current</th>
              <th className="text-right p-3">P&L</th>
              <th className="text-right p-3">ROI</th>
              <th className="text-left p-3">Signal</th>
              <th className="text-left p-3"></th>
            </tr>
          </thead>
          <tbody>
            {items.map(item => {
              const pnl = (item.current_value || item.purchase_price) - item.purchase_price;
              const roi = item.purchase_price > 0 ? (pnl / item.purchase_price * 100) : 0;
              return (
                <tr key={item.id} className="border-b border-white/5 last:border-0 hover:bg-white/[0.02]">
                  <td className="p-3 font-medium">{item.name}</td>
                  <td className="p-3 text-gray-400">{item.size}</td>
                  <td className="p-3 text-right tabular-nums">{formatPrice(item.purchase_price)}</td>
                  <td className="p-3 text-right tabular-nums">{formatPrice(item.current_value)}</td>
                  <td className={cn("p-3 text-right tabular-nums font-medium", pnl >= 0 ? "text-green-400" : "text-red-400")}>
                    {pnl >= 0 ? "+" : ""}{formatPrice(pnl)}
                  </td>
                  <td className={cn("p-3 text-right tabular-nums", pnl >= 0 ? "text-green-400" : "text-red-400")}>
                    {pnl >= 0 ? "+" : ""}{roi.toFixed(1)}%
                  </td>
                  <td className="p-3">
                    <span className={cn("text-xs font-medium",
                      item.sell_signal === "Strong Sell" ? "text-red-400" :
                      item.sell_signal === "Consider Sell" ? "text-yellow-400" :
                      "text-gray-400"
                    )}>{item.sell_signal}</span>
                  </td>
                  <td className="p-3">
                    <button onClick={() => handleDelete(item.id)} className="text-gray-600 hover:text-red-400">
                      <Trash2 size={14} />
                    </button>
                  </td>
                </tr>
              );
            })}
            {items.length === 0 && (
              <tr><td colSpan={8} className="p-12 text-center text-gray-500">No pairs in collection — add your first pair above</td></tr>
            )}
          </tbody>
        </table>
      </div>

      {snapshots.length > 0 && (
        <div className="bg-bg-card border border-white/5 rounded-xl p-5">
          <h3 className="font-display font-bold mb-4">Portfolio Value Over Time</h3>
          <ResponsiveContainer width="100%" height={300}>
            <LineChart data={snapshots}>
              <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.05)" />
              <XAxis dataKey="date" tick={{ fill: "#6b7280", fontSize: 11 }}
                tickFormatter={(d: string) => new Date(d).toLocaleDateString("en-US", { month: "short", day: "numeric" })} />
              <YAxis tick={{ fill: "#6b7280", fontSize: 11 }} tickFormatter={(v: number) => `$${(v/1000).toFixed(1)}k`} />
              <Tooltip contentStyle={{ background: "#111118", border: "1px solid rgba(255,255,255,0.1)", borderRadius: 8 }}
                formatter={(v: number) => [`$${v.toLocaleString()}`, ""]} />
              <Line type="monotone" dataKey="value" stroke="#10b981" strokeWidth={2} dot={false} name="Market Value" />
              <Line type="monotone" dataKey="cost" stroke="#6b7280" strokeWidth={1} strokeDasharray="5 5" dot={false} name="Cost Basis" />
            </LineChart>
          </ResponsiveContainer>
        </div>
      )}
    </div>
  );
}


function CopTab() {
  const [raffles, setRaffles] = useState<Raffle[]>([]);
  const [bookmarklet, setBookmarklet] = useState("");
  const [templates, setTemplates] = useState({ discord: "", instagram: "" });
  const [profile, setProfile] = useState({ name: "", email: "", phone: "", size: "10", zip: "" });
  const [copied, setCopied] = useState("");

  useEffect(() => {
    getRaffles().then(setRaffles).catch(() => {});
    getRaffleTemplates("Sneakerhead", "10").then(setTemplates).catch(() => {});
  }, []);

  const handleGenerateBookmarklet = async () => {
    const { bookmarklet: bm } = await generateBookmarklet(profile);
    setBookmarklet(bm);
  };

  const copyText = (text: string, label: string) => {
    navigator.clipboard.writeText(text);
    setCopied(label);
    setTimeout(() => setCopied(""), 2000);
  };

  return (
    <div className="space-y-6">
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <div className="bg-bg-card border border-white/5 rounded-xl p-5">
          <h3 className="font-display font-bold mb-4">Active Raffles</h3>
          <table className="w-full text-sm">
            <thead>
              <tr className="text-gray-500 text-xs uppercase border-b border-white/5">
                <th className="text-left p-2">Shoe</th>
                <th className="text-left p-2">Store</th>
                <th className="text-left p-2">Deadline</th>
                <th className="text-left p-2">Link</th>
              </tr>
            </thead>
            <tbody>
              {raffles.map((r, i) => (
                <tr key={i} className="border-b border-white/5 last:border-0">
                  <td className="p-2 font-medium">{r.shoe_name.slice(0, 40)}</td>
                  <td className="p-2 text-gray-400">{r.store}</td>
                  <td className="p-2 text-gray-400 text-xs">{r.deadline || "TBD"}</td>
                  <td className="p-2">
                    {r.url ? (
                      <a href={r.url} target="_blank" rel="noopener noreferrer" className="text-accent text-xs hover:underline">Enter</a>
                    ) : "—"}
                  </td>
                </tr>
              ))}
              {raffles.length === 0 && (
                <tr><td colSpan={4} className="p-8 text-center text-gray-500">Raffle data loading from Sole Retriever...</td></tr>
              )}
            </tbody>
          </table>
        </div>

        <div className="bg-bg-card border border-white/5 rounded-xl p-5">
          <h3 className="font-display font-bold mb-4">Saved Profile</h3>
          <div className="space-y-3">
            {(["name", "email", "phone", "size", "zip"] as const).map(field => (
              <div key={field}>
                <label className="text-xs text-gray-500 uppercase">{field}</label>
                <input
                  value={profile[field]}
                  onChange={e => setProfile(p => ({ ...p, [field]: e.target.value }))}
                  className="w-full px-3 py-2 bg-bg border border-white/10 rounded-lg text-sm mt-1"
                />
              </div>
            ))}
            <button onClick={handleGenerateBookmarklet}
              className="w-full bg-accent text-black font-semibold py-2 rounded-lg">
              Generate Autofill Bookmarklet
            </button>
          </div>
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <div className="bg-bg-card border border-white/5 rounded-xl p-5">
          <div className="flex items-center justify-between mb-3">
            <h3 className="font-display font-bold">Autofill Bookmarklet</h3>
            {bookmarklet && (
              <button onClick={() => copyText(bookmarklet, "bookmarklet")} className="text-accent text-xs flex items-center gap-1">
                <Copy size={12} /> {copied === "bookmarklet" ? "Copied!" : "Copy"}
              </button>
            )}
          </div>
          {bookmarklet ? (
            <pre className="bg-bg p-3 rounded-lg text-xs text-gray-300 overflow-x-auto max-h-48 whitespace-pre-wrap">{bookmarklet}</pre>
          ) : (
            <p className="text-gray-500 text-sm">Fill in your profile and click Generate above.</p>
          )}
        </div>

        <div className="bg-bg-card border border-white/5 rounded-xl p-5 space-y-4">
          <h3 className="font-display font-bold">Raffle Entry Templates</h3>
          <div>
            <div className="flex items-center justify-between">
              <label className="text-xs text-gray-500 uppercase">Discord</label>
              <button onClick={() => copyText(templates.discord, "discord")} className="text-accent text-xs flex items-center gap-1">
                <Copy size={12} /> {copied === "discord" ? "Copied!" : "Copy"}
              </button>
            </div>
            <textarea value={templates.discord} readOnly rows={3}
              className="w-full mt-1 px-3 py-2 bg-bg border border-white/10 rounded-lg text-sm text-gray-300" />
          </div>
          <div>
            <div className="flex items-center justify-between">
              <label className="text-xs text-gray-500 uppercase">Instagram</label>
              <button onClick={() => copyText(templates.instagram, "instagram")} className="text-accent text-xs flex items-center gap-1">
                <Copy size={12} /> {copied === "instagram" ? "Copied!" : "Copy"}
              </button>
            </div>
            <textarea value={templates.instagram} readOnly rows={2}
              className="w-full mt-1 px-3 py-2 bg-bg border border-white/10 rounded-lg text-sm text-gray-300" />
          </div>
        </div>
      </div>
    </div>
  );
}


function DigestTab() {
  const [digest, setDigest] = useState<Record<string, any> | null>(null);

  useEffect(() => {
    getDigest().then(setDigest).catch(() => {});
  }, []);

  if (!digest) return <div className="text-center py-16 text-gray-500">Loading digest...</div>;

  const topDrops: { name: string; heat_index: number; rarity_tier: string; retail_price: number; production_number: number }[] = digest.top_drops || [];
  const barData = topDrops.map(d => ({ name: d.name.slice(0, 25), heat: d.heat_index }));
  const portfolio = digest.portfolio as { total_invested: number; current_value: number; pnl: number; count: number };
  const rarityDist = Object.entries(digest.rarity_distribution || {}).map(([name, value]) => ({ name, value: value as number }));

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h2 className="text-lg font-display font-bold">Weekly Digest — {new Date().toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" })}</h2>
        <button
          onClick={() => window.print()}
          className="bg-accent text-black font-semibold px-4 py-2 rounded-lg flex items-center gap-2 text-sm"
        >
          <Download size={16} /> Download PDF
        </button>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <div className="bg-bg-card border border-white/5 rounded-xl p-5">
          <h3 className="font-display font-bold mb-4">Heat Index Leaderboard</h3>
          {barData.length > 0 ? (
            <ResponsiveContainer width="100%" height={300}>
              <BarChart data={barData} layout="vertical">
                <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.05)" />
                <XAxis type="number" domain={[0, 10]} tick={{ fill: "#6b7280", fontSize: 11 }} />
                <YAxis type="category" dataKey="name" width={120} tick={{ fill: "#9ca3af", fontSize: 11 }} />
                <Tooltip contentStyle={{ background: "#111118", border: "1px solid rgba(255,255,255,0.1)", borderRadius: 8 }} />
                <Bar dataKey="heat" fill="#10b981" radius={[0, 4, 4, 0]} />
              </BarChart>
            </ResponsiveContainer>
          ) : <div className="h-64 flex items-center justify-center text-gray-500">No data</div>}
        </div>

        <div className="bg-bg-card border border-white/5 rounded-xl p-5 space-y-4">
          <h3 className="font-display font-bold">Digest Summary</h3>
          <div>
            <p className="text-xs text-gray-500 uppercase mb-1">Portfolio Performance</p>
            <div className="flex gap-6">
              <div>
                <p className="text-xs text-gray-500">Value</p>
                <p className="text-2xl font-bold tabular-nums">{formatPrice(portfolio?.current_value)}</p>
              </div>
              <div>
                <p className="text-xs text-gray-500">P&L</p>
                <p className={cn("text-2xl font-bold tabular-nums",
                  (portfolio?.pnl || 0) >= 0 ? "text-green-400" : "text-red-400"
                )}>{(portfolio?.pnl || 0) >= 0 ? "+" : ""}{formatPrice(portfolio?.pnl)}</p>
              </div>
            </div>
          </div>

          <div>
            <p className="text-xs text-gray-500 uppercase mb-2">Top Drops</p>
            {topDrops.slice(0, 5).map((d, i) => (
              <div key={i} className="flex items-center gap-3 py-2 border-b border-white/5 last:border-0">
                <span className={cn("w-10 h-10 rounded-full flex items-center justify-center font-display font-bold text-sm border",
                  heatBg(d.heat_index), heatColor(d.heat_index)
                )}>{d.heat_index}</span>
                <div>
                  <p className="font-medium text-sm">{d.name.slice(0, 40)}</p>
                  <p className="text-xs text-gray-500">{formatPrice(d.retail_price)} · {d.rarity_tier}</p>
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>

      {rarityDist.length > 0 && (
        <div className="bg-bg-card border border-white/5 rounded-xl p-5">
          <h3 className="font-display font-bold mb-4">Rarity Breakdown (All Tracked Drops)</h3>
          <ResponsiveContainer width="100%" height={250}>
            <PieChart>
              <Pie data={rarityDist} cx="50%" cy="50%" innerRadius={50} outerRadius={100} dataKey="value" paddingAngle={3}>
                {rarityDist.map((entry, i) => (
                  <Cell key={i} fill={RARITY_COLORS[entry.name] || "#4b5563"} />
                ))}
              </Pie>
              <Legend />
              <Tooltip />
            </PieChart>
          </ResponsiveContainer>
        </div>
      )}
    </div>
  );
}


function KpiCard({ label, value, sub, accent }: { label: string; value: string; sub?: string; accent?: boolean }) {
  return (
    <div className="bg-bg-card border border-white/5 rounded-xl p-5">
      <p className="text-xs text-gray-500 uppercase tracking-wider mb-1">{label}</p>
      <p className={cn("text-2xl font-bold tabular-nums", accent && "text-green-400")}>{value}</p>
      {sub && <p className={cn("text-sm mt-1", accent ? "text-green-400/70" : "text-gray-500")}>{sub}</p>}
    </div>
  );
}

function DropCard({ drop, expanded }: { drop: Drop; expanded?: boolean }) {
  return (
    <div className="bg-bg-card border border-white/5 rounded-xl overflow-hidden hover:border-white/10 transition group">
      <div className="relative p-4 pb-0">
        <div className="flex justify-between items-start">
          <span className={cn("px-2 py-0.5 rounded text-xs font-bold border", rarityColor(drop.rarity_tier))}>
            {drop.rarity_tier || "Unknown"}
          </span>
          <div className={cn("w-12 h-12 rounded-full flex items-center justify-center font-display font-bold text-lg border-2",
            heatBg(drop.heat_index), heatColor(drop.heat_index)
          )}>
            {drop.heat_index}
          </div>
        </div>

        <div className="h-32 flex items-center justify-center my-3">
          {drop.image_url && drop.image_url.startsWith("http") ? (
            <img src={drop.image_url} alt={drop.name} className="max-h-full max-w-full object-contain" />
          ) : (
            <svg viewBox="0 0 120 60" className="w-32 h-16 opacity-20">
              <path d="M10 45 Q15 10 40 20 Q60 28 80 15 Q100 5 110 30 L110 50 Q60 55 10 50 Z"
                fill="none" stroke="currentColor" strokeWidth="2" className={cn(
                  drop.brand === "Jordan" ? "text-red-400" :
                  drop.brand === "adidas" ? "text-blue-400" : "text-gray-400"
                )} />
            </svg>
          )}
        </div>
      </div>

      <div className="p-4 pt-0 space-y-2">
        <h3 className="font-semibold text-sm leading-tight line-clamp-2">{drop.name}</h3>

        <div className="flex items-center gap-3 text-xs text-gray-400">
          {drop.retail_price && <span className="flex items-center gap-1">💰 {formatPrice(drop.retail_price)}</span>}
          <span className="flex items-center gap-1">📅 {formatDate(drop.release_date)}</span>
        </div>

        {drop.release_date && (
          <p className={cn("text-xs font-semibold",
            countdown(drop.release_date) === "DROPPED" ? "text-gray-500" : "text-accent"
          )}>
            {countdown(drop.release_date)}
          </p>
        )}

        {expanded && (
          <div className="flex items-center justify-between text-xs text-gray-500 pt-1 border-t border-white/5">
            <span>{drop.production_number ? `${drop.production_number.toLocaleString()} pairs` : "Production TBD"}</span>
            <span className={cn("px-1.5 py-0.5 rounded text-[10px] font-medium border",
              drop.production_confidence === "Confirmed" ? "bg-green-500/20 text-green-400 border-green-500/30" :
              drop.production_confidence === "Rumored" ? "bg-yellow-500/20 text-yellow-400 border-yellow-500/30" :
              "bg-red-500/20 text-red-400 border-red-500/30"
            )}>{drop.production_confidence}</span>
          </div>
        )}

        <div className="flex items-center justify-between text-xs text-gray-600">
          {drop.source && <span>{drop.source}</span>}
          {drop.stockx_price && <span className="text-accent">StockX: {formatPrice(drop.stockx_price)}</span>}
        </div>
      </div>
    </div>
  );
}
