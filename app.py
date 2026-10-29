"""Minimal app to reproduce one bug: a database connection held while waiting for a slow external API.

Two endpoints do the same thing (charge an order through an external payment API):
- POST /orders/{id}/pay-buggy  keeps the transaction open during the external call
- POST /orders/{id}/pay        commits first, so the connection goes back to the pool
GET /orders/{id} never calls the external API. It is the "unrelated page" the load test measures.
"""

import os

import httpx
from fastapi import Depends, FastAPI, HTTPException, Query
from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./demo.db")
EXTERNAL_API = os.getenv("EXTERNAL_API", "http://127.0.0.1:9100")

# SQLAlchemy's default pool: 5 connections + 10 overflow = 15, wait up to 30 s for a free one
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {})
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)

# Tests replace this with httpx.MockTransport, so no real external API is needed
transport: httpx.BaseTransport | None = None


class Base(DeclarativeBase):
    pass


class Order(Base):
    __tablename__ = "orders"
    id: Mapped[int] = mapped_column(primary_key=True)
    total: Mapped[int]
    status: Mapped[str] = mapped_column(default="new")


Base.metadata.create_all(engine)
app = FastAPI()


def get_db():
    with SessionLocal() as db:
        yield db


def charge(amount: int) -> str:
    try:
        with httpx.Client(transport=transport, timeout=15) as client:
            res = client.post(f"{EXTERNAL_API}/charge", json={"amount": amount})
            res.raise_for_status()
            return str(res.json()["status"])
    except (httpx.HTTPError, ValueError, KeyError) as e:
        # The external API's own error text is not passed on to the caller
        raise HTTPException(502, "Payment service unavailable") from e


def load(db: Session, order_id: int) -> Order:
    order = db.get(Order, order_id)
    if order is None:
        raise HTTPException(404, "Order not found")
    return order


@app.post("/orders", status_code=201)
def create_order(total: int = Query(100, gt=0, le=1_000_000), db: Session = Depends(get_db)):
    order = Order(total=total)
    db.add(order)
    db.commit()
    return {"id": order.id}


@app.get("/orders/{order_id}")
def read_order(order_id: int, db: Session = Depends(get_db)):
    order = load(db, order_id)
    return {"id": order.id, "total": order.total, "status": order.status}


@app.post("/orders/{order_id}/pay-buggy")
def pay_buggy(order_id: int, db: Session = Depends(get_db)):
    order = load(db, order_id)  # transaction starts, connection taken from the pool
    order.status = charge(order.total)  # waits for the external API with the connection checked out
    db.commit()  # connection goes back only here
    return {"id": order.id, "status": order.status}


@app.post("/orders/{order_id}/pay")
def pay(order_id: int, db: Session = Depends(get_db)):
    order = load(db, order_id)
    amount = order.total
    db.commit()  # connection back to the pool before the slow call
    status = charge(amount)
    order.status = status
    db.commit()
    return {"id": order.id, "status": order.status}
