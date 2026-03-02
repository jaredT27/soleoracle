"""SoleOracle – FastAPI backend: REST API + APScheduler jobs."""
import json, asyncio, logging
from datetime import datetime, timedelta
from typing import Optional
from contextlib import asynccontextmanager

from fastapi import FastAPI, Depends, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sqlalchemy.orm import Session
from sqlalchemy import desc, func
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from models import (
    get_db, SneakerDrop, PortfolioItem, ProductionLeak,
    ScraperLog, PortfolioSnapshot, SessionLocal,
)
from scrapers import (
    run_drop_scrapers, run_production_scraper,
    run_resale_updater, take_portfolio_snapshot,
    scrape_raffles, scrape_resale_price,
    _compute_heat_index, _classify_rarity,
)

logger = logging.getLogger("soleoracle")

scheduler = AsyncIOScheduler()


def _wrap(coro_fn):
    """Wrap an async func so APScheduler can call it."""
    def wrapper():
        loop = asyncio.get_event_loop()
        if loop.is_running():
            asyncio.ensure_future(coro_fn())
        else:
            loop.run_until_complete(coro_fn())
    return wrapper


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("SoleOracle backend starting up...")
    scheduler.add_job(_wrap(run_drop_scrapers), "interval", hours=1, id="drops_hourly",
                      next_run_time=datetime.utcnow() + timedelta(seconds=10))
    scheduler.add_job(_wrap(run_production_scraper), "interval", hours=6, id="production_6h",
                      next_run_time=datetime.utcnow() + timedelta(seconds=30))
    scheduler.add_job(_wrap(run_resale_updater), "interval", hours=4, id="resale_4h",
                      next_run_time=datetime.utcnow() + timedelta(seconds=60))
    scheduler.add_job(_wrap(take_portfolio_snapshot), "interval", hours=24, id="snapshot_daily")
    scheduler.start()
    logger.info("APScheduler started with 4 jobs")
    asyncio.ensure_future(run_drop_scrapers())
    yield
    scheduler.shutdown(wait=False)
    logger.info("SoleOracle backend shutting down")


app = FastAPI(
    title="SoleOracle API",
    description="Sneaker Drop Oracle & Resale Copilot — Backend API",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class DropOut(BaseModel):
    id: int
    name: str
    brand: str
    colorway: str
    style_code: str
    retail_price: Optional[float]
    release_date: Optional[datetime]
    release_time: str
    image_url: str
    where_to_buy: str
    raffle_links: str
    production_number: Optional[int]
    production_confidence: str
    production_source: str
    rarity_tier: str
    heat_index: float
    hype_score: float
    scarcity_score: float
    resale_multiple: float
    velocity_score: float
    stockx_price: Optional[float]
    goat_price: Optional[float]
    stockx_url: str
    goat_url: str
    source: str
    created_at: Optional[datetime]
    updated_at: Optional[datetime]

    class Config:
        from_attributes = True


class PortfolioItemIn(BaseModel):
    name: str
    brand: str = ""
    size: str = ""
    purchase_price: float
    purchase_date: Optional[str] = None
    condition: str = "DS"
    image_url: str = ""
    style_code: str = ""
    notes: str = ""


class PortfolioItemOut(BaseModel):
    id: int
    name: str
    brand: str
    size: str
    purchase_price: float
    purchase_date: Optional[datetime]
    condition: str
    image_url: str
    current_value: Optional[float]
    style_code: str
    notes: str
    sell_signal: str
    created_at: Optional[datetime]
    updated_at: Optional[datetime]

    class Config:
        from_attributes = True


class LeakIn(BaseModel):
    shoe_name: str
    production_number: int
    source_url: str = ""
    confidence: str = "Estimated"


class LeakOut(BaseModel):
    id: int
    shoe_name: str
    production_number: int
    source_url: str
    confidence: str
    submitted_by: str
    created_at: Optional[datetime]

    class Config:
        from_attributes = True


@app.get("/api/health")
async def health():
    return {"status": "ok", "service": "SoleOracle", "timestamp": datetime.utcnow().isoformat()}


@app.get("/api/drops/hot", response_model=list[DropOut])
async def get_hot_drops(limit: int = 5, db: Session = Depends(get_db)):
    return db.query(SneakerDrop).order_by(desc(SneakerDrop.heat_index)).limit(limit).all()


@app.get("/api/drops/stats")
async def get_drop_stats(db: Session = Depends(get_db)):
    total = db.query(SneakerDrop).count()
    brands = db.query(SneakerDrop.brand, func.count(SneakerDrop.id)).group_by(SneakerDrop.brand).all()
    rarity_dist = db.query(SneakerDrop.rarity_tier, func.count(SneakerDrop.id)).group_by(SneakerDrop.rarity_tier).all()
    avg_heat = db.query(func.avg(SneakerDrop.heat_index)).scalar() or 0
    avg_price = db.query(func.avg(SneakerDrop.retail_price)).scalar() or 0
    return {
        "total_drops": total,
        "brands": {b: c for b, c in brands},
        "rarity_distribution": {r: c for r, c in rarity_dist},
        "avg_heat_index": round(float(avg_heat), 1),
        "avg_retail_price": round(float(avg_price), 2),
    }


@app.get("/api/drops", response_model=list[DropOut])
async def get_drops(
    brand: Optional[str] = None,
    rarity: Optional[str] = None,
    sort: str = Query("date", regex="^(date|heat|price|rarity|name)$"),
    search: Optional[str] = None,
    limit: int = Query(100, le=500),
    offset: int = 0,
    db: Session = Depends(get_db),
):
    q = db.query(SneakerDrop)
    if brand:
        q = q.filter(SneakerDrop.brand == brand)
    if rarity:
        q = q.filter(SneakerDrop.rarity_tier == rarity)
    if search:
        q = q.filter(SneakerDrop.name.ilike(f"%{search}%"))
    if sort == "date":
        q = q.order_by(SneakerDrop.release_date.asc())
    elif sort == "heat":
        q = q.order_by(desc(SneakerDrop.heat_index))
    elif sort == "price":
        q = q.order_by(SneakerDrop.retail_price.asc())
    elif sort == "rarity":
        q = q.order_by(SneakerDrop.production_number.asc())
    else:
        q = q.order_by(SneakerDrop.name.asc())
    return q.offset(offset).limit(limit).all()


@app.get("/api/drops/{drop_id}", response_model=DropOut)
async def get_drop(drop_id: int, db: Session = Depends(get_db)):
    drop = db.query(SneakerDrop).get(drop_id)
    if not drop:
        raise HTTPException(404, "Drop not found")
    return drop


@app.get("/api/portfolio", response_model=list[PortfolioItemOut])
async def get_portfolio(db: Session = Depends(get_db)):
    return db.query(PortfolioItem).order_by(desc(PortfolioItem.created_at)).all()


@app.post("/api/portfolio", response_model=PortfolioItemOut)
async def add_portfolio_item(item: PortfolioItemIn, db: Session = Depends(get_db)):
    purchase_dt = None
    if item.purchase_date:
        try:
            purchase_dt = datetime.fromisoformat(item.purchase_date)
        except Exception:
            purchase_dt = None
    db_item = PortfolioItem(
        name=item.name, brand=item.brand, size=item.size,
        purchase_price=item.purchase_price, purchase_date=purchase_dt,
        condition=item.condition, image_url=item.image_url,
        style_code=item.style_code, notes=item.notes,
        current_value=item.purchase_price,
    )
    db.add(db_item)
    db.commit()
    db.refresh(db_item)
    asyncio.ensure_future(_update_item_resale(db_item.id, item.style_code, item.name))
    return db_item


@app.delete("/api/portfolio/{item_id}")
async def delete_portfolio_item(item_id: int, db: Session = Depends(get_db)):
    item = db.query(PortfolioItem).get(item_id)
    if not item:
        raise HTTPException(404, "Item not found")
    db.delete(item)
    db.commit()
    return {"deleted": True}


@app.get("/api/portfolio/stats")
async def get_portfolio_stats(db: Session = Depends(get_db)):
    items = db.query(PortfolioItem).all()
    if not items:
        return {"total_invested": 0, "current_value": 0, "total_pnl": 0, "pnl_pct": 0, "best_performer": None, "count": 0}
    total_cost = sum(i.purchase_price for i in items)
    total_val = sum(i.current_value or i.purchase_price for i in items)
    pnl = total_val - total_cost
    best = max(items, key=lambda i: (i.current_value or i.purchase_price) - i.purchase_price)
    return {
        "total_invested": round(total_cost, 2),
        "current_value": round(total_val, 2),
        "total_pnl": round(pnl, 2),
        "pnl_pct": round(pnl / total_cost * 100, 1) if total_cost > 0 else 0,
        "best_performer": {
            "name": best.name,
            "pnl": round((best.current_value or best.purchase_price) - best.purchase_price, 2),
            "roi": round(((best.current_value or best.purchase_price) - best.purchase_price) / best.purchase_price * 100, 1) if best.purchase_price > 0 else 0,
        },
        "count": len(items),
    }


@app.get("/api/portfolio/snapshots")
async def get_portfolio_snapshots(days: int = 30, db: Session = Depends(get_db)):
    cutoff = datetime.utcnow() - timedelta(days=days)
    snaps = db.query(PortfolioSnapshot).filter(
        PortfolioSnapshot.snapshot_date >= cutoff
    ).order_by(PortfolioSnapshot.snapshot_date.asc()).all()
    return [{"date": s.snapshot_date.isoformat(), "value": s.total_value, "cost": s.total_cost} for s in snaps]


async def _update_item_resale(item_id: int, style_code: str, name: str):
    try:
        await asyncio.sleep(2)
        prices = await scrape_resale_price(style_code, name)
        db = SessionLocal()
        item = db.query(PortfolioItem).get(item_id)
        if item:
            best = prices["stockx_price"] or prices["goat_price"]
            if best:
                item.current_value = best
                if item.purchase_price > 0:
                    roi = (best - item.purchase_price) / item.purchase_price
                    if roi > 1.5:
                        item.sell_signal = "Strong Sell"
                    elif roi > 0.5:
                        item.sell_signal = "Consider Sell"
                    else:
                        item.sell_signal = "Hold"
            db.commit()
        db.close()
    except Exception as e:
        logger.error(f"Item resale update error: {e}")


@app.get("/api/leaks", response_model=list[LeakOut])
async def get_leaks(db: Session = Depends(get_db)):
    return db.query(ProductionLeak).order_by(ProductionLeak.production_number.asc()).all()


@app.post("/api/leaks", response_model=LeakOut)
async def add_leak(leak: LeakIn, db: Session = Depends(get_db)):
    db_leak = ProductionLeak(
        shoe_name=leak.shoe_name, production_number=leak.production_number,
        source_url=leak.source_url, confidence=leak.confidence, submitted_by="user",
    )
    db.add(db_leak)
    db.commit()
    db.refresh(db_leak)
    drop = db.query(SneakerDrop).filter(
        SneakerDrop.name.ilike(f"%{leak.shoe_name[:30]}%")
    ).first()
    if drop:
        drop.production_number = leak.production_number
        drop.production_confidence = leak.confidence
        drop.production_source = leak.source_url
        drop.rarity_tier = _classify_rarity(leak.production_number)
        heat = _compute_heat_index(leak.production_number, drop.hype_score, drop.resale_multiple, drop.velocity_score)
        drop.heat_index = heat["heat_index"]
        drop.scarcity_score = heat["scarcity_score"]
        db.commit()
    return db_leak


@app.get("/api/leaks/rarity-distribution")
async def get_rarity_distribution(db: Session = Depends(get_db)):
    drops = db.query(SneakerDrop.rarity_tier, func.count(SneakerDrop.id)).group_by(SneakerDrop.rarity_tier).all()
    return {tier: count for tier, count in drops}


@app.get("/api/raffles")
async def get_raffles():
    raffles = await scrape_raffles()
    return raffles


@app.post("/api/cop/bookmarklet")
async def generate_bookmarklet(name: str = "", email: str = "", phone: str = "", size: str = "", zip_code: str = ""):
    script = f"javascript:void(function(){{var n='{name}';var e='{email}';var p='{phone}';var s='{size}';var z='{zip_code}';document.querySelectorAll('input').forEach(function(i){{var nm=(i.name||'').toLowerCase();var ph=(i.placeholder||'').toLowerCase();var t=nm+' '+ph;if(/name|full.?name|first.?name/.test(t))i.value=n;if(/email|e-mail/.test(t))i.value=e;if(/phone|tel|mobile/.test(t))i.value=p;if(/size|shoe.?size/.test(t))i.value=s;if(/zip|postal|postcode/.test(t))i.value=z;i.dispatchEvent(new Event('input',{{bubbles:true}}));i.dispatchEvent(new Event('change',{{bubbles:true}}))}});alert('SoleOracle Autofill Complete!')}})())"
    return {"bookmarklet": script}


@app.get("/api/cop/raffle-templates")
async def get_raffle_templates(name: str = "Sneakerhead", size: str = "10"):
    return {
        "discord": f"Hey! I'd love to enter the raffle! Name: {name} Size: US {size}",
        "instagram": f"Entering for my size {size}! @SoleOracle keeping me informed on every drop.",
    }


@app.post("/api/scrapers/run")
async def trigger_scrapers(target: str = "all"):
    if target in ("all", "drops"):
        asyncio.ensure_future(run_drop_scrapers())
    if target in ("all", "production"):
        asyncio.ensure_future(run_production_scraper())
    if target in ("all", "resale"):
        asyncio.ensure_future(run_resale_updater())
    return {"triggered": target, "status": "running"}


@app.get("/api/scrapers/logs")
async def get_scraper_logs(limit: int = 20, db: Session = Depends(get_db)):
    logs = db.query(ScraperLog).order_by(desc(ScraperLog.run_at)).limit(limit).all()
    return [{"id": l.id, "scraper": l.scraper_name, "status": l.status,
             "message": l.message, "items_found": l.items_found,
             "run_at": l.run_at.isoformat() if l.run_at else None} for l in logs]


@app.get("/api/scheduler/status")
async def scheduler_status():
    jobs = scheduler.get_jobs()
    return {
        "running": scheduler.running,
        "jobs": [{"id": j.id, "name": j.name,
                  "next_run": j.next_run_time.isoformat() if j.next_run_time else None,
                  "trigger": str(j.trigger)} for j in jobs],
    }


@app.get("/api/digest")
async def get_weekly_digest(db: Session = Depends(get_db)):
    top_drops = db.query(SneakerDrop).order_by(desc(SneakerDrop.heat_index)).limit(10).all()
    items = db.query(PortfolioItem).all()
    total_cost = sum(i.purchase_price for i in items) if items else 0
    total_val = sum(i.current_value or i.purchase_price for i in items) if items else 0
    rarity_dist = db.query(SneakerDrop.rarity_tier, func.count(SneakerDrop.id)).group_by(SneakerDrop.rarity_tier).all()
    snaps = db.query(PortfolioSnapshot).order_by(desc(PortfolioSnapshot.snapshot_date)).limit(30).all()
    return {
        "generated_at": datetime.utcnow().isoformat(),
        "top_drops": [{"name": d.name, "heat_index": d.heat_index, "rarity_tier": d.rarity_tier,
                       "retail_price": d.retail_price, "production_number": d.production_number} for d in top_drops],
        "portfolio": {"total_invested": round(total_cost, 2), "current_value": round(total_val, 2),
                      "pnl": round(total_val - total_cost, 2), "count": len(items)},
        "rarity_distribution": {r: c for r, c in rarity_dist},
        "snapshots": [{"date": s.snapshot_date.isoformat(), "value": s.total_value, "cost": s.total_cost} for s in reversed(snaps)],
    }


@app.get("/api/export")
async def export_data(db: Session = Depends(get_db)):
    drops = db.query(SneakerDrop).all()
    items = db.query(PortfolioItem).all()
    leaks = db.query(ProductionLeak).all()
    return {
        "exported_at": datetime.utcnow().isoformat(),
        "drops": [{"name": d.name, "brand": d.brand, "colorway": d.colorway,
                   "style_code": d.style_code, "retail_price": d.retail_price,
                   "release_date": d.release_date.isoformat() if d.release_date else None,
                   "production_number": d.production_number, "heat_index": d.heat_index,
                   "rarity_tier": d.rarity_tier} for d in drops],
        "portfolio": [{"name": i.name, "size": i.size, "purchase_price": i.purchase_price,
                       "current_value": i.current_value, "condition": i.condition} for i in items],
        "leaks": [{"shoe_name": l.shoe_name, "production_number": l.production_number,
                   "confidence": l.confidence, "source_url": l.source_url} for l in leaks],
    }
