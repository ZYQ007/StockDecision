# 买入时机（StockDecision）

A 股 2～5 日短线**开仓复核**本机助手：三道门规则给出「可买 / 观望 / 不买」，不下单。

规则辅助，不构成收益承诺。License: [MIT](LICENSE)。

支持 **Windows** 与 **macOS**。

## 终端用户

向维护者索取对应系统的安装包：

| 系统 | 产物 |
| --- | --- |
| Windows | `买入时机-Setup-*.exe` 或 portable zip |
| macOS | `买入时机-mac-*.dmg` / `买入时机.app` / portable zip |

详见 [docs/安装与使用.md](docs/安装与使用.md)。

Windows 开盘自动运行（工作日 9:10 启 / 15:10 停；迟到开机登录后若仍在交易时段会补启）：

```text
powershell -ExecutionPolicy Bypass -File scripts\schedule-market-hours.ps1 -Action Register
```

## 开发者本机运行

```text
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python -m app
```

浏览器：http://127.0.0.1:8765  

推荐启动器（数据进用户目录）：

```text
python scripts/launcher.py
```

- Windows 数据：`%LOCALAPPDATA%\买入时机\`
- macOS 数据：`~/Library/Application Support/买入时机\`

## 维护者打安装包

**Windows（在 Windows 上）：**

1. 安装 [Inno Setup 6](https://jrsoftware.org/isinfo.php)
2. `powershell -ExecutionPolicy Bypass -File scripts\build-installer.ps1`

**macOS（须在 Mac 上）：**

```text
chmod +x scripts/build-installer-mac.sh
./scripts/build-installer-mac.sh
```

产物在 `dist/`。

## 文档

- [产品说明书](docs/产品说明书.md)
- [交易逻辑总纲](docs/a-stock-trading-logic.md)
- [安装与使用](docs/安装与使用.md)（含 Win / Mac）

## 后续路线（未在本期实现）

1. 本机分发（Win 安装包 + Mac .app/DMG）— 当前
2. 小团队托管（鉴权、持仓隔离）
3. 系统网站变现；小程序不作一期主形态

### macOS 说明

通达信为 Windows 客户端，Mac 上一般走备用行情主站，功能可用但可能弱于「Windows + 通达信」。
