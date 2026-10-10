"""九段研报旁路。规则结论权威，本模块只作参考。"""

from __future__ import annotations

from app import config
from app.data import stock_sdk_bridge as sdk
from app.engine.decide import decide
from app.engine.market import classify_market
from app.engine.sector import classify_sector
from app.engine.types import EntryInputs, MarketInputs, SectorInputs


def build_report(
    *,
    quote: dict,
    market: MarketInputs,
    sector: SectorInputs,
    entry: EntryInputs,
    decision_verdict: str,
    stock_read_text: str = "",
    pick_text: str = "",
    wave2_text: str = "",
) -> dict:
    if not config.AI_REPORT_ENABLED:
        return {
            "ok": False,
            "disabled": True,
            "note": "研报旁路已关闭",
            "changes_verdict": False,
        }
    m = classify_market(market)
    s = classify_sector(sector)
    track = "短期题材情绪逻辑"
    if s.theme_quality == "真主线" and entry.board_core:
        track = "短期主线交易逻辑（非中长期价值）"
    risks = _risks(m, s, entry, quote)
    while len(risks) < 3:
        risks.append("公开数据不全，未知风险仍在")
    if entry.ret_10d_pct >= 25:
        valuation = "近10日涨幅偏大，短线拥挤风险升高；研报侧不做精确估值"
    else:
        valuation = "估值细节不足，仅提示短线拥挤度需自查；不以估值为可买门"

    support = entry.ma10
    resist = entry.high_20
    plan = {
        "仓位": f"环境{m.env_tier}，总仓建议上限约 {int(round(m.position_cap * 10))} 成",
        "买入区间": f"观察价附近 {support:.2f}" if support else "等观察价",
        "止损": "须自设止损；单笔亏损建议控制在总资金约 2% 以内（本工具不下单）",
        "止盈思路": "短线以板块退潮或跌破 MA10/MA20 为减仓思路",
    }
    sections = {
        "1_market": f"{m.env_tier}环境（regime={m.regime}）。{m.reason}",
        "2_sector": (
            f"板块「{s.name or '未对齐'}」定性 {s.theme_quality or '未知'}，"
            f"阶段 {s.stage or '未知'}，持续性 {s.persist or '未知'}。{s.reason}"
        ),
        "3_stock_logic": (
            f"轨道：{track}。{pick_text or '候选逻辑见规则侧。'} "
            f"{'模式：' + wave2_text if wave2_text else ''}".strip()
        ),
        "4_flow": (
            f"近3日个股主力净流入 "
            f"{_money(entry.stock_flow_3d) if entry.stock_flow_3d is not None else '暂缺'}；"
            f"量比 {_vol(entry.volume_ratio)}。"
            f"{stock_read_text}"
        ),
        "5_valuation": valuation,
        "6_tech": (
            f"现价 {entry.price:.2f}，支撑参考 MA10 {support:.2f}，压力参考近20日高 {resist:.2f}；"
            f"技术面只辅助买点，不能单独作为买入理由。"
        ),
        "7_risks": risks,
        "8_plan": plan,
        "9_summary": (
            f"机会更偏【{track}】；规则结论是「{decision_verdict}」。"
            f"核心不确定性：板块是否伪题材、资金是否持续、大盘是否转弱。"
        ),
    }
    conflict = False
    if decision_verdict in {"不买", "观望"} and s.theme_quality == "真主线" and m.env_tier == "强势":
        conflict = True
    if decision_verdict == "可买" and (m.env_tier == "弱势" or s.theme_quality == "伪题材"):
        conflict = True

    deep = None
    if config.AI_REPORT_USE_TRADINGAGENTS:
        deep = _try_tradingagents(quote.get("code") or "")

    sdk_note = ""
    brief = sdk.quote_brief(quote.get("code") or "")
    if brief.get("ok"):
        sdk_note = "已抽样 stock-sdk 报价作对照"
    else:
        sdk_note = "stock-sdk 对照暂不可用，不假装有数"

    return {
        "ok": True,
        "changes_verdict": False,
        "authority": "主栏三道门规则结论权威；本研报不改变可买/观望/不买",
        "conflict": conflict,
        "conflict_note": "口径冲突，以规则为准" if conflict else "",
        "logic_track": track,
        "sections": sections,
        "sdk_note": sdk_note,
        "tradingagents": deep,
        "disclaimer": config.DISCLAIMER,
    }


def _vol(value: float | None) -> str:
    if value is None:
        return "-"
    return f"{value:.2f}"


def _money(value: float) -> str:
    if abs(value) >= 1e8:
        return f"{value / 1e8:+.2f} 亿"
    return f"{value / 1e4:+.0f} 万"


def _risks(m, s, entry, quote) -> list[str]:
    out = []
    if m.env_tier == "弱势" or m.block_new:
        out.append("大盘弱势或防守，新开仓环境差")
    if s.theme_quality == "伪题材" or s.persist == "一日游":
        out.append("板块疑似伪题材或一日游")
    if entry.stock_flow_3d is not None and entry.stock_flow_3d < 0:
        out.append("近3日个股主力净流入为负")
    if entry.volume_ratio and entry.volume_ratio >= 1.8 and entry.day_pct <= 1:
        out.append("高位放量滞涨风险")
    if entry.ret_10d_pct >= 25:
        out.append("近10日涨幅过大，追高风险")
    name = (quote.get("name") or "").upper()
    if "ST" in name.replace(" ", ""):
        out.append("ST 风险标的")
    if not s.ready:
        out.append("主板块未对齐，板块风险未知")
    return out[:6]


def _try_tradingagents(code: str) -> dict | None:
    try:
        from tradingagents.graph.trading_graph import TradingAgentsGraph  # type: ignore
    except Exception as exc:
        return {"ok": False, "error": f"TradingAgents 不可用: {exc}"}
    try:
        ta = TradingAgentsGraph(debug=False, config={"output_language": "Chinese"})
        # 重量路径仅探测是否可导入；完整 propagate 成本高，默认不自动跑完
        return {
            "ok": True,
            "note": "已检测到 TradingAgents，完整多 Agent 需自行配置 LLM Key 后启用深度模式",
            "code": code,
            "ready": True,
        }
    except Exception as exc:
        return {"ok": False, "error": str(exc)}
