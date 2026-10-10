"""场内 ETF 现货与日 K（东财 ulist / kline），按白名单拉取。"""

from __future__ import annotations

import asyncio

import httpx

from app.config_etf import etf_by_code
from app.data import eastmoney
from app.data.parse import fnum, secid
from app.engine.levels import Bar

HEADERS = eastmoney.HEADERS
HOSTS = eastmoney.HOSTS
UT = eastmoney.UT


async def fetch_etf_spot(client: httpx.AsyncClient, codes: list[str] | None = None) -> dict[str, dict]:
    """返回 code -> 现货行。"""
    wanted = codes or list(etf_by_code())
    wanted = [str(c).zfill(6) for c in wanted]
    out: dict[str, dict] = {}
    for start in range(0, len(wanted), 40):
        chunk = wanted[start : start + 40]
        secids = ",".join(secid(code) for code in chunk)
        data = await eastmoney._get(
            client,
            HOSTS,
            "/api/qt/ulist.np/get",
            {
                "fltt": 2,
                "invt": 2,
                "ut": UT,
                "secids": secids,
                "fields": "f2,f3,f5,f6,f8,f10,f12,f14,f15,f16,f17,f18",
            },
        )
        for raw in eastmoney._diff(data):
            code = str(raw.get("f12") or "").zfill(6)
            if not code:
                continue
            price = fnum(raw.get("f2"))
            amount = fnum(raw.get("f6"), 0) or 0
            out[code] = {
                "code": code,
                "name": str(raw.get("f14") or ""),
                "price": price,
                "pct": fnum(raw.get("f3"), 0.0) or 0.0,
                "high": fnum(raw.get("f15")),
                "low": fnum(raw.get("f16")),
                "open": fnum(raw.get("f17")),
                "prev_close": fnum(raw.get("f18")),
                "volume": fnum(raw.get("f5"), 0) or 0,
                "amount": amount,
                "volume_ratio": fnum(raw.get("f10")),
                "turnover": fnum(raw.get("f8")),
                "suspended": price is None or price <= 0 or amount <= 0,
            }
    return out


async def fetch_etf_kline(client: httpx.AsyncClient, code: str) -> list[Bar]:
    """ETF 日 K：复用东财个股 K 线接口（51/15/58 等 secid 规则）。"""
    return await eastmoney.fetch_kline(client, str(code).zfill(6), qfq=True, index=False)


async def fill_etf_bars(
    client: httpx.AsyncClient,
    db,
    codes: list[str],
    *,
    limit: int = 8,
) -> int:
    """批补日 K 写入 daily_bars，返回成功条数。"""
    filled = 0
    for code in codes[:limit]:
        try:
            bars = await fetch_etf_kline(client, code)
            if len(bars) < 20:
                continue
            db.replace_bars(code, bars)
            filled += 1
        except Exception:
            continue
        await asyncio.sleep(0.05)
    return filled
