from app.data.ths import amount_rank_pct, is_broad, parse_catalog, parse_members, parse_stock_page
from app.engine.relate import Candidate, choose_board, is_core


def _series(start: float, step: float) -> dict[str, float]:
    days = [f"2026-09-{day:02d}" for day in range(1, 21)]
    return {day: start + index * step for index, day in enumerate(days)}


def test_broad_names_are_dropped():
    assert is_broad("沪深300")
    assert is_broad("贵州板块")
    assert is_broad("融资融券")
    assert not is_broad("网络安全")


def test_core_uses_amount_rank_before_hint():
    assert is_core("概念", 0.2, False)
    assert not is_core("概念", 0.8, True)
    assert is_core("概念", None, True)
    assert is_core("行业", 0.9, False)


def test_choose_highest_core_correlation():
    stock = _series(0.2, 0.05)
    industry = Candidate("1", "白酒", "行业", {day: value * 0.4 for day, value in stock.items()}, True, 0.1)
    concept = Candidate("2", "网络安全", "概念", dict(stock), True, 0.1)
    fringe = Candidate("3", "电商概念", "概念", {day: value * 2 for day, value in stock.items()}, False, 0.9)
    broad = Candidate("4", "沪深300", "指数", dict(stock), True, 0.1)
    choice = choose_board([industry, concept, fringe, broad], stock)
    assert choice is concept
    assert choice.corr is not None and choice.corr > 0.9


def test_weak_concept_falls_back_to_industry():
    stock = _series(0.3, 0.1)
    industry = Candidate("1", "白酒", "行业", {day: value * 0.8 for day, value in stock.items()}, True, None)
    concept = Candidate("2", "乡村振兴", "概念", {day: 0.01 for day in stock}, True, 0.1)
    choice = choose_board([industry, concept], stock)
    assert choice is industry


def test_parse_ths_pages():
    catalog = parse_catalog('<a href="http://q.10jqka.com.cn/thshy/detail/code/881273/">白酒</a>', "行业")
    assert catalog == [{"code": "881273", "name": "白酒", "kind": "行业"}]
    field = '三级行业分类：<span class="tip">食品饮料 -- 白酒Ⅱ -- 白酒Ⅲ （共<strong>20</strong>家）</span> field/0881273/'
    concept = '<td class="gnName"  clid="885525">白酒概念</td><a code="600519">贵州茅台</a>'
    parsed = parse_stock_page(field, concept, {"881273": catalog[0]})
    assert parsed["industry"]["name"] == "白酒"
    assert parsed["industry"]["level3"] == "白酒Ⅲ"
    assert parsed["boards"][0]["name"] == "白酒概念"
    members = parse_members(
        '<tr><td><a href="http://stockpage.10jqka.com.cn/600519/">600519</a></td><td>44.53亿</td><td>12.50亿</td><td>15788.50亿</td></tr>'
        '<tr><td><a href="http://stockpage.10jqka.com.cn/000858/">000858</a></td><td>12.58亿</td></tr>'
    )
    assert abs(amount_rank_pct(members, "600519") - 0.5) < 1e-9
