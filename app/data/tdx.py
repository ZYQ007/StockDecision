"""通达信行情。

本机客户端只向外连接主站，不在 127.0.0.1 上开端口。
这里读取它的 connect.cfg，用同一批主站取现价和日 K。
"""

import threading
import time
from pathlib import Path

from eltdx import TdxClient

from app.config import TDX_HOME
from app.data.parse import fnum
from app.engine.levels import Bar

_lock = threading.Lock()
_client: TdxClient | None = None
_down_until = 0.0
_flow_cache: dict[str, dict[str, float]] = {}
_flow_failed_until: dict[str, float] = {}
_stock_flow_cache: dict[str, dict[str, float]] = {}
_stock_flow_failed_until: dict[str, float] = {}
INDEX_NAMES = {"000001": "上证指数", "399001": "深证成指", "399006": "创业板指"}


def parse_hq_hosts(text: str, limit: int = 12) -> list[str]:
    """取出 [HQHOST] 主站。PrimaryHost 是从 0 开始的序号，排到最前。"""
    ips: dict[int, str] = {}
    ports: dict[int, int] = {}
    primary = -1
    in_hq = False
    for raw in text.splitlines():
        line = raw.strip()
        if line.startswith("[") and line.endswith("]"):
            if in_hq:
                break
            in_hq = line.upper() == "[HQHOST]"
            continue
        if not in_hq or "=" not in line:
            continue
        key, value = line.split("=", 1)
        value = value.strip()
        if key == "PrimaryHost" and value.lstrip("-").isdigit():
            primary = int(value)
        elif key.startswith("IPAddress") and key[9:].isdigit() and value:
            ips[int(key[9:])] = value
        elif key.startswith("Port") and key[4:].isdigit() and value.isdigit():
            ports[int(key[4:])] = int(value)
    order = sorted(ips)
    preferred = primary + 1
    if preferred in ips:
        order = [preferred] + [num for num in order if num != preferred]
    hosts = [f"{ips[num]}:{ports.get(num, 7709)}" for num in order]
    return hosts[:limit]


def fetch_index_quotes() -> dict[str, dict] | None:
    found = _snapshots([(1, "000001"), (0, "399001"), (0, "399006")])
    if not found:
        return None
    out = {}
    for row in found:
        code = str(_field(row, "code") or "")
        price = _field(row, "last_price", 0) or 0
        if price <= 0:
            continue
        prev = _field(row, "pre_close_price", 0) or 0
        out[code] = {
            "code": code,
            "name": INDEX_NAMES.get(code, code),
            "price": price,
            "pct": _pct(price, prev),
            "amount": _field(row, "amount", 0) or 0,
            "high": _field(row, "high_price", 0) or 0,
            "low": _field(row, "low_price", 0) or 0,
            "open": _field(row, "open_price", 0) or 0,
            "prev_close": prev,
            "volume": _field(row, "total_hand", 0) or 0,
        }
    if len(out) < 2:
        _fail()
        return None
    return out


def fetch_amount_leaders(limit: int = 1200) -> list[dict]:
    """沪深 A 股按成交额从高到低。流通市值用流通股本乘现价。"""
    if not _up() or limit <= 0:
        return []
    try:
        with _lock:
            client = _ensure()
        table = client.helpers.realtime_rank(category="沪深A股", sort_by="成交额", count=limit)
    except Exception:
        return []
    rows = []
    symbols = []
    for item in getattr(table, "rows", ()) or ():
        full_code = str(getattr(item, "full_code", "") or "")
        code = full_code[-6:]
        if len(code) != 6 or not code.isdigit():
            continue
        price = _field(item, "last_price", 0) or 0
        amount = _field(item, "amount", 0) or 0
        rows.append(
            {
                "code": code,
                "name": str(getattr(item, "name", "") or ""),
                "price": price,
                "pct": _field(item, "change_pct", 0) or 0,
                "volume": _field(item, "volume_hand", 0) or 0,
                "amount": amount,
                "volume_ratio": None,
                "total_mv": 0,
                "circ_mv": 0,
                "industry": "",
                "concepts": [],
                "suspended": price <= 0 or amount <= 0,
            }
        )
        if full_code:
            symbols.append(full_code)
    shares = _circulating_shares(client, symbols)
    for row in rows:
        count = shares.get(row["code"]) or 0
        if count and row["price"]:
            row["circ_mv"] = count * row["price"]
            row["total_mv"] = row["circ_mv"]
    return rows


def _circulating_shares(client, symbols: list[str]) -> dict[str, float]:
    found: dict[str, float] = {}
    for start in range(0, len(symbols), 80):
        chunk = symbols[start : start + 80]
        try:
            batch = client.corporate.finance_batch(chunk)
        except Exception:
            continue
        for rec in getattr(batch, "records", ()) or ():
            count = getattr(rec, "circulating_shares", 0) or 0
            code = str(getattr(rec, "code", "") or "")
            if code and count > 0:
                found[code] = float(count)
    return found


def fetch_quote(code: str, market: int) -> dict | None:
    found = _snapshots([(market, code)])
    if not found:
        return None
    row = found[0]
    price = _field(row, "last_price", 0) or 0
    if price <= 0:
        return None
    prev = _field(row, "pre_close_price", 0) or 0
    return {
        "price": price,
        "pct": _pct(price, prev),
        "high": _field(row, "high_price", 0) or 0,
        "low": _field(row, "low_price", 0) or 0,
        "open": _field(row, "open_price", 0) or 0,
        "prev_close": prev,
        "volume": _field(row, "total_hand", 0) or 0,
        "amount": _field(row, "amount", 0) or 0,
    }


def prefetch_board_flows(codes: list[str]) -> None:
    """按板块代码取近几日主力净流入。通达信行业、概念指数走上海市场。"""
    now = time.time()
    wanted: list[str] = []
    seen: set[str] = set()
    for code in codes:
        text = str(code or "")
        if not text.isdigit() or text in _flow_cache or text in seen or _flow_failed_until.get(text, 0) > now:
            continue
        seen.add(text)
        wanted.append(text)
    if not wanted or not _up():
        return
    for start in range(0, len(wanted), 30):
        chunk = wanted[start : start + 30]
        try:
            with _lock:
                raw = _ensure().money_flow.daily([f"sh{code}" for code in chunk])
        except Exception:
            until = time.time() + 600
            for code in chunk:
                _flow_failed_until[code] = until
            return
        blocks = list(getattr(raw, "blocks", None) or [])
        if not blocks and getattr(raw, "records", None) is not None:
            blocks = [raw]
        for block in blocks:
            _store_flow(block, _flow_cache)
        # 没返回的代码不写空缓存，否则会一直当成「资金流没有」。


def prefetch_stock_flows(codes: list[str]) -> None:
    """按股票代码取主力净流入。缓存和板块指数分开，避免代码撞车。"""
    from app.data.parse import market_of

    now = time.time()
    wanted: list[str] = []
    seen: set[str] = set()
    for code in codes:
        text = str(code or "")
        if not text.isdigit() or text in _stock_flow_cache or text in seen or _stock_flow_failed_until.get(text, 0) > now:
            continue
        seen.add(text)
        wanted.append(text)
    if not wanted or not _up():
        return
    for start in range(0, len(wanted), 30):
        chunk = wanted[start : start + 30]
        try:
            with _lock:
                raw = _ensure().money_flow.daily([_symbol(market_of(code), code) for code in chunk])
        except Exception:
            until = time.time() + 600
            for code in chunk:
                _stock_flow_failed_until[code] = until
            return
        blocks = list(getattr(raw, "blocks", None) or [])
        if not blocks and getattr(raw, "records", None) is not None:
            blocks = [raw]
        for block in blocks:
            _store_flow(block, _stock_flow_cache)


def stock_inflows(code: str) -> dict[str, float] | None:
    text = str(code or "")
    if not text.isdigit():
        return None
    if text not in _stock_flow_cache and _stock_flow_failed_until.get(text, 0) <= time.time():
        prefetch_stock_flows([text])
    found = _stock_flow_cache.get(text) or {}
    return found or None


def board_inflows(code: str) -> dict[str, float] | None:
    text = str(code or "")
    if not text.isdigit():
        return None
    if text not in _flow_cache and _flow_failed_until.get(text, 0) <= time.time():
        prefetch_board_flows([text])
    found = _flow_cache.get(text) or {}
    return found or None


def _store_flow(block, cache: dict[str, dict[str, float]]) -> None:
    code = str(getattr(block, "code", "") or "")
    if not code:
        return
    mapping: dict[str, float] = {}
    for rec in getattr(block, "records", ()) or ():
        day = _trade_date(getattr(rec, "date", ""))
        net = getattr(rec, "main_net", None)
        if day and net is not None:
            mapping[day] = float(net)
    cache[code] = mapping


def fetch_bars(code: str, market: int, index: bool = False) -> list[Bar]:
    del index
    if not _up():
        return []
    try:
        with _lock:
            page = _ensure().bars.get(_symbol(market, code), period="day", count=120)
    except Exception:
        _fail()
        return []
    bars = []
    for row in getattr(page, "bars", None) or []:
        trade_date = _trade_date(_field(row, "time", ""))
        close = _field(row, "close", 0) or 0
        if not trade_date or close <= 0:
            continue
        bars.append(
            Bar(
                trade_date=trade_date,
                open=_field(row, "open", 0) or 0,
                high=_field(row, "high", 0) or 0,
                low=_field(row, "low", 0) or 0,
                close=close,
                volume=_field(row, "volume_lots", 0) or 0,
                amount=_field(row, "amount", 0) or 0,
            )
        )
    bars.sort(key=lambda item: item.trade_date)
    return bars


def _snapshots(pairs: list[tuple[int, str]]):
    if not _up():
        return None
    try:
        with _lock:
            raw = _ensure().quotes.get_snapshots([_symbol(market, code) for market, code in pairs])
    except Exception:
        _fail()
        return None
    rows = list(raw or [])
    if not rows:
        _fail()
        return None
    return rows


def _ensure() -> TdxClient:
    global _client
    if _client is None:
        _client = TdxClient.from_hosts(
            _hosts(),
            timeout=5,
            probe_hosts=True,
            probe_timeout=1.5,
            server_count=1,
            heartbeat_interval=30,
        )
    return _client


def _hosts() -> list[str]:
    path = Path(TDX_HOME) / "connect.cfg"
    if path.is_file():
        text = path.read_bytes().decode("gbk", errors="replace")
        found = parse_hq_hosts(text)
        if found:
            return found
    from eltdx.hosts import FALLBACK_HOSTS

    return list(FALLBACK_HOSTS[:12])


def _symbol(market: int, code: str) -> str:
    if code.startswith(("4", "8", "92")):
        return f"bj{code}"
    return f"{'sh' if market == 1 else 'sz'}{code}"


def _field(row, name: str, default=None):
    if isinstance(row, dict):
        value = row.get(name, default)
    else:
        value = getattr(row, name, default)
    if default is None or isinstance(default, str):
        return value if value is not None else default
    return fnum(value, default)


def _trade_date(value) -> str:
    if hasattr(value, "strftime"):
        return value.strftime("%Y-%m-%d")
    text = str(value or "")
    return text[:10] if len(text) >= 10 else ""


def _pct(price: float, prev: float) -> float:
    if prev <= 0:
        return 0.0
    return (price / prev - 1) * 100


def _up() -> bool:
    return time.time() >= _down_until


def _fail() -> None:
    global _client, _down_until
    _down_until = time.time() + 600
    with _lock:
        client, _client = _client, None
    if client is not None:
        try:
            client.close()
        except Exception:
            pass
