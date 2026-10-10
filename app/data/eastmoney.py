"""东方财富公开行情。日 K 用前复权，避免分红把均线拉开。"""

import asyncio

import httpx

from app.data.parse import fnum, secid
from app.engine.levels import Bar

HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Referer": "https://quote.eastmoney.com/",
}
HOSTS = (
    "https://push2.eastmoney.com",
    "https://82.push2.eastmoney.com",
    "https://17.push2.eastmoney.com",
)
HIS_HOSTS = (
    "https://push2his.eastmoney.com",
    "https://82.push2his.eastmoney.com",
)
UT = "fa5fd1943c7b386f172d6893dbfba10b"
SPOT_FS = "m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23"
SPOT_FIELDS = "f2,f3,f5,f6,f8,f10,f12,f14,f15,f16,f17,f18,f20,f21,f100,f103"


def _diff(data: dict | None) -> list[dict]:
    if not data:
        return []
    diff = data.get("diff") or []
    if isinstance(diff, dict):
        return [v for v in diff.values() if isinstance(v, dict)]
    return [row for row in diff if isinstance(row, dict)]


async def _get(client: httpx.AsyncClient, hosts: tuple[str, ...], path: str, params: dict) -> dict | None:
    last = None
    for host in hosts:
        try:
            resp = await client.get(host + path, params=params, headers=HEADERS)
            resp.raise_for_status()
            body = resp.json()
            if body.get("data"):
                return body["data"]
            last = body
        except (httpx.HTTPError, ValueError):
            continue
    return last.get("data") if isinstance(last, dict) else None


async def _spot_page(client: httpx.AsyncClient, page: int) -> tuple[list[dict], int]:
    data = await _get(
        client,
        HOSTS,
        "/api/qt/clist/get",
        {
            "pn": page,
            "pz": 200,
            "po": 1,
            "np": 1,
            "ut": UT,
            "fltt": 2,
            "invt": 2,
            "fid": "f6",
            "fs": SPOT_FS,
            "fields": SPOT_FIELDS,
        },
    )
    total = int((data or {}).get("total") or 0)
    return _diff(data), total


async def fetch_spot(client: httpx.AsyncClient) -> list[dict]:
    first, total = await _spot_page(client, 1)
    rows = list(first)
    pages = min(40, max(1, (total + 199) // 200)) if total else 1
    for start in range(2, pages + 1, 6):
        batch = range(start, min(start + 6, pages + 1))
        chunks = await asyncio.gather(*(_spot_page(client, page) for page in batch))
        for chunk, _total in chunks:
            rows.extend(chunk)
    return [_spot_row(raw) for raw in rows if raw.get("f12")]


def _spot_row(raw: dict) -> dict:
    code = str(raw.get("f12") or "").zfill(6)
    concepts = raw.get("f103") or ""
    if not isinstance(concepts, str):
        concepts = ""
    price = fnum(raw.get("f2"))
    amount = fnum(raw.get("f6"), 0) or 0
    volume = fnum(raw.get("f5"), 0) or 0
    return {
        "code": code,
        "name": str(raw.get("f14") or ""),
        "price": price,
        "pct": fnum(raw.get("f3"), 0.0) or 0.0,
        "high": fnum(raw.get("f15")),
        "low": fnum(raw.get("f16")),
        "open": fnum(raw.get("f17")),
        "prev_close": fnum(raw.get("f18")),
        "volume": volume,
        "amount": amount,
        "volume_ratio": fnum(raw.get("f10")),
        "total_mv": fnum(raw.get("f20"), 0) or 0,
        "circ_mv": fnum(raw.get("f21"), 0) or 0,
        "industry": "" if str(raw.get("f100") or "").strip() in {"", "-", "—"} else str(raw.get("f100")).strip(),
        "concepts": [c.strip() for c in concepts.split(",") if c.strip()],
        "suspended": price is None or price <= 0 or amount <= 0,
    }


async def fetch_boards(client: httpx.AsyncClient, kind: str) -> list[dict]:
    fs = "m:90+t:2+f:!50" if kind == "industry" else "m:90+t:3+f:!50"
    rows: list[dict] = []
    page = 1
    while page <= 8:
        data = await _get(
            client,
            HOSTS,
            "/api/qt/clist/get",
            {
                "pn": page,
                "pz": 200,
                "po": 1,
                "np": 1,
                "ut": UT,
                "fltt": 2,
                "invt": 2,
                "fid": "f3",
                "fs": fs,
                "fields": "f12,f14,f2,f3,f6,f62",
            },
        )
        chunk = _diff(data)
        if not chunk:
            break
        for raw in chunk:
            name = str(raw.get("f14") or "").strip()
            if not name:
                continue
            rows.append(
                {
                    "code": str(raw.get("f12") or ""),
                    "name": name,
                    "pct": fnum(raw.get("f3"), 0.0) or 0.0,
                    "amount": fnum(raw.get("f6"), 0) or 0,
                    "inflow": fnum(raw.get("f62")),
                }
            )
        if len(chunk) < 200:
            break
        page += 1
    rows.sort(key=lambda r: r["pct"], reverse=True)
    return rows


async def attach_board_flows(client: httpx.AsyncClient, boards: list[dict]) -> None:
    """近几日主力净流入。整批都拿不到就停，避免东财断开时把刷新拖死。"""
    targets = [board for board in boards if str(board.get("code") or "").startswith("BK")]
    for start in range(0, len(targets), 6):
        chunk = targets[start : start + 6]
        results = await asyncio.gather(*(fetch_board_flow(client, board["code"]) for board in chunk), return_exceptions=True)
        failed = 0
        for board, result in zip(chunk, results):
            if isinstance(result, Exception) or not result:
                failed += 1
                continue
            board["inflows"] = result
            if board.get("inflow") is None:
                board["inflow"] = result[-1]["inflow"]
        if failed == len(chunk):
            break


async def fetch_board_flow(client: httpx.AsyncClient, code: str) -> list[dict]:
    data = await _get(
        client,
        HIS_HOSTS,
        "/api/qt/stock/fflow/daykline/get",
        {
            "lmt": 5,
            "klt": 101,
            "secid": f"90.{code}",
            "fields1": "f1,f2,f3,f7",
            "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61,f62,f63,f64,f65",
            "ut": UT,
        },
    )
    out = []
    for line in (data or {}).get("klines") or []:
        parts = str(line).split(",")
        if len(parts) < 2:
            continue
        inflow = fnum(parts[1])
        if inflow is None:
            continue
        out.append({"date": parts[0], "inflow": inflow})
    return out


async def fetch_index_quotes(client: httpx.AsyncClient) -> dict[str, dict]:
    data = await _get(
        client,
        HOSTS,
        "/api/qt/ulist.np/get",
        {
            "fltt": 2,
            "invt": 2,
            "ut": UT,
            "secids": "1.000001,0.399001,0.399006",
            "fields": "f2,f3,f6,f12,f14,f15,f16,f17,f18",
        },
    )
    out = {}
    for raw in _diff(data):
        code = str(raw.get("f12") or "")
        out[code] = {
            "code": code,
            "name": str(raw.get("f14") or ""),
            "price": fnum(raw.get("f2"), 0) or 0,
            "pct": fnum(raw.get("f3"), 0) or 0,
            "amount": fnum(raw.get("f6"), 0) or 0,
            "high": fnum(raw.get("f15"), 0) or 0,
            "low": fnum(raw.get("f16"), 0) or 0,
            "open": fnum(raw.get("f17"), 0) or 0,
            "prev_close": fnum(raw.get("f18"), 0) or 0,
        }
    return out


async def fetch_kline(client: httpx.AsyncClient, code: str, qfq: bool = True, index: bool = False) -> list[Bar]:
    data = await _get(
        client,
        HIS_HOSTS,
        "/api/qt/stock/kline/get",
        {
            "secid": secid(code, index=index),
            "klt": 101,
            "fqt": 1 if qfq else 0,
            "lmt": 120,
            "end": "20500101",
            "ut": UT,
            "fields1": "f1,f2,f3,f4,f5,f6",
            "fields2": "f51,f52,f53,f54,f55,f56,f57",
        },
    )
    lines = (data or {}).get("klines") or []
    bars: list[Bar] = []
    for line in lines:
        parts = str(line).split(",")
        if len(parts) < 7:
            continue
        bars.append(
            Bar(
                trade_date=parts[0],
                open=fnum(parts[1], 0) or 0,
                close=fnum(parts[2], 0) or 0,
                high=fnum(parts[3], 0) or 0,
                low=fnum(parts[4], 0) or 0,
                volume=fnum(parts[5], 0) or 0,
                amount=fnum(parts[6], 0) or 0,
            )
        )
    bars.sort(key=lambda b: b.trade_date)
    return bars
