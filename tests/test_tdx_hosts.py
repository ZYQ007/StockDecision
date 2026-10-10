from app.data.boards import _needs_closes
from app.data.tdx import parse_hq_hosts

SAMPLE = """
[USER]
UserName=

[HQHOST]
HostNum=3
PrimaryHost=2
HostName01=深圳
IPAddress01=1.1.1.1
Port01=7709
HostName02=上海
IPAddress02=2.2.2.2
Port02=7709
HostName03=北京
IPAddress03=3.3.3.3
Port03=7711

[OTHER]
IPAddress01=9.9.9.9
"""


def test_primary_host_is_first_and_later_sections_are_ignored():
    assert parse_hq_hosts(SAMPLE) == ["3.3.3.3:7711", "1.1.1.1:7709", "2.2.2.2:7709"]


def test_stale_board_closes_need_refresh():
    assert _needs_closes(None, "2026-10-09")
    assert _needs_closes({}, "2026-10-09")
    assert _needs_closes({"2025-12-31": 100.0}, "2026-10-09")
    assert not _needs_closes({"2026-10-09": 100.0}, "2026-10-09")
