"""新浪行情。东财被重置时用它补指数、全市场、行业和日 K。日 K 不复权。"""

import asyncio
import json
import re

import httpx

from app.data.parse import fnum
from app.engine.levels import Bar

HEADERS = {"User-Agent": "Mozilla/5.0", "Referer": "https://finance.sina.com.cn"}
SPOT_URL = "https://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/Market_Center.getHQNodeData"
KLINE_URL = "https://money.finance.sina.com.cn/quotes_service/api/json_v2.php/CN_MarketData.getKLineData"
INDUSTRY_URL = "https://vip.stock.finance.sina.com.cn/q/view/newSinaHy.php"
NODE_URL = SPOT_URL


def symbol_of(code: str, index: bool = False) -> str:
    if index and code.startswith("000"):
        return "sh" + code
    if index or code.startswith(("39", "15")):
        return "sz" + code
    if code.startswith(("6", "9", "5")):
        return "sh" + code
    return "sz" + code


async def _text(client: httpx.AsyncClient, url: str, params: dict | None = None, encoding: str = "utf-8") -> str:
    resp = await client.get(url, params=params, headers=HEADERS)
    resp.raise_for_status()
    return resp.content.decode(encoding, errors="replace")


async def fetch_index_quotes(client: httpx.AsyncClient) -> dict[str, dict]:
    raw = await _text(client, "https://hq.sinajs.cn/list=sh000001,sz399001,sz399006", encoding="gbk")
    out = {}
    for line in raw.split(";"):
        if "hq_str_" not in line or "=" not in line:
            continue
        left, right = line.split("=", 1)
        code = left.strip().split("_")[-1][-6:]
        body = right.strip().strip('"')
        parts = body.split(",")
        if len(parts) < 10 or not code:
            continue
        price = fnum(parts[3], 0) or 0
        prev = fnum(parts[2], 0) or 0
        out[code] = {
            "code": code,
            "name": parts[0],
            "price": price,
            "pct": ((price / prev) - 1) * 100 if prev else 0,
            "amount": fnum(parts[9], 0) or 0,
            "high": fnum(parts[4], 0) or 0,
            "low": fnum(parts[5], 0) or 0,
            "open": fnum(parts[1], 0) or 0,
            "prev_close": prev,
            "volume": fnum(parts[8], 0) or 0,
        }
    return out


async def fetch_kline(client: httpx.AsyncClient, code: str, index: bool = False) -> list[Bar]:
    raw = await _text(
        client,
        KLINE_URL,
        {"symbol": symbol_of(code, index=index), "scale": 240, "ma": "no", "datalen": 120},
    )
    if not raw or raw.strip() in {"null", "[]"}:
        return []
    try:
        rows = json.loads(raw)
    except json.JSONDecodeError:
        return []
    bars = []
    for row in rows or []:
        bars.append(
            Bar(
                trade_date=str(row.get("day") or "")[:10],
                open=fnum(row.get("open"), 0) or 0,
                high=fnum(row.get("high"), 0) or 0,
                low=fnum(row.get("low"), 0) or 0,
                close=fnum(row.get("close"), 0) or 0,
                volume=fnum(row.get("volume"), 0) or 0,
                amount=0,
            )
        )
    bars.sort(key=lambda b: b.trade_date)
    return bars


async def _spot_page(client: httpx.AsyncClient, page: int) -> list[dict]:
    raw = await _text(client, SPOT_URL, {"page": page, "num": 80, "sort": "amount", "asc": 0, "node": "hs_a"})
    if not raw or raw.strip() in {"null", "[]"}:
        return []
    try:
        rows = json.loads(raw)
    except json.JSONDecodeError:
        return []
    return [_spot_row(row) for row in rows or [] if row.get("code")]


def _spot_row(row: dict) -> dict:
    code = str(row.get("code") or "").zfill(6)
    price = fnum(row.get("trade"))
    amount = fnum(row.get("amount"), 0) or 0
    nmc = fnum(row.get("nmc"), 0) or 0
    mkt = fnum(row.get("mktcap"), 0) or 0
    # 新浪市值单位是万元。
    if nmc and nmc < 1e8:
        nmc *= 1e4
    if mkt and mkt < 1e8:
        mkt *= 1e4
    return {
        "code": code,
        "name": str(row.get("name") or ""),
        "price": price,
        "pct": fnum(row.get("changepercent"), 0) or 0,
        "high": fnum(row.get("high")),
        "low": fnum(row.get("low")),
        "open": fnum(row.get("open")),
        "prev_close": fnum(row.get("settlement")),
        "volume": fnum(row.get("volume"), 0) or 0,
        "amount": amount,
        "volume_ratio": None,
        "total_mv": mkt,
        "circ_mv": nmc,
        "industry": "",
        "concepts": [],
        "suspended": price is None or price <= 0 or amount <= 0,
    }


async def fetch_spot(client: httpx.AsyncClient) -> list[dict]:
    first = await _spot_page(client, 1)
    rows = list(first)
    if len(first) < 80:
        return rows
    page = 2
    while page <= 80:
        batch = range(page, page + 8)
        chunks = await asyncio.gather(*(_spot_page(client, n) for n in batch), return_exceptions=True)
        stop = False
        for chunk in chunks:
            if isinstance(chunk, Exception) or not chunk:
                stop = True
                continue
            rows.extend(chunk)
            if len(chunk) < 80:
                stop = True
        if stop:
            break
        page += 8
    return rows


async def fetch_industries(client: httpx.AsyncClient) -> list[dict]:
    raw = await _text(client, INDUSTRY_URL, encoding="gbk")
    match = re.search(r"=\s*(\{.*\})\s*;?\s*$", raw, re.S)
    if not match:
        return []
    try:
        payload = json.loads(match.group(1))
    except json.JSONDecodeError:
        return []
    rows = []
    for node, packed in payload.items():
        parts = str(packed).split(",")
        if len(parts) < 6:
            continue
        rows.append(
            {
                "code": node,
                "name": parts[1],
                "pct": fnum(parts[5], 0) or 0,
                "amount": fnum(parts[7], 0) or 0 if len(parts) > 7 else 0,
                "count": int(fnum(parts[2], 0) or 0),
            }
        )
    rows.sort(key=lambda r: r["pct"], reverse=True)
    return rows


async def _industry_codes(client: httpx.AsyncClient, node: str, pages: int) -> list[str]:
    codes = []
    for page in range(1, pages + 1):
        raw = await _text(client, NODE_URL, {"page": page, "num": 100, "sort": "amount", "asc": 0, "node": node})
        if not raw or raw.strip() in {"null", "[]"}:
            break
        try:
            rows = json.loads(raw)
        except json.JSONDecodeError:
            break
        if not rows:
            break
        codes.extend(str(row.get("code") or "").zfill(6) for row in rows if row.get("code"))
        if len(rows) < 100:
            break
    return codes


async def fetch_industry_map(client: httpx.AsyncClient, boards: list[dict]) -> dict[str, str]:
    mapping: dict[str, str] = {}

    async def one(board: dict) -> tuple[str, list[str]]:
        pages = 2 if board.get("count", 0) > 100 else 1
        try:
            return board["name"], await _industry_codes(client, board["code"], pages)
        except Exception:
            return board["name"], []

    for start in range(0, len(boards), 8):
        chunk = boards[start : start + 8]
        groups = await asyncio.gather(*(one(board) for board in chunk))
        for name, codes in groups:
            for code in codes:
                mapping.setdefault(code, name)
    return mapping
