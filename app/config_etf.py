"""主流场内 ETF 白名单与性价比阈值。改名单即可扩池，不做全市场扫描。"""

# 回撤窗口与分档（比例，0.08 = 8%）
ETF_LOOKBACK = 60
ETF_VALUE_DD_BROAD = 0.08
ETF_VALUE_DD_THEME = 0.12
ETF_WATCH_DD_BROAD = 0.04
ETF_WATCH_DD_THEME = 0.06
ETF_MA20_BIAS_MAX = 0.03
# 近 5 日涨幅过大则不当「性价比」（已快速修复）
ETF_REBOUND_5D_BLOCK = 0.06
ETF_ACTIVE_LIMIT = 15
ETF_MIN_BARS = 25

# code, name, bucket(broad|sector|theme), track, rescue_priority(越高越靠前)
ETF_WATCHLIST: list[dict] = [
    # —— 宽基（救市敏感：经验标签，非官方监测）——
    {"code": "510050", "name": "上证50ETF", "bucket": "broad", "track": "上证50", "rescue_priority": 90},
    {"code": "510300", "name": "沪深300ETF", "bucket": "broad", "track": "沪深300", "rescue_priority": 100},
    {"code": "510310", "name": "沪深300ETF易方达", "bucket": "broad", "track": "沪深300", "rescue_priority": 95},
    {"code": "159919", "name": "沪深300ETF嘉实", "bucket": "broad", "track": "沪深300", "rescue_priority": 95},
    {"code": "510500", "name": "中证500ETF", "bucket": "broad", "track": "中证500", "rescue_priority": 92},
    {"code": "159922", "name": "中证500ETF嘉实", "bucket": "broad", "track": "中证500", "rescue_priority": 90},
    {"code": "512100", "name": "中证1000ETF", "bucket": "broad", "track": "中证1000", "rescue_priority": 88},
    {"code": "159845", "name": "中证1000ETF鹏华", "bucket": "broad", "track": "中证1000", "rescue_priority": 86},
    {"code": "159915", "name": "创业板ETF", "bucket": "broad", "track": "创业板指", "rescue_priority": 94},
    {"code": "159952", "name": "创业板ETF广发", "bucket": "broad", "track": "创业板指", "rescue_priority": 90},
    {"code": "588000", "name": "科创50ETF", "bucket": "broad", "track": "科创50", "rescue_priority": 93},
    {"code": "588080", "name": "科创板50ETF", "bucket": "broad", "track": "科创50", "rescue_priority": 91},
    {"code": "588050", "name": "科创ETF", "bucket": "broad", "track": "科创板", "rescue_priority": 80},
    {"code": "510880", "name": "红利ETF", "bucket": "broad", "track": "红利", "rescue_priority": 85},
    {"code": "512890", "name": "红利低波ETF", "bucket": "broad", "track": "红利低波", "rescue_priority": 82},
    {"code": "563000", "name": "中国A50ETF", "bucket": "broad", "track": "A50", "rescue_priority": 80},
    {"code": "563300", "name": "中证2000ETF", "bucket": "broad", "track": "中证2000", "rescue_priority": 75},
    {"code": "159967", "name": "创业板成长ETF", "bucket": "broad", "track": "创业成长", "rescue_priority": 72},
    # —— 行业 / 主题 ——
    {"code": "512880", "name": "证券ETF", "bucket": "sector", "track": "证券", "rescue_priority": 60},
    {"code": "159841", "name": "证券ETF天弘", "bucket": "sector", "track": "证券", "rescue_priority": 58},
    {"code": "512000", "name": "券商ETF", "bucket": "sector", "track": "券商", "rescue_priority": 58},
    {"code": "512800", "name": "银行ETF", "bucket": "sector", "track": "银行", "rescue_priority": 55},
    {"code": "512200", "name": "房地产ETF", "bucket": "sector", "track": "地产", "rescue_priority": 50},
    {"code": "159930", "name": "地产ETF", "bucket": "sector", "track": "地产", "rescue_priority": 48},
    {"code": "515220", "name": "煤炭ETF", "bucket": "sector", "track": "煤炭", "rescue_priority": 45},
    {"code": "512400", "name": "有色金属ETF", "bucket": "sector", "track": "有色", "rescue_priority": 40},
    {"code": "159870", "name": "化工ETF", "bucket": "sector", "track": "化工", "rescue_priority": 36},
    {"code": "159981", "name": "能源化工ETF", "bucket": "sector", "track": "能化", "rescue_priority": 35},
    {"code": "159611", "name": "电力ETF", "bucket": "sector", "track": "电力", "rescue_priority": 40},
    {"code": "561170", "name": "电力ETF富国", "bucket": "sector", "track": "电力", "rescue_priority": 39},
    {"code": "512660", "name": "军工ETF", "bucket": "sector", "track": "军工", "rescue_priority": 40},
    {"code": "512670", "name": "国防ETF", "bucket": "sector", "track": "军工", "rescue_priority": 39},
    {"code": "512690", "name": "酒ETF", "bucket": "sector", "track": "白酒", "rescue_priority": 45},
    {"code": "159928", "name": "消费ETF", "bucket": "sector", "track": "消费", "rescue_priority": 48},
    {"code": "159996", "name": "家电ETF", "bucket": "sector", "track": "家电", "rescue_priority": 35},
    {"code": "512170", "name": "医疗ETF", "bucket": "sector", "track": "医疗", "rescue_priority": 46},
    {"code": "512010", "name": "医药ETF", "bucket": "sector", "track": "医药", "rescue_priority": 46},
    {"code": "159992", "name": "创新药ETF", "bucket": "theme", "track": "创新药", "rescue_priority": 40},
    {"code": "515880", "name": "通信ETF", "bucket": "sector", "track": "通信", "rescue_priority": 36},
    {"code": "515050", "name": "5GETF", "bucket": "theme", "track": "通信", "rescue_priority": 35},
    {"code": "512980", "name": "传媒ETF", "bucket": "sector", "track": "传媒", "rescue_priority": 33},
    {"code": "159869", "name": "游戏ETF", "bucket": "theme", "track": "游戏", "rescue_priority": 30},
    {"code": "159766", "name": "旅游ETF", "bucket": "theme", "track": "旅游", "rescue_priority": 30},
    {"code": "159865", "name": "养殖ETF", "bucket": "sector", "track": "养殖", "rescue_priority": 32},
    {"code": "159825", "name": "农业ETF", "bucket": "sector", "track": "农业", "rescue_priority": 32},
    {"code": "516110", "name": "汽车ETF", "bucket": "sector", "track": "汽车", "rescue_priority": 35},
    {"code": "159819", "name": "人工智能ETF", "bucket": "theme", "track": "AI", "rescue_priority": 40},
    {"code": "515070", "name": "人工智能ETF华夏", "bucket": "theme", "track": "AI", "rescue_priority": 40},
    {"code": "512480", "name": "半导体ETF", "bucket": "theme", "track": "半导体", "rescue_priority": 42},
    {"code": "159995", "name": "芯片ETF", "bucket": "theme", "track": "芯片", "rescue_priority": 42},
    {"code": "512760", "name": "芯片ETF国泰", "bucket": "theme", "track": "芯片", "rescue_priority": 41},
    {"code": "588200", "name": "科创芯片ETF", "bucket": "theme", "track": "科创芯片", "rescue_priority": 43},
    {"code": "515790", "name": "光伏ETF", "bucket": "theme", "track": "光伏", "rescue_priority": 38},
    {"code": "159857", "name": "光伏ETF天弘", "bucket": "theme", "track": "光伏", "rescue_priority": 38},
    {"code": "516160", "name": "新能源ETF", "bucket": "theme", "track": "新能源", "rescue_priority": 38},
    {"code": "159875", "name": "新能源车ETF", "bucket": "theme", "track": "新能源车", "rescue_priority": 37},
    {"code": "515030", "name": "新能源车ETF华夏", "bucket": "theme", "track": "新能源车", "rescue_priority": 37},
    {"code": "516510", "name": "云计算ETF", "bucket": "theme", "track": "云计算", "rescue_priority": 34},
    {"code": "515400", "name": "大数据ETF", "bucket": "theme", "track": "大数据", "rescue_priority": 32},
]


def etf_by_code() -> dict[str, dict]:
    out: dict[str, dict] = {}
    for row in ETF_WATCHLIST:
        code = str(row["code"]).zfill(6)
        prev = out.get(code)
        if prev and int(prev.get("rescue_priority") or 0) >= int(row.get("rescue_priority") or 0):
            continue
        out[code] = {**row, "code": code}
    return out
