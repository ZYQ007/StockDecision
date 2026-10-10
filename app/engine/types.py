from dataclasses import dataclass, field


@dataclass
class MarketInputs:
    ready: bool = True
    sh_above_ma20: bool = False
    cy_above_ma20: bool = False
    sh_ma20_up: bool = False
    cy_ma20_up: bool = False
    sh_pct: float = 0.0
    cy_pct: float = 0.0
    amount_ratio: float = 1.0
    amount_reliable: bool = True
    sh_range_pos: float = 0.5
    sh_upper_shadow: float = 0.0
    sh_near_low: bool = False
    up_count: int = 0
    down_count: int = 0
    zt_count: int = 0
    dt_count: int = 0
    sh_price: float = 0.0
    cy_price: float = 0.0
    sz_price: float = 0.0
    sz_pct: float = 0.0
    total_amount: float = 0.0
    avg_amount_5: float = 0.0
    amount_basis: str = "amount"
    sh_ma20: float = 0.0
    cy_ma20: float = 0.0
    northbound_note: str = ""
    emotion_source: str = ""


@dataclass
class MarketView:
    ready: bool
    regime: str
    block_new: bool
    block_chase: bool
    reason: str
    amount_label: str
    amount_ratio: float
    sh_price: float
    sh_pct: float
    cy_price: float
    cy_pct: float
    sz_price: float
    sz_pct: float
    total_amount: float
    avg_amount_5: float
    up_count: int
    down_count: int
    zt_count: int
    dt_count: int
    sh_ma20: float
    cy_ma20: float
    env_tier: str = "震荡"  # 强势 | 震荡 | 弱势
    position_cap: float = 0.5
    northbound_note: str = ""


@dataclass
class SectorDay:
    trade_date: str
    pct: float
    index_pct: float
    rank: int = 0
    total: int = 0
    inflow: float | None = None


@dataclass
class SectorInputs:
    ready: bool = False
    name: str = ""
    rank: int = 0
    total: int = 0
    pct: float = 0.0
    index_pct: float = 0.0
    matched_concepts: list[str] = field(default_factory=list)
    days: list[SectorDay] = field(default_factory=list)
    kind: str = ""
    source: str = ""
    corr: float | None = None
    amount_pct: float | None = None


@dataclass
class SectorView:
    ready: bool
    name: str
    rank: int
    total: int
    pct: float
    weak: bool
    extended: bool
    unknown: bool
    reason: str
    matched_concepts: list[str] = field(default_factory=list)
    persist: str = ""
    fade: bool = False
    block_buy: bool = False
    amount_pct: float | None = None
    theme_quality: str = ""  # 真主线 | 伪题材 | 中性 | 未知
    stage: str = ""  # 萌芽 | 发酵 | 主升 | 分歧 | 尾声 | 未知


@dataclass
class EntryInputs:
    ready: bool = True
    price: float = 0.0
    day_pct: float = 0.0
    ma5: float = 0.0
    ma10: float = 0.0
    ma20: float = 0.0
    ma20_up: bool = False
    high_20: float = 0.0
    low_20: float = 0.0
    ret_10d_pct: float = 0.0
    volume_ratio: float | None = None
    vwap: float | None = None
    amount: float = 0.0
    suspended: bool = False
    ret_5d_pct: float = 0.0
    index_ret_5d_pct: float = 0.0
    stock_flow_3d: float | None = None
    limit_up: bool = False
    board_core: bool = False
    avg_amount_5: float = 0.0
    turnover: float | None = None


@dataclass
class EntryView:
    ready: bool
    trend_ok: bool
    setup: str  # pullback | breakout | hold | leader | chase | none | broken
    terminal: bool
    vetoes: list[str]
    reason: str
    watch_price: float | None
    watch_text: str
    dist_ma5: float
    dist_ma10: float
    range_pos: float


@dataclass
class Gate:
    name: str
    status: str  # 过 | 不过 | 否决 | 缺失
    text: str


@dataclass
class Decision:
    verdict: str  # 可买 | 观望 | 不买
    setup: str
    reason_line: str
    gates: list[Gate]
    vetoes: list[str]
    watch_text: str
    watch_price: float | None
    scores: dict
    warnings: list[str] = field(default_factory=list)
    logic_track: str = "短期主线交易"
    env_tier: str = "震荡"
    position_advice: str = ""
    theme_quality: str = ""
    sector_stage: str = ""
    ai_conflict: bool = False
