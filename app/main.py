import asyncio
import logging
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Body, FastAPI, Query
from fastapi.responses import FileResponse

from app.config import SPOT_TTL_CLOSED_SEC, SPOT_TTL_OPEN_SEC
from app.engine.session import session_info
from app.service import Hub

log = logging.getLogger("stockdecision")
hub = Hub()
WEB_DIR = Path(__file__).resolve().parent / "web"
LANDING = WEB_DIR / "landing.html"
APP_WEB = WEB_DIR / "index.html"


async def _refresh_loop() -> None:
    while True:
        try:
            await hub.refresh_indices()
            info = session_info()
            ttl = SPOT_TTL_OPEN_SEC if info["open"] else SPOT_TTL_CLOSED_SEC
            if time.time() - hub.provider.spot_at >= ttl:
                await hub.refresh_spot()
                await hub.refresh_indices()
        except Exception:
            log.exception("行情刷新失败")
        info = session_info()
        await asyncio.sleep(15 if info["open"] else 20)


async def _factor_loop() -> None:
    while True:
        try:
            filled = await hub.fill_factors()
        except Exception:
            log.exception("日K因子补齐失败")
            filled = 0
        await asyncio.sleep(0.2 if filled else 2)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    refresh = asyncio.create_task(_refresh_loop())
    factors = asyncio.create_task(_factor_loop())
    try:
        yield
    finally:
        refresh.cancel()
        factors.cancel()
        await hub.close()


app = FastAPI(title="买入时机", lifespan=lifespan)


@app.get("/")
def landing():
    return FileResponse(LANDING)


@app.get("/app")
def app_ui():
    return FileResponse(APP_WEB)


@app.get("/api/health")
def health():
    data = hub.data_health()
    return {
        "ok": True,
        "quotes": len(hub.provider.quotes),
        "price_date": hub.provider.price_date,
        "index_source": hub.provider.index_source,
        "quote_source": hub.provider.quote_source,
        "error": hub.provider.last_error,
        **data,
    }


@app.get("/api/signals")
def signals():
    return hub.signals_payload()


@app.get("/api/market")
def market():
    return hub.market_payload()


@app.get("/api/pool")
def pool():
    return hub.pool_payload()


@app.get("/api/etf/pool")
def etf_pool():
    return hub.etf_payload()


@app.get("/api/stats")
def stats():
    return hub.stats_payload()


@app.get("/api/decide")
async def decide(q: str = Query("")):
    try:
        return await hub.judge(q)
    except Exception:
        log.exception("判断失败")
        return {"error": "failed", "message": "判断时行情中断了，过几秒再试"}


@app.get("/api/report")
async def report(q: str = Query("")):
    try:
        return await hub.report(q)
    except Exception:
        log.exception("研报失败")
        return {
            "error": "failed",
            "message": "研报生成中断了，过几秒再试",
            "changes_verdict": False,
        }


@app.get("/api/positions")
def positions():
    return hub.positions_payload()


@app.post("/api/positions")
def add_position(payload: dict = Body(default={})):
    try:
        return hub.add_position(
            code=str(payload.get("code") or ""),
            name=str(payload.get("name") or ""),
            entry_price=payload.get("entry_price"),
            entry_date=str(payload.get("entry_date") or ""),
            stop_pct=payload.get("stop_pct"),
            note=str(payload.get("note") or ""),
        )
    except Exception:
        log.exception("记入持仓失败")
        return {"error": "failed", "message": "记入持仓失败，过几秒再试"}


@app.post("/api/positions/{code}/close")
def close_position(code: str):
    try:
        return hub.close_position(code)
    except Exception:
        log.exception("了结持仓失败")
        return {"error": "failed", "message": "了结失败，过几秒再试"}
