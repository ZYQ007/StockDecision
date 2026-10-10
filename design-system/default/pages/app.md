# App Page Overrides

> **PROJECT:** 买入时机  
> **Page Type:** Dashboard / Tool  
> Overrides `design-system/default/MASTER.md`.

---

## Page-Specific Rules

### Layout Overrides

- Full-width shell (`width: 100%`), horizontal padding `clamp(16px, 2vw, 28px)` — no 1520px cap
- Stack (top → bottom, always visible): sticky top bar → tape → alerts → **main tablist** → current pane
- Main tabs (single tablist, one pane at a time):
  1. **查这一只** (default) — two-column analyze: judge + report summary  
  2. **最近可买** — full-width signals table (priority, accent panel)  
  3. **持仓关注** — full-width positions table  
  4. **当下池** — stock pool groups + one table  
  5. **ETF** — whitelist ETF: broad / value / active / all  
  6. **统计** — stratified stats (secondary / muted)
- Hash routes: `#decide` `#signals` `#positions` `#pool` `#etf` `#stats` (refresh restores)
- ETF statuses: 性价比关注 / 观望 / 偏贵 (not stock 可买); rescue-sensitive label is experiential only
- Inactive panes stay in DOM (`hidden`) so `tick` keeps refreshing data
- Pane tables use remaining viewport height (`fill-pane` / flex)
- Sticky top bar `56px` with `scroll-padding-top`
- Pool as one tablist with three visual groups (盯盘 / 可买 / 模式) and count badges
- Report collapsed by default; verdict refresh is manual (no 15s auto-judge)
- Wide: judge | report side-by-side; `<1100px` stack vertically

### Spacing Overrides

- Density high (dial ~9): `--space-md 12px`, panel padding 16px, compact table rows
- Main tab touch target ≥40–44px; table area eats leftover viewport

### Typography Overrides

- CJK: `Noto Sans SC` + `IBM Plex Mono` (not Inter / not Fira from generic DS search)
- Body 14px; table 12.5px; mono for prices and clock
- Priority panel title 15px; stats title muted 13px

### Color Overrides

- Lock dark OLED from Master (`#020617` / `#0E1223` / accent `#22C55E`)
- China quotes: 红涨 `#EF4444` / 绿跌 `#22C55E`
- Gate pass = accent green; veto = destructive red; wait = amber
- Priority panel: accent border + soft ring (not purple glow)
- Main tab selected: accent underline indicator

### Component Overrides

- Primary action label:「判断」; secondary「刷新结论」
- Brand link → `/`; footer「返回落地页」→ `/`
- Main + pool tab keyboard: Arrow / Home / End; selected tab `tabIndex=0`
- Touch targets: submit ≥44px; tabs ≥36px with 8px gap
- Visible focus ring (`--color-ring`); `prefers-reduced-motion` respected
- Failed gates sorted first; next-step bar for 观望/可买/不买
- 最近可买 / 池子点名称 → `judge` then auto-switch to「查这一只」
- 持仓告警「查看持仓」→ switch to「持仓关注」
- 最近可买: count badge on tab + panel head

---

## Recommendations Applied

- Row hover highlight on tables; sticky table headers
- No light-mode flip
- Progressive disclosure for nine-section report
- Pool empty states explain data vs env vs no-hit
- Information architecture: one primary task per viewport (tabs), not stacked cards
