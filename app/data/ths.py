"""同花顺行业、概念和板块指数。东财所属板块只在同花顺页面失败时备用。"""

import json
import re
from datetime import datetime

import httpx

from app.data.parse import market_of

HEADERS = {"User-Agent": "Mozilla/5.0", "Referer": "https://q.10jqka.com.cn/"}
BROAD_WORDS = (
    "融资融券",
    "沪股通",
    "深股通",
    "港股通",
    "标准普尔",
    "富时罗素",
    "MSCI",
    "沪深300",
    "HS300",
    "上证50",
    "上证180",
    "上证380",
    "中证500",
    "中证1000",
    "中证800",
    "创业板综",
    "创业板指",
    "深证成指",
    "百元股",
    "大盘股",
    "中盘股",
    "小盘股",
    "权重股",
    "行业龙头",
    "东方财富热股",
    "央视50",
    "证金持股",
    "社保重仓",
    "基金重仓",
    "机构重仓",
    "股权分散",
    "高送转",
    "次新股",
    "消费风格",
)
def is_broad(name: str) -> bool:
    text = name or ""
    if any(word in text for word in BROAD_WORDS):
        return True
    return text.endswith("板块") and "概念" not in text


def parse_catalog(html: str, kind: str) -> list[dict]:
    path = "thshy" if kind == "行业" else "gn"
    found = re.findall(rf"{path}/detail/code/(\d+)/\"[^>]*>([^<]+)</a>", html)
    rows = []
    seen = set()
    for code, name in found:
        name = name.strip()
        if not name or code in seen or is_broad(name):
            continue
        seen.add(code)
        rows.append({"code": code, "name": name, "kind": kind})
    return rows


def parse_stock_page(field_html: str, concept_html: str, catalog: dict[str, dict]) -> dict:
    industry = None
    match = re.search(r"field/0*(\d{6})/", field_html)
    level = re.search(r"三级行业分类：.*?<span[^>]*>(.*?)</span>", field_html, re.S)
    level_text = re.sub(r"<[^>]+>", "", level.group(1)).strip() if level else ""
    level3 = level_text.split("--")[-1].split("（")[0].strip() if level_text else ""
    if match:
        code = match.group(1)
        known = catalog.get(code) or {}
        industry = {
            "code": code,
            "name": known.get("name") or level3 or code,
            "level3": level3,
            "kind": "行业",
            "core_hint": True,
        }
    concepts = []
    for code, name in re.findall(r'class="gnName"\s+clid="(\d+)"\s*>\s*([^<]+)', concept_html):
        name = name.strip()
        if not name or is_broad(name):
            continue
        kind = "指数" if "指数" in name else "概念"
        concepts.append({"code": code, "name": name, "kind": kind, "core_hint": False, "level3": ""})
    return {"industry": industry, "boards": concepts}


def mark_core_hints(concept_html: str, stock_code: str, boards: list[dict]) -> None:
    for board in boards:
        chunk = _chunk_after(concept_html, board["code"])
        leaders = set(re.findall(r'class="gnltg"[^>]*code="(\d{6})"', chunk))
        board["core_hint"] = stock_code in leaders


def parse_members(html: str) -> list[tuple[str, float | None]]:
    members = []
    seen = set()
    for tr in re.findall(r"<tr>(.*?)</tr>", html, re.S):
        code = re.search(r"stockpage\.10jqka\.com\.cn/(\d{6})/", tr)
        if not code:
            continue
        symbol = code.group(1)
        if symbol in seen:
            continue
        seen.add(symbol)
        amounts = [_cn_amount(token) for token in re.findall(r">([\d.]+(?:亿|万))<", tr)]
        members.append((symbol, amounts[0] if amounts else None))
    return members


def parse_board_closes(text: str) -> list[tuple[str, float]]:
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end <= start:
        return []
    try:
        payload = json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return []
    rows = []
    for item in str(payload.get("data") or "").split(";"):
        parts = item.split(",")
        if len(parts) < 5 or len(parts[0]) != 8:
            continue
        close = _float(parts[4])
        if close is None:
            continue
        trade_date = f"{parts[0][:4]}-{parts[0][4:6]}-{parts[0][6:8]}"
        rows.append((trade_date, close))
    return rows


def amount_rank_pct(members: list[tuple[str, float | None]], code: str) -> float | None:
    known = [(symbol, amount) for symbol, amount in members if amount]
    if not any(symbol == code for symbol, _amount in known):
        return None
    ordered = sorted(known, key=lambda item: item[1], reverse=True)
    rank = next(index for index, (symbol, _amount) in enumerate(ordered, start=1) if symbol == code)
    return rank / len(ordered)


async def fetch_catalog(client: httpx.AsyncClient) -> list[dict]:
    industry = await _text(client, "https://q.10jqka.com.cn/thshy/")
    concept = await _text(client, "https://q.10jqka.com.cn/gn/")
    return parse_catalog(industry, "行业") + parse_catalog(concept, "概念")


async def fetch_stock_boards(client: httpx.AsyncClient, code: str, catalog: dict[str, dict]) -> dict | None:
    field = await _text(client, f"https://basic.10jqka.com.cn/{code}/field.html")
    concept = await _text(client, f"https://basic.10jqka.com.cn/{code}/concept.html")
    parsed = parse_stock_page(field, concept, catalog)
    if parsed["industry"] or parsed["boards"]:
        mark_core_hints(concept, code, parsed["boards"])
        parsed["source"] = "同花顺"
        return parsed
    return await fetch_em_boards(client, code)


async def fetch_em_boards(client: httpx.AsyncClient, code: str) -> dict | None:
    prefix = "SH" if market_of(code) == 1 else "SZ"
    try:
        resp = await client.get(
            "https://emweb.securities.eastmoney.com/PC_HSF10/CoreConception/PageAjax",
            params={"code": f"{prefix}{code}"},
            headers={**HEADERS, "Referer": "https://emweb.securities.eastmoney.com/"},
        )
        resp.raise_for_status()
        rows = resp.json().get("ssbk") or []
    except (httpx.HTTPError, ValueError):
        return None
    industry = None
    boards = []
    for row in rows:
        name = str(row.get("BOARD_NAME") or "").strip()
        board_code = str(row.get("BOARD_CODE") or "").strip()
        if not name or not board_code or is_broad(name):
            continue
        if name.endswith("Ⅲ") and industry is None:
            industry = {"code": board_code, "name": name, "level3": name, "kind": "行业", "core_hint": True}
            continue
        if name.endswith(("Ⅱ", "Ⅰ")):
            continue
        kind = "指数" if "指数" in name else "概念"
        precise = str(row.get("IS_PRECISE") or "") == "1"
        boards.append({"code": board_code, "name": name, "kind": kind, "core_hint": precise, "level3": ""})
    if not industry and not boards:
        return None
    return {"industry": industry, "boards": boards, "source": "东财"}


async def fetch_members(client: httpx.AsyncClient, board_code: str, kind: str) -> list[tuple[str, float | None]]:
    path = "thshy" if kind == "行业" else "gn"
    html = await _text(client, f"https://q.10jqka.com.cn/{path}/detail/code/{board_code}/")
    return parse_members(html)


async def fetch_closes(client: httpx.AsyncClient, board_code: str) -> list[tuple[str, float]]:
    year = datetime.now().year
    rows = parse_board_closes(await _text(client, f"https://d.10jqka.com.cn/v4/line/bk_{board_code}/01/{year}.js"))
    # 今年条数不够，或还没跨过年初，都把上年拼上，避免只剩去年底的旧序列。
    if len(rows) < 60:
        older = parse_board_closes(await _text(client, f"https://d.10jqka.com.cn/v4/line/bk_{board_code}/01/{year - 1}.js"))
        rows = older + rows
    return rows


async def _text(client: httpx.AsyncClient, url: str) -> str:
    try:
        resp = await client.get(url, headers=HEADERS)
        resp.raise_for_status()
    except httpx.HTTPError:
        return ""
    return resp.content.decode("gbk", errors="replace")


def _chunk_after(html: str, code: str) -> str:
    mark = f'clid="{code}"'
    start = html.find(mark)
    if start < 0:
        return ""
    return html[start : start + 900]


def _cn_amount(token: str) -> float | None:
    if token.endswith("亿"):
        return _float(token[:-1], 1e8)
    if token.endswith("万"):
        return _float(token[:-1], 1e4)
    return None


def _float(value: str, scale: float = 1) -> float | None:
    try:
        return float(value) * scale
    except ValueError:
        return None
