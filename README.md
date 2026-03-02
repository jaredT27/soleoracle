# SoleOracle — Sneaker Drop Oracle & Resale Copilot

A full-stack sneaker intelligence platform that aggregates real-time drop calendars, production numbers, rarity tiers, resale prices, and portfolio tracking into a single dashboard.

![License](https://img.shields.io/badge/license-MIT-green)
![Backend](https://img.shields.io/badge/backend-FastAPI-009688)
![Frontend](https://img.shields.io/badge/frontend-Next.js%2015-black)

---

## Features

### Dashboard
- Real-time KPI cards: portfolio value, P&L, next hot drop, tracked drops
- Hot drops leaderboard with heat index scoring
- Live scraper activity feed with status monitoring

### Drops Calendar
- Full searchable/filterable drop calendar
- Brand filters (Nike, Jordan, adidas, New Balance, Converse, ASICS)
- Sort by date, heat index, price, or name
- Drop cards with countdown timers, rarity badges, heat scores

### Rarity Intel
- Production number leaderboard with confidence ratings
- Rarity distribution pie chart (Ultra-Rare, Limited, Semi-Limited, Mass Release)
- Submit custom production leaks with source attribution
- Confidence levels: Confirmed, Rumored, Estimated

### Portfolio Tracker
- Add/remove pairs with purchase price, size, condition, style code
- Real-time P&L calculation with ROI percentages
- Sell signal generation (Strong Sell, Consider Sell, Hold)
- Portfolio value over time chart (market value vs cost basis)
- Automated daily portfolio snapshots

### Cop Assistant
- Live raffle aggregation from Sole Retriever
- Saved profile for quick raffle entry
- Autofill bookmarklet generator
- Discord & Instagram raffle entry templates with copy-to-clipboard

### Weekly Digest
- Heat index leaderboard bar chart
- Portfolio performance summary
- Top drops ranking with rarity breakdown
- Downloadable PDF export

---

## Architecture

```
soleoracle-fullstack/
├── backend/                  # Python FastAPI server
│   ├── main.py               # FastAPI app, routes, APScheduler
│   ├── models.py             # SQLAlchemy models (SQLite)
│   ├── scrapers.py           # Real web scrapers
│   └── requirements.txt
│
├── frontend/                 # Next.js 15 App Router
│   ├── src/
│   │   ├── app/
│   │   │   ├── page.tsx      # Main SPA (6 tabs)
│   │   │   ├── layout.tsx    # Root layout
│   │   │   └── globals.css   # Custom styles
│   │   └── lib/
│   │       └── api.ts        # Typed API client
│   ├── next.config.js        # API proxy rewrites
│   ├── tailwind.config.js    # Custom theme
│   └── package.json
│
└── README.md
```

### Backend Stack
- **FastAPI** — async Python web framework
- **SQLAlchemy** — ORM with SQLite database
- **APScheduler** — background job scheduler (4 recurring jobs)
- **BeautifulSoup4 + httpx** — web scrapers
- **Uvicorn** — ASGI server

### Frontend Stack
- **Next.js 15** — React framework with App Router
- **TypeScript** — type-safe development
- **Tailwind CSS** — utility-first styling
- **Recharts** — data visualization (bar, line, pie charts)
- **Lucide React** — icon library
- **date-fns** — date utilities

---

## Data Sources (Live Scrapers)

| Source | Data | Schedule |
|--------|------|----------|
| Sole Retriever | Drop dates, raffles | Every hour |
| Sneaker Bar Detroit | Release calendar | Every hour |
| Nike SNKRS API | Official Nike/Jordan drops | Every hour |
| Sneaker News | Release dates | Every hour |
| StockX (public) | Resale prices | Every 4 hours |
| GOAT (public) | Resale prices | Every 4 hours |
| Hypebeast / Complex | Production intel | Every 6 hours |

### APScheduler Jobs
1. **scrape_all_drops** — hourly, aggregates from all drop sources
2. **scrape_resale_prices** — every 4 hours, updates StockX/GOAT prices
3. **scrape_production_intel** — every 6 hours, gathers production leaks
4. **take_portfolio_snapshot** — daily, records portfolio value history

---

## Quick Start (Local Development)

### Prerequisites
- Python 3.10+
- Node.js 18+
- npm or yarn

### 1. Clone the repo
```bash
git clone https://github.com/YOUR_USERNAME/soleoracle.git
cd soleoracle
```

### 2. Start the backend
```bash
cd backend
pip install -r requirements.txt
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```
The backend will:
- Create `soleoracle.db` (SQLite) automatically
- Start APScheduler with 4 recurring jobs
- Begin scraping data immediately on first run
- Serve API at `http://localhost:8000`

### 3. Start the frontend (new terminal)
```bash
cd frontend
npm install
npm run dev
```
Frontend runs at `http://localhost:3000` and proxies `/api/*` to the backend.

### 4. Open the app
Navigate to [http://localhost:3000](http://localhost:3000). Data will populate automatically as scrapers run.

---

## API Endpoints

### Drops
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/drops` | List drops (query: brand, search, sort, limit) |
| GET | `/api/drops/hot?limit=N` | Top N drops by heat index |
| GET | `/api/drops/stats` | Aggregate drop statistics |

### Portfolio
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/portfolio` | List all portfolio items |
| POST | `/api/portfolio` | Add a pair |
| DELETE | `/api/portfolio/:id` | Remove a pair |
| GET | `/api/portfolio/stats` | Portfolio P&L summary |
| GET | `/api/portfolio/snapshots?days=N` | Historical value snapshots |

### Rarity Intel
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/leaks` | List production leaks |
| POST | `/api/leaks` | Submit a leak |
| GET | `/api/leaks/rarity-distribution` | Rarity tier counts |

### Cop Assistant
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/raffles` | Active raffles |
| POST | `/api/cop/bookmarklet` | Generate autofill bookmarklet |
| GET | `/api/cop/raffle-templates` | Discord/Instagram templates |

### System
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/health` | Health check |
| GET | `/api/digest` | Weekly digest data |
| GET | `/api/export` | Full data export (JSON) |
| POST | `/api/scrapers/run?target=all` | Trigger scrapers manually |
| GET | `/api/scrapers/logs` | Scraper run history |
| GET | `/api/scheduler/status` | APScheduler job status |

---

## Deployment

### Backend → Render.com
1. Create a new **Web Service** on [Render](https://render.com)
2. Connect your GitHub repo
3. Set:
   - **Root Directory**: `backend`
   - **Build Command**: `pip install -r requirements.txt`
   - **Start Command**: `uvicorn main:app --host 0.0.0.0 --port $PORT`
4. Deploy

### Frontend → Vercel
1. Import the repo on [Vercel](https://vercel.com)
2. Set:
   - **Root Directory**: `frontend`
   - **Framework Preset**: Next.js
3. Add environment variable:
   - `NEXT_PUBLIC_API_URL` = your Render backend URL (e.g., `https://soleoracle-api.onrender.com`)
4. Deploy

---

## Heat Index Algorithm

Each drop receives a composite **Heat Index** (0–10) calculated from:

| Factor | Weight | Source |
|--------|--------|--------|
| Hype Score | 35% | Social media buzz, article mentions |
| Scarcity Score | 30% | Production numbers, rarity tier |
| Resale Multiple | 25% | StockX/GOAT price vs retail |
| Velocity Score | 10% | How fast resale prices are moving |

---

## Environment Variables

### Backend
| Variable | Default | Description |
|----------|---------|-------------|
| `PORT` | `8000` | Server port |

### Frontend
| Variable | Default | Description |
|----------|---------|-------------|
| `NEXT_PUBLIC_API_URL` | `http://localhost:8000` | Backend API URL |

---

## License

MIT License. See [LICENSE](LICENSE) for details.

---

Built with real-time sneaker data. No mock data. No static pages. Pure full-stack.
