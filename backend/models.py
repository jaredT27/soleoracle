"""SoleOracle – SQLAlchemy models for SQLite database."""
from datetime import datetime
from sqlalchemy import (
    Column, Integer, String, Float, DateTime, Text, Boolean, create_engine
)
from sqlalchemy.orm import declarative_base, sessionmaker

DATABASE_URL = "sqlite:///./soleoracle.db"
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


class SneakerDrop(Base):
    """Upcoming sneaker releases scraped from multiple sources."""
    __tablename__ = "sneaker_drops"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    brand = Column(String, nullable=False, index=True)
    colorway = Column(String, default="")
    style_code = Column(String, default="")
    retail_price = Column(Float, nullable=True)
    release_date = Column(DateTime, nullable=True)
    release_time = Column(String, default="")
    image_url = Column(String, default="")
    where_to_buy = Column(Text, default="[]")
    raffle_links = Column(Text, default="[]")

    production_number = Column(Integer, nullable=True)
    production_confidence = Column(String, default="Estimated")
    production_source = Column(String, default="")
    rarity_tier = Column(String, default="Unknown")

    heat_index = Column(Float, default=0.0)
    hype_score = Column(Float, default=0.0)
    scarcity_score = Column(Float, default=0.0)
    resale_multiple = Column(Float, default=0.0)
    velocity_score = Column(Float, default=0.0)

    stockx_price = Column(Float, nullable=True)
    goat_price = Column(Float, nullable=True)
    stockx_url = Column(String, default="")
    goat_url = Column(String, default="")

    source = Column(String, default="")
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class PortfolioItem(Base):
    """User's personal sneaker collection."""
    __tablename__ = "portfolio_items"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    brand = Column(String, default="")
    size = Column(String, default="")
    purchase_price = Column(Float, nullable=False)
    purchase_date = Column(DateTime, nullable=True)
    condition = Column(String, default="DS")
    image_url = Column(String, default="")
    current_value = Column(Float, nullable=True)
    style_code = Column(String, default="")
    notes = Column(Text, default="")
    sell_signal = Column(String, default="Hold")
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class ProductionLeak(Base):
    """User-submitted or scraped production number intelligence."""
    __tablename__ = "production_leaks"

    id = Column(Integer, primary_key=True, index=True)
    shoe_name = Column(String, nullable=False)
    production_number = Column(Integer, nullable=False)
    source_url = Column(String, default="")
    confidence = Column(String, default="Estimated")
    submitted_by = Column(String, default="system")
    created_at = Column(DateTime, default=datetime.utcnow)


class ScraperLog(Base):
    """Logs for scraper runs."""
    __tablename__ = "scraper_logs"

    id = Column(Integer, primary_key=True, index=True)
    scraper_name = Column(String, nullable=False)
    status = Column(String, default="success")
    message = Column(Text, default="")
    items_found = Column(Integer, default=0)
    run_at = Column(DateTime, default=datetime.utcnow)


class PortfolioSnapshot(Base):
    """Daily snapshot of portfolio total value."""
    __tablename__ = "portfolio_snapshots"

    id = Column(Integer, primary_key=True, index=True)
    total_value = Column(Float, nullable=False)
    total_cost = Column(Float, nullable=False)
    snapshot_date = Column(DateTime, default=datetime.utcnow)


Base.metadata.create_all(bind=engine)
