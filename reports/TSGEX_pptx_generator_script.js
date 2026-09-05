const pptxgen = require("pptxgenjs");

// ---- Palette (per user spec) ----
const WHITE = "FFFFFF";
const NAVY = "0F172A";     // titles / dark bg
const SLATE = "334155";    // body text
const ACCENT = "2563EB";   // accent blue
const LIGHT_TINT = "EFF6FF"; // light card bg (blue-50)
const LIGHT_TINT2 = "F8FAFC"; // slate-50
const BORDER = "E2E8F0";   // slate-200
const MUTED = "64748B";    // slate-500 captions
const GOOD = "16A34A";     // green for positive callouts (used sparingly)
const WARN = "B45309";     // amber for risk callouts (used sparingly, not alarmist)

const FONT = "Microsoft JhengHei";

const pres = new pptxgen();
pres.layout = "LAYOUT_WIDE"; // 13.333 x 7.5 in, 16:9
const PW = 13.333, PH = 7.5;

function newSlide(bg = WHITE) {
  const s = pres.addSlide();
  s.background = { color: bg };
  return s;
}

function footer(s, pageLabel, dark = false) {
  s.addText("TSGEX 資產管理部｜內部機密", {
    x: 0.5, y: PH - 0.4, w: 6, h: 0.3, fontFace: FONT, fontSize: 9,
    color: dark ? "94A3B8" : MUTED, align: "left", isTextBox: true, margin: 0,
  });
  s.addText(pageLabel, {
    x: PW - 2.5, y: PH - 0.4, w: 2, h: 0.3, fontFace: FONT, fontSize: 9,
    color: dark ? "94A3B8" : MUTED, align: "right", isTextBox: true, margin: 0,
  });
}

function circleLabel(s, x, y, d, label, opts = {}) {
  s.addShape("ellipse", { x, y, w: d, h: d, fill: { color: opts.fill || LIGHT_TINT }, line: { type: "none" } });
  s.addText(label, {
    x, y, w: d, h: d, fontFace: FONT, bold: true, fontSize: opts.fontSize || 16,
    color: opts.color || ACCENT, align: "center", valign: "middle", isTextBox: true, margin: 0,
  });
}

function sectionTitle(s, title, sub) {
  s.addText(title, {
    x: 0.6, y: 0.4, w: PW - 1.2, h: 0.7, fontFace: FONT, bold: true, fontSize: 28,
    color: NAVY, align: "left", isTextBox: true, margin: 0,
  });
  if (sub) {
    s.addText(sub, {
      x: 0.6, y: 1.05, w: PW - 1.2, h: 0.4, fontFace: FONT, fontSize: 13,
      color: MUTED, align: "left", isTextBox: true, margin: 0,
    });
  }
}

// simple card with title + body, light tint background, no accent stripe
function card(s, x, y, w, h, title, body, opts = {}) {
  s.addShape("roundRect", {
    x, y, w, h, rectRadius: 0.08,
    fill: { color: opts.fill || LIGHT_TINT2 },
    line: { color: BORDER, width: 0.75 },
    shadow: { type: "outer", color: "1E293B", opacity: 0.08, blur: 6, offset: 2, angle: 90 },
  });
  if (title) {
    s.addText(title, {
      x: x + 0.22, y: y + 0.16, w: w - 0.44, h: 0.35, fontFace: FONT, bold: true,
      fontSize: opts.titleSize || 13, color: opts.titleColor || NAVY, align: "left", isTextBox: true, margin: 0,
    });
  }
  if (body) {
    s.addText(body, {
      x: x + 0.22, y: y + (title ? 0.55 : 0.16), w: w - 0.44, h: h - (title ? 0.72 : 0.32),
      fontFace: FONT, fontSize: opts.bodySize || 11, color: opts.bodyColor || SLATE,
      align: "left", valign: "top", isTextBox: true, margin: 0, lineSpacingMultiple: 1.15,
    });
  }
}

function statCallout(s, x, y, w, h, value, label, opts = {}) {
  s.addShape("roundRect", {
    x, y, w, h, rectRadius: 0.08,
    fill: { color: opts.fill || LIGHT_TINT },
    line: { type: "none" },
  });
  s.addText(value, {
    x: x + 0.15, y: y + 0.12, w: w - 0.3, h: h - 0.55, fontFace: FONT, bold: true,
    fontSize: opts.valueSize || 30, color: opts.valueColor || ACCENT, align: "center", valign: "bottom",
    isTextBox: true, margin: 0,
  });
  s.addText(label, {
    x: x + 0.1, y: y + h - 0.42, w: w - 0.2, h: 0.35, fontFace: FONT, fontSize: 10.5,
    color: opts.labelColor || SLATE, align: "center", valign: "top", isTextBox: true, margin: 0,
  });
}

// generic table wrapper with consistent styling
function stdTable(s, rows, opts) {
  const header = rows[0].map((t) => ({
    text: t,
    options: { fill: { color: NAVY }, color: WHITE, bold: true, fontSize: opts.fontSize || 10.5, align: "center", valign: "middle" },
  }));
  const body = rows.slice(1).map((r, ri) =>
    r.map((t, ci) => ({
      text: t,
      options: {
        fill: { color: ri % 2 === 0 ? WHITE : LIGHT_TINT2 },
        color: SLATE, fontSize: opts.fontSize || 10.5,
        align: opts.centerCols && opts.centerCols.includes(ci) ? "center" : "left",
        valign: "middle", bold: opts.boldCols && opts.boldCols.includes(ci),
      },
    }))
  );
  s.addTable([header, ...body], {
    x: opts.x, y: opts.y, w: opts.w, colW: opts.colW,
    border: { type: "solid", color: BORDER, pt: 0.75 },
    autoPage: false, valign: "middle", margin: [0.05, 0.08, 0.05, 0.08],
    rowH: opts.rowH,
  });
}

/* ============ SLIDE 1: TITLE (white background) ============ */
{
  const s = newSlide(WHITE);
  // subtle decorative circles, light tint only — no dark fill
  s.addShape("ellipse", { x: 10.4, y: -2.0, w: 5, h: 5, fill: { color: LIGHT_TINT }, line: { type: "none" } });
  s.addShape("ellipse", { x: -1.8, y: 5.4, w: 4, h: 4, fill: { color: LIGHT_TINT2 }, line: { color: BORDER, width: 0.75 } });

  s.addText("TSGEX 資產管理部", {
    x: 0.9, y: 1.6, w: 11.5, h: 0.5, fontFace: FONT, fontSize: 16, color: ACCENT,
    bold: true, align: "left", isTextBox: true, margin: 0, charSpacing: 2,
  });
  s.addText("自有流動資金收益優化可行性評估報告", {
    x: 0.9, y: 2.15, w: 11.5, h: 1.1, fontFace: FONT, fontSize: 40, color: NAVY,
    bold: true, align: "left", isTextBox: true, margin: 0,
  });
  s.addText("五大主流工具數據穿透、風險剖析與財務部資產配置決策矩陣", {
    x: 0.9, y: 3.15, w: 11.5, h: 0.6, fontFace: FONT, fontSize: 18, color: SLATE,
    align: "left", isTextBox: true, margin: 0,
  });

  s.addShape("line", { x: 0.9, y: 4.05, w: 3.2, h: 0, line: { color: ACCENT, width: 2 } });

  const chips = ["Bitfinex USD Margin Funding", "OKX 活期理財", "Binance 活期理財", "OKX 雙幣贏", "Binance 雙幣投資"];
  let cx = 0.9;
  chips.forEach((c) => {
    const w = 0.18 + c.length * 0.115;
    s.addShape("roundRect", { x: cx, y: 4.35, w, h: 0.42, rectRadius: 0.21, fill: { color: LIGHT_TINT }, line: { color: BORDER, width: 0.75 } });
    s.addText(c, { x: cx, y: 4.35, w, h: 0.42, fontFace: FONT, fontSize: 10.5, color: ACCENT, align: "center", valign: "middle", isTextBox: true, margin: 0 });
    cx += w + 0.18;
  });

  s.addText("提案呈送：財務部（Treasury & Finance）｜風險管理委員會｜投資委員會（IC）", {
    x: 0.9, y: 6.35, w: 8, h: 0.35, fontFace: FONT, fontSize: 12, color: SLATE, isTextBox: true, margin: 0,
  });
  s.addText("內部機密（Internal Confidential）｜2026年9月｜文件編號 TSGEX-AM-2026-0904-R2", {
    x: 0.9, y: 6.7, w: 10, h: 0.35, fontFace: FONT, fontSize: 11, color: MUTED, isTextBox: true, margin: 0,
  });
}

/* ============ SLIDE 2: EXECUTIVE SUMMARY ============ */
{
  const s = newSlide();
  sectionTitle(s, "執行摘要", "五大標的之收益光譜定位——本報告以數據呈現機制與風險，配置決策保留予財務部");

  const items = [
    { n: "01", t: "Bitfinex USD\nMargin Funding", d: "出借利息｜P2P超額抵押\n零方向性曝險", apy: "4.25%–17.0%+", fill: LIGHT_TINT },
    { n: "02", t: "OKX USDT\n活期理財", d: "資金池利差\nT+0 流動性", apy: "約 1.7%–4.3%", fill: LIGHT_TINT2 },
    { n: "03", t: "Binance USDT\n活期理財", d: "資金池利差\nT+0 流動性", apy: "約 1.5%", fill: LIGHT_TINT2 },
    { n: "04", t: "OKX\n雙幣贏", d: "選擇權權利金\n非保本結構", apy: "名目 4%–138%", fill: LIGHT_TINT },
    { n: "05", t: "Binance\n雙幣投資", d: "選擇權權利金\n非保本結構", apy: "官方 4%–138%", fill: LIGHT_TINT },
  ];
  const cw = 2.32, gap = 0.16, startX = 0.6, y0 = 1.65, ch = 3.55;
  items.forEach((it, i) => {
    const x = startX + i * (cw + gap);
    s.addShape("roundRect", { x, y: y0, w: cw, h: ch, rectRadius: 0.1, fill: { color: it.fill }, line: { color: BORDER, width: 0.75 } });
    circleLabel(s, x + 0.18, y0 + 0.2, 0.5, it.n, { fill: WHITE, color: ACCENT, fontSize: 14 });
    s.addText(it.t, {
      x: x + 0.18, y: y0 + 0.85, w: cw - 0.36, h: 0.75, fontFace: FONT, bold: true, fontSize: 13.5,
      color: NAVY, align: "left", isTextBox: true, margin: 0, lineSpacingMultiple: 1.05,
    });
    s.addText(it.d, {
      x: x + 0.18, y: y0 + 1.65, w: cw - 0.36, h: 0.85, fontFace: FONT, fontSize: 10.5,
      color: SLATE, align: "left", isTextBox: true, margin: 0, lineSpacingMultiple: 1.2,
    });
    s.addShape("line", { x: x + 0.18, y: y0 + 2.55, w: cw - 0.36, h: 0, line: { color: BORDER, width: 0.75 } });
    s.addText("機構百萬資金 APY", { x: x + 0.18, y: y0 + 2.65, w: cw - 0.36, h: 0.25, fontFace: FONT, fontSize: 9, color: MUTED, isTextBox: true, margin: 0 });
    s.addText(it.apy, { x: x + 0.18, y: y0 + 2.88, w: cw - 0.36, h: 0.55, fontFace: FONT, bold: true, fontSize: 15, color: ACCENT, isTextBox: true, margin: 0 });
  });

  s.addText(
    "核心財務基準：SOFR / 3M T-Bill ≈ 4.5%＋150–200 bps 流動性溢價（政策基準）；即時市場 SOFR（2026-09-01）為 3.66%",
    { x: 0.6, y: 5.45, w: PW - 1.2, h: 0.4, fontFace: FONT, fontSize: 12, color: SLATE, isTextBox: true, margin: 0 }
  );
  card(s, 0.6, 5.9, PW - 1.2, 1.0, "本報告定位",
    "五項工具視為功能各異之「資產配置積木」，涵蓋純固定收益、資金池活期收益、賣方結構型衍生品三種收益本質；報告以呈現真實金融工程機制、數據試算與風險因子為唯一目的，最終配置決策保留予財務部與投資委員會依風險偏好判斷。",
    { fill: LIGHT_TINT2, bodySize: 11.5 });
  footer(s, "2 / 16");
}

/* ============ SLIDE 3: BENCHMARK ============ */
{
  const s = newSlide();
  sectionTitle(s, "財務基準與研究揭露", "即時聯網檢索校驗（檢索時間：2026 年 9 月）");

  statCallout(s, 0.6, 1.75, 3.7, 2.0, "4.5%+150–200bps", "公司內部政策性 Hurdle Rate", { valueSize: 24 });
  statCallout(s, 4.55, 1.75, 3.7, 2.0, "3.66%", "即時 SOFR（2026-09-01，NY Fed）", { valueSize: 30, valueColor: NAVY, fill: LIGHT_TINT2 });
  statCallout(s, 8.5, 1.75, 4.23, 2.0, "本報告採用", "計算超額利差（Alpha）時，統一以即時市場 SOFR 3.66% 為客觀基準", { valueSize: 16, valueColor: GOOD });

  card(s, 0.6, 4.1, 5.95, 2.5, "研究方法揭露",
    "本報告所引用之各平台利率、費用結構、儲備金證明與雙幣理財機制，均經即時聯網檢索取得（Bitfinex Help Center / EarnUSD、OKX Help Center、Binance 官方公告、NY Fed FRED 資料庫等），完整來源列示於報告末章「資料來源與檢索時間」。",
    { fill: LIGHT_TINT2, bodySize: 12 });
  card(s, 6.75, 4.1, 5.98, 2.5, "客觀中立原則",
    "全篇報告聚焦「100% 公開、透明、真實」之底層邏輯、真實收益率計算與具體風險因子，不對任一標的下達主觀否定性結論；五項工具均視為可依風險偏好調整權重之配置積木。",
    { fill: LIGHT_TINT2, bodySize: 12 });
  footer(s, "3 / 16");
}

/* ============ SLIDE 4: BITFINEX MECHANISM ============ */
{
  const s = newSlide();
  sectionTitle(s, "① Bitfinex USD Margin Funding", "P2P 保證金撮合機制與美元法幣屬性");

  const rows = [
    ["P2P 訂單簿撮合", "出借人掛出金額／利率／天期，依價格與時間優先原則自動撮合，資訊透明度高"],
    ["借款人超額抵押", "原始保證金率約為部位名目價值之 15%–33%（最高槓桿約 3–6.6 倍）"],
    ["維持保證金與清算引擎", "保證金比率跌破約 15% 時自動觸發強制減倉，優先以借款人擔保品償付"],
    ["出借人優先受償權", "求償順位優先於借款人自身權益；強平引擎完成減倉前，出借人本金不受影響"],
  ];
  let y = 1.7;
  rows.forEach((r, i) => {
    circleLabel(s, 0.6, y, 0.5, String(i + 1), { fill: LIGHT_TINT, fontSize: 15 });
    s.addText(r[0], { x: 1.35, y: y - 0.02, w: 3.1, h: 0.55, fontFace: FONT, bold: true, fontSize: 13, color: NAVY, isTextBox: true, margin: 0, valign: "middle" });
    s.addText(r[1], { x: 4.55, y: y - 0.02, w: 8.15, h: 0.55, fontFace: FONT, fontSize: 11.5, color: SLATE, isTextBox: true, margin: 0, valign: "middle", lineSpacingMultiple: 1.1 });
    y += 0.72;
  });

  card(s, 0.6, y + 0.15, 5.95, 1.65, "為何選擇 USD 法幣",
    "零幣價波動（Delta-Neutral），本金無方向性曝險；無穩定幣脫錨疑慮；可直接列示為現金及約當現金，符合 GAAP/IFRS 認列規範，會計處理最單純。",
    { fill: LIGHT_TINT2, bodySize: 11.5 });
  card(s, 6.75, y + 0.15, 5.98, 1.65, "利差階梯掛單授權",
    "常態（APR<15%）：2–7 天短天期滾存｜高息溢價期（APR≥15%）：開放至 15–30 天鎖定超額利潤｜極端波動期（APR≥30%+）：專案彈性授權至 60–120 天",
    { fill: LIGHT_TINT2, bodySize: 11.5 });
  footer(s, "4 / 16");
}

/* ============ SLIDE 5: BITFINEX DATA & SCENARIOS ============ */
{
  const s = newSlide();
  sectionTitle(s, "① Bitfinex：即時市場數據與百萬美元試算", "檢索日：2026 年 9 月｜扣除平台 15% 服務費後");

  statCallout(s, 0.6, 1.65, 2.85, 1.5, "12.1%", "近期 USD 出借日均 APR（扣費前）", { valueSize: 28 });
  statCallout(s, 3.6, 1.65, 2.85, 1.5, "3%–20%", "FRR 歷史區間（每小時更新）", { valueSize: 24, valueColor: NAVY, fill: LIGHT_TINT2 });
  statCallout(s, 6.6, 1.65, 2.85, 1.5, "15% / 18%", "標準／隱藏掛單服務費", { valueSize: 24, valueColor: NAVY, fill: LIGHT_TINT2 });
  statCallout(s, 9.6, 1.65, 3.13, 1.5, "+663 bps", "基準情境相較即時 SOFR 超額利差", { valueSize: 26, valueColor: GOOD });

  s.addChart(pres.ChartType.bar, [
    {
      name: "淨年化收益率 Net APY",
      labels: ["保守情境\n(5.0% gross)", "基準情境\n(12.1% gross)", "樂觀情境\n(20%+ gross)"],
      values: [4.25, 10.29, 17.0],
    },
  ], {
    x: 0.6, y: 3.45, w: 6.6, h: 3.4,
    barDir: "col", chartColors: [ACCENT],
    showTitle: true, title: "百萬美元淨年化收益率（%）", titleFontFace: FONT, titleFontSize: 13, titleColor: NAVY,
    showValue: true, dataLabelPosition: "outEnd", dataLabelFontSize: 11, dataLabelColor: NAVY, dataLabelFormatCode: '0.00"%"',
    catAxisLabelFontFace: FONT, catAxisLabelFontSize: 10, catAxisLabelColor: SLATE,
    valAxisLabelFontFace: FONT, valAxisLabelFontSize: 9, valAxisLabelColor: MUTED,
    valGridLine: { color: BORDER, size: 0.75 }, catGridLine: { style: "none" },
    showLegend: false, valAxisMaxVal: 20,
  });

  stdTable(s, [
    ["情境", "淨年化", "年度淨利", "月度淨利"],
    ["保守", "4.25%", "$42,500", "$3,541.7"],
    ["基準", "10.29%", "$102,850", "$8,570.8"],
    ["樂觀", "17.0%+", "$170,000+", "$14,166.7+"],
  ], { x: 7.5, y: 3.55, w: 5.23, colW: [1.2, 1.2, 1.5, 1.33], fontSize: 11, centerCols: [1, 2, 3], rowH: 0.55 });

  s.addText("本金 $1,000,000｜相較即時 SOFR（3.66%）：保守 +59bps／基準 +663bps／樂觀 +1,334bps+", {
    x: 7.5, y: 5.85, w: 5.23, h: 0.8, fontFace: FONT, fontSize: 10, color: MUTED, isTextBox: true, margin: 0, lineSpacingMultiple: 1.2,
  });
  footer(s, "5 / 16");
}

/* ============ SLIDE 6: OKX FLEXIBLE ============ */
{
  const s = newSlide();
  sectionTitle(s, "② OKX USDT 活期理財（Simple Earn 靈活）", "階梯利率結構穿透：百萬美元規模真實有效年化");

  card(s, 0.6, 1.65, 5.95, 2.0, "運作架構",
    "用戶 USDT 併入 OKX 整體借貸資金池，每小時依借貸需求排序出借申請，構成表內無擔保信用曝險。儲備金證明：第 45 期月度 PoR（2026年8月），鏈上錢包合計約 232.3 億美元，主要資產覆蓋率維持 100% 以上。",
    { fill: LIGHT_TINT2, bodySize: 11.5 });

  card(s, 6.75, 1.65, 5.98, 2.0, "階梯利率與費用",
    "前 500 USDT 享 Bonus APR 最高 10.00%；超過額度部分依市場浮動 APR 計息。平台費用 15%：小時報酬 = 出借金額 × APR ÷ 365 ÷ 24 × 85%。",
    { fill: LIGHT_TINT, bodySize: 11.5 });

  stdTable(s, [
    ["級距（USDT）", "金額", "名目 APR", "淨 APR（扣15%）", "利息貢獻"],
    ["0 – 500（Bonus）", "500", "10.00%", "8.50%", "$42.50"],
    ["500 – 1,000,000（市場浮動，中位 3.5%）", "999,500", "3.50%", "2.975%", "$29,735.13"],
    ["合計", "1,000,000", "—", "—", "$29,777.63"],
  ], { x: 0.6, y: 3.9, w: 8.1, colW: [3.2, 1.4, 1.2, 1.5, 0.8], fontSize: 10, centerCols: [1, 2, 3, 4], rowH: 0.5, boldCols: [] });

  statCallout(s, 8.95, 3.9, 3.78, 1.5, "2.98%", "加權平均 Effective APY（中位情境）", { valueSize: 30 });
  statCallout(s, 8.95, 5.55, 3.78, 1.15, "1.70%–4.25%", "浮動區間（市場APR 2%–5%）", { valueSize: 20, valueColor: NAVY, fill: LIGHT_TINT2 });
  footer(s, "6 / 16");
}

/* ============ SLIDE 7: BINANCE FLEXIBLE ============ */
{
  const s = newSlide();
  sectionTitle(s, "③ Binance USDT 活期理財（Simple Earn 活期）", "階梯利率結構穿透：百萬美元規模真實有效年化");

  card(s, 0.6, 1.65, 5.95, 2.0, "運作架構",
    "用戶 USDT 併入 Binance 整體資金池，依 Real-Time APR（每分鐘更新）計息。SAFU 保護基金：2026年2月完成組成調整，原約10億美元穩定幣儲備轉換為約15,000枚BTC，承諾跌破8億美元將補充；整體 PoR 截至2025年底約1,628億美元。",
    { fill: LIGHT_TINT2, bodySize: 11.5 });

  card(s, 6.75, 1.65, 5.98, 2.0, "階梯利率（官方實例）",
    "USDT Flexible：Real-Time APR 約 1.5%；前 200 USDT 另享 Bonus Tiered APR 3.0%（合計約 4.5%）。另有促銷公告「最高可達 6% APR」，惟同樣僅適用於極小額促銷級距。",
    { fill: LIGHT_TINT, bodySize: 11.5 });

  stdTable(s, [
    ["級距（USDT）", "金額", "適用利率", "利息貢獻"],
    ["0 – 200（Real-Time + Bonus）", "200", "4.50%", "$9.00"],
    ["200 – 1,000,000（Real-Time APR）", "999,800", "1.50%", "$14,997.00"],
    ["合計", "1,000,000", "—", "$15,006.00"],
  ], { x: 0.6, y: 3.9, w: 8.1, colW: [3.6, 1.6, 1.4, 1.5], fontSize: 10.5, centerCols: [1, 2, 3], rowH: 0.5 });

  statCallout(s, 8.95, 3.9, 3.78, 1.5, "1.50%", "加權平均 Effective APY", { valueSize: 30 });
  card(s, 8.95, 5.55, 3.78, 1.15, null,
    "Bonus 級距僅佔百萬資金之 0.02%，機構規模有效年化幾乎完全收斂至 Real-Time APR 基礎利率。",
    { fill: LIGHT_TINT2, bodySize: 10.5 });
  footer(s, "7 / 16");
}

/* ============ SLIDE 8: CAPITAL DRAG CHART ============ */
{
  const s = newSlide();
  sectionTitle(s, "活期理財：頭牌利率 vs. 機構規模真實年化", "百萬美元資金之「階梯利率稀釋效應」量化對比");

  s.addChart(pres.ChartType.bar, [
    { name: "行銷頭牌利率（小額適用）", labels: ["OKX 活期", "Binance 活期"], values: [10.0, 4.5] },
    { name: "百萬美元 Effective APY", labels: ["OKX 活期", "Binance 活期"], values: [2.98, 1.50] },
  ], {
    x: 0.6, y: 1.65, w: 7.2, h: 4.3,
    barDir: "col", barGrouping: "clustered",
    chartColors: [BORDER.replace("E2E8F0", "CBD5E1"), ACCENT],
    showTitle: true, title: "年化利率對比（%）", titleFontFace: FONT, titleFontSize: 13, titleColor: NAVY,
    showValue: true, dataLabelPosition: "outEnd", dataLabelFontSize: 10.5, dataLabelColor: NAVY, dataLabelFormatCode: '0.00"%"',
    catAxisLabelFontFace: FONT, catAxisLabelFontSize: 11, catAxisLabelColor: SLATE,
    valAxisLabelFontFace: FONT, valAxisLabelFontSize: 9, valAxisLabelColor: MUTED,
    valGridLine: { color: BORDER, size: 0.75 }, catGridLine: { style: "none" },
    showLegend: true, legendPos: "b", legendFontFace: FONT, legendFontSize: 10, legendColor: SLATE,
  });

  statCallout(s, 8.1, 1.65, 4.63, 1.55, "$84,878 / $44,994", "OKX / Binance 年度資本拖累（Capital Drag）", { valueSize: 20 });
  card(s, 8.1, 3.35, 4.63, 2.6, "財務部審查重點",
    "行銷頁面高年化僅具「獲客展示」意義，對百萬美元等級機構資金不具實質參考價值。若整筆 $1,000,000 均比照行銷頭牌利率估算，OKX 與 Binance 之實際年度利息分別短少約 $84,878 與 $44,994——此為配置活期理財時應納入之機會成本。",
    { fill: LIGHT_TINT2, bodySize: 11.5 });
  footer(s, "8 / 16");
}

/* ============ SLIDE 9: OKX DUAL INVESTMENT ============ */
{
  const s = newSlide();
  sectionTitle(s, "④ OKX 雙幣贏（Dual Investment）", "選擇權權利金本質與百萬資金情境損益試算");

  card(s, 0.6, 1.6, 5.95, 1.7, "金融工程本質",
    "低買（Buy Low）＝出售看跌期權（Short Put）；高賣（Sell High）＝出售看漲期權（Short Call）。年化利率＝固定報酬率×365÷Term，本質為選擇權權利金之年化換算，而非傳統利息。「距離現貨越近，年化越高，但轉換機率亦提高」（OKX官方說明）。",
    { fill: LIGHT_TINT, bodySize: 11 });

  card(s, 6.75, 1.6, 5.98, 1.7, "示意範例設定",
    "BTC/USDT 現貨 $60,000｜行使價 $57,000（價外5%）｜天期 7天｜示意年化 45%\n權利金收入 ≈ $8,630.14（本金 $1,000,000）",
    { fill: LIGHT_TINT2, bodySize: 12 });

  stdTable(s, [
    ["情境", "結算條件", "期末總值", "單週報酬率"],
    ["情境1：價外到期", "結算價 ≥ $57,000", "$1,008,630.14", "+0.86%"],
    ["情境2：小幅價內", "結算價 $55,000", "$973,542.44", "-2.65%"],
    ["情境3：深度價內（暴跌25%）", "結算價 $45,000", "$798,104.74", "-20.19%"],
  ], { x: 0.6, y: 3.55, w: PW - 1.2, colW: [3.4, 2.8, 2.9, 2.23], fontSize: 11, centerCols: [1, 2, 3], rowH: 0.55 });

  card(s, 0.6, 5.75, PW - 1.2, 1.15, "財務運用場景",
    "① 設定目標價逢低分批建倉：於等待建倉價位期間同時賺取權利金｜② 震盪市掛深度價外（OTM 10%+）收益增強：降低轉換機率，以較低年化換取較高本金安全邊際",
    { fill: LIGHT_TINT2, bodySize: 11 });
  footer(s, "9 / 16");
}

/* ============ SLIDE 9B: WHEEL STRATEGY (rolling re-sell at same strike) ============ */
{
  const s = newSlide();
  sectionTitle(s, "④ 進階策略：轉換後之滾動掛單（\"Wheel\" 策略）", "本金轉為 BTC 後不認賠平倉，改以同一行使價反向掛「高賣」等待價格回升");

  card(s, 0.6, 1.6, 5.95, 2.1, "怎麼做？（Covered-Call Wheel 概念）",
    "① 低買轉換為 BTC 後，② 立即以持有之 BTC、相同行使價（$55,900）掛出「高賣」收取權利金；③ 若到期未漲破，繼續持有 BTC 並重複掛單；④ 一旦漲破，BTC 依原行使價換回 USDT，本金名目值完整取回，且期間累積之權利金全數保留。",
    { fill: LIGHT_TINT, bodySize: 11 });

  stdTable(s, [
    ["週期", "操作", "示意年化", "本期權利金", "結算結果"],
    ["第1週 低買", "$1,000,000→轉換為17.8891 BTC", "40%", "$7,671", "跌破，轉換為BTC"],
    ["第2週 高賣", "同一行使價 $55,900 滾動掛單", "32%", "$5,823", "未漲破，續留BTC"],
    ["第3週 高賣", "同一行使價 $55,900 滾動掛單", "38%", "$7,042", "漲破，換回USDT"],
  ], { x: 6.75, y: 1.6, w: 5.98, colW: [1.15, 2.13, 1.0, 1.1, 1.6], fontSize: 9, rowH: 0.5 });

  statCallout(s, 0.6, 3.95, 3.9, 1.55, "+2.05%（3週）", "順利路徑：本金全數取回＋累積權利金 $20,535", { valueSize: 22, valueColor: GOOD });
  statCallout(s, 4.7, 3.95, 3.9, 1.55, "-28.4%（未實現）", "對照情境：10週價格未回升，帳面浮虧 $284,436", { valueSize: 22, valueColor: WARN, fill: LIGHT_TINT2 });
  card(s, 8.75, 3.95, 3.98, 1.55, "關鍵前提",
    "「不會虧錢」僅在最終價格確實回升至原行使價、且過程中未改用更低行使價時成立。",
    { fill: LIGHT_TINT2, bodySize: 10.5 });

  card(s, 0.6, 5.7, PW - 1.2, 1.2, "財務部應理解之三項限制",
    "① 權利金隨套牢加深而遞減（越價外，權利金越低，非維持初始水準）｜② 價格回升時間無保證，資金於等待期間無法投入其他生息工具（機會成本）｜③ FVTPL會計原則下，未回升期間之BTC部位仍須逐期認列未實現跌價損失，非「零風險」",
    { fill: LIGHT_TINT, bodySize: 10.5 });
  footer(s, "10 / 16");
}

/* ============ SLIDE 9C: MONTE CARLO FULL-YEAR SIMULATION ============ */
{
  const s = newSlide();
  sectionTitle(s, "④ 全年模擬：兩種操作規則的年化報酬分布", "蒙地卡羅模擬（20,000條路徑）｜現貨$77,000｜年化波動55%｜7天一期，全年52期｜零方向性假設");

  stdTable(s, [
    ["統計量", "規則1：最高收益(ATM)", "規則2：不被轉換(OTM緩衝)"],
    ["平均年化報酬", "-20.2%", "-24.1%"],
    ["中位數年化報酬", "-22.9%", "-24.8%"],
    ["P5（較差路徑）／P95（較佳路徑）", "-66.6% ／ +33.9%", "-66.3% ／ +19.2%"],
    ["全年虧損機率", "73.4%", "77.5%"],
    ["平均每年「卡住」週數", "45.0／52週", "42.7／52週"],
  ], { x: 0.6, y: 1.75, w: 7.3, colW: [2.7, 2.3, 2.3], fontSize: 10, rowH: 0.55 });

  statCallout(s, 8.1, 1.75, 4.63, 1.4, "兩規則平均皆為負", "在零方向性（不預設漲跌）基準情境下", { valueSize: 20, valueColor: WARN });
  card(s, 8.1, 3.3, 4.63, 2.1, "即使假設 BTC 全年+30%",
    "規則1平均年化仍為 -4.2%，規則2仍為 -11.6%——因「高賣」結構將上檔封頂於行使價，方向性上漲僅能間接透過「更快脫離套牢」受惠，無法直接參與漲幅。",
    { fill: LIGHT_TINT, bodySize: 11 });

  card(s, 0.6, 5.6, PW - 1.2, 1.3, "為什麼「年化最高」的規則，全年不一定比較好？",
    "出售選擇權收取權利金，本質是承接波動率風險換取補償；當市場願付的權利金不足以覆蓋標的實際波動帶來的潛在損失，長期反覆執行即呈現「多數週期小賺、少數週期大套牢」的負偏態分布。第9頁的+2.05%三週範例是單一幸運路徑，本頁呈現的才是全年反覆執行後的機率分布，財務部審查應以本頁為主要依據。",
    { fill: LIGHT_TINT2, bodySize: 10.5 });
  footer(s, "11 / 16");
}

/* ============ SLIDE 10: BINANCE DUAL INVESTMENT ============ */
{
  const s = newSlide();
  sectionTitle(s, "⑤ Binance 雙幣投資（Dual Investment）", "與 OKX 之產品架構對比");

  stdTable(s, [
    ["比較維度", "Binance 雙幣投資", "OKX 雙幣贏"],
    ["產品期限", "1 天至數週不等", "依市場條件動態設定"],
    ["標的資產豐富度", "BTC、ETH 及多組主流交易對", "BTC、ETH、USDT，六種投資策略組合"],
    ["交割時間點", "依產品條款固定時點交割", "每日 UTC+8 16:30 結算"],
    ["特色功能", "Auto-Compound：Basic／Advanced方案，依是否觸及目標價自動再訂閱", "提前贖回（Early Redemption）：可主動平倉，惟通常犧牲部分權利金"],
  ], { x: 0.6, y: 1.65, w: PW - 1.2, colW: [2.4, 5.2, 4.73], fontSize: 11, rowH: 0.62 });

  statCallout(s, 0.6, 4.85, 3.9, 1.85, "4%–138%", "官方揭露存款貨幣年化區間", { valueSize: 26 });
  card(s, 4.7, 4.85, 4.0, 1.85, "歷史高點",
    "部分特定高波動性商品之歷史公告年化甚至達 175%。行使價越接近現貨、天期越短，年化通常越高，但轉換機率亦同步提高，與 OKX 定價邏輯一致。",
    { fill: LIGHT_TINT2, bodySize: 11 });
  card(s, 8.9, 4.85, 3.83, 1.85, "財務運用場景",
    "高賣獲利了結：對已持有 BTC/ETH 部位設定目標賣出價｜低買策略性積累：搭配 Auto-Compound 系統化執行，惟須留意連續期間累積曝險",
    { fill: LIGHT_TINT, bodySize: 10.5 });
  footer(s, "12 / 16");
}

/* ============ SLIDE 11: ACCOUNTING MATRIX ============ */
{
  const s = newSlide();
  sectionTitle(s, "財務部專題：會計處理與外部審計", "IFRS 認列基礎與 Big 4 查核複雜度對比");

  stdTable(s, [
    ["比較維度", "Bitfinex USD 放貸", "OKX/Binance 活期理財", "OKX/Binance 雙幣理財"],
    ["建議會計科目", "現金及約當現金／短期金融資產", "虛擬資產存貨或無形資產", "嵌入式衍生工具（FVTPL）"],
    ["計價貨幣風險", "無", "有（USDT 脫錨風險）", "有（計價幣別＋標的雙重波動）"],
    ["期末公允價值評價模型", "不需複雜評價", "需依市價評價", "需選擇權定價模型（Black-Scholes）"],
    ["減損測試", "不適用", "適用", "適用（拆解主合約與衍生工具）"],
    ["外部審計函證難度", "中等", "中等偏難", "高難度"],
    ["合規成本（相對排序）", "低", "中", "高"],
  ], { x: 0.6, y: 1.65, w: PW - 1.2, colW: [2.6, 3.2, 3.7, 2.83], fontSize: 10.5, centerCols: [], rowH: 0.62 });
  footer(s, "13 / 16");
}

/* ============ SLIDE 12: COMPREHENSIVE MATRIX ============ */
{
  const s = newSlide();
  sectionTitle(s, "五大策略綜合決策矩陣", "Comprehensive Comparison Matrix");

  stdTable(s, [
    ["指標", "Bitfinex", "OKX活期", "Binance活期", "OKX雙幣贏", "Binance雙幣"],
    ["收益本質", "利息收入", "利息（稀釋）", "利息（稀釋）", "選擇權權利金", "選擇權權利金"],
    ["百萬資金 APY", "4.25–17.0%+", "1.70–4.25%", "約1.50%", "名目4–138%", "官方4–138%"],
    ["本金保障", "不受市場方向影響", "承擔平台信用曝險", "承擔平台信用曝險", "可能強制轉換資產", "可能強制轉換資產"],
    ["Delta 風險", "無", "低", "低", "有", "有"],
    ["流動性召回", "天期鎖定(2–120天)", "即時", "即時", "鎖定至結算日", "鎖定至結算日"],
    ["會計複雜度", "低", "中", "中", "高", "高"],
  ], { x: 0.6, y: 1.65, w: PW - 1.2, colW: [2.13, 2.24, 2.24, 2.24, 2.24, 2.24], fontSize: 9.5, centerCols: [1, 2, 3, 4, 5], rowH: 0.62 });
  footer(s, "14 / 16");
}

/* ============ SLIDE 13: ALLOCATION MODELS ============ */
{
  const s = newSlide();
  sectionTitle(s, "財務部資產配置模擬模型", "三種全配置權重方案｜本金 $1,000,000");

  s.addChart(pres.ChartType.bar, [
    { name: "Blended APY", labels: ["模型A\n穩健防禦型", "模型B\n平衡收益型", "模型C\n戰術成長型"], values: [12.15, 17.36, 22.56] },
  ], {
    x: 0.6, y: 1.6, w: 5.9, h: 3.3,
    barDir: "col", chartColors: [ACCENT],
    showTitle: true, title: "綜合加權年化 Blended APY（%）", titleFontFace: FONT, titleFontSize: 12, titleColor: NAVY,
    showValue: true, dataLabelPosition: "outEnd", dataLabelFontSize: 11, dataLabelColor: NAVY, dataLabelFormatCode: '0.00"%"',
    catAxisLabelFontFace: FONT, catAxisLabelFontSize: 10, catAxisLabelColor: SLATE,
    valAxisLabelFontFace: FONT, valAxisLabelFontSize: 9, valAxisLabelColor: MUTED,
    valGridLine: { color: BORDER, size: 0.75 }, catGridLine: { style: "none" },
    showLegend: false, valAxisMaxVal: 25,
  });

  stdTable(s, [
    ["模型", "Bitfinex", "OKX活期", "Binance活期", "OKX雙幣", "Binance雙幣", "年度收益"],
    ["A 穩健防禦型", "70%", "10%", "10%", "5%", "5%", "$121,500"],
    ["B 平衡收益型", "55%", "10%", "10%", "15%", "10%", "$173,600"],
    ["C 戰術成長型", "40%", "10%", "10%", "20%", "20%", "$225,600"],
  ], { x: 6.75, y: 1.6, w: 5.98, colW: [1.5, 0.85, 0.85, 0.95, 0.8, 0.98, 1.05], fontSize: 8.8, centerCols: [1, 2, 3, 4, 5, 6], rowH: 0.55 });

  card(s, 6.75, 3.85, 5.98, 1.05, null,
    "無方向性曝險部位佔比：A 75%／B 55%／C 40%｜T+0 流動性緩衝均為 20%｜雙幣理財曝險合計：A 10%／B 25%／C 40%",
    { fill: LIGHT_TINT2, bodySize: 10.5 });

  card(s, 0.6, 5.1, PW - 1.2, 1.6, "方法論揭露（重要）",
    "雙幣理財之 45% 年化係採「未觸及行使價（價外到期）」情境計算，未反映觸價本金轉換損失。若納入機率加權情境分析，實際綜合年化將視市場波動與觸價機率顯著偏離本表數字，甚至於單一結算週期內轉為負值，詳見報告第 6、7 章情境試算。",
    { fill: LIGHT_TINT, bodySize: 11 });
  footer(s, "15 / 16");
}

/* ============ SLIDE 14: GOVERNANCE + ROADMAP + CLOSE (white background) ============ */
{
  const s = newSlide(WHITE);
  s.addText("內控架構與推進時程", {
    x: 0.6, y: 0.5, w: PW - 1.2, h: 0.6, fontFace: FONT, bold: true, fontSize: 28, color: NAVY, isTextBox: true, margin: 0,
  });

  const guard = [
    ["最小授權", "API 僅開放出借／理財申購，物理封閉提幣與轉帳"],
    ["IP 白名單", "固定內部 VPC 出口 IP，企業 KMS 加密金鑰"],
    ["OTM 緩衝門檻", "雙幣理財行使價距離建議 ≥ 8%，納入交易員 SOP"],
    ["Kill-Switch", "異常事件自動預警，觸發後停止新單並緊急處置"],
  ];
  let gy = 1.5;
  guard.forEach((g) => {
    circleLabel(s, 0.6, gy, 0.45, "•", { fill: LIGHT_TINT, color: ACCENT, fontSize: 18 });
    s.addText(g[0], { x: 1.2, y: gy - 0.02, w: 2.05, h: 0.5, fontFace: FONT, bold: true, fontSize: 12.5, color: NAVY, isTextBox: true, margin: 0, valign: "middle" });
    s.addText(g[1], { x: 3.3, y: gy - 0.02, w: 3.4, h: 0.5, fontFace: FONT, fontSize: 10, color: SLATE, isTextBox: true, margin: 0, valign: "middle", lineSpacingMultiple: 1.1 });
    gy += 0.75;
  });

  const phases = [
    ["Phase 1", "會簽授權與 API 設定", "2–4 週"],
    ["Phase 2", "小規模沙盒試點（五項工具）", "2–3 個月"],
    ["Phase 3", "常態化配置與自動化部署", "Phase 2 結束後 1 個月內啟動"],
  ];
  let px = 7.3;
  const phaseW = 1.55, phaseGap = 0.28;
  phases.forEach((p, i) => {
    const w = phaseW;
    s.addShape("roundRect", { x: px, y: 1.5, w, h: 3.0, rectRadius: 0.08, fill: { color: LIGHT_TINT2 }, line: { color: BORDER, width: 0.75 } });
    s.addText(p[0], { x: px + 0.13, y: 1.65, w: w - 0.26, h: 0.35, fontFace: FONT, bold: true, fontSize: 12.5, color: ACCENT, isTextBox: true, margin: 0 });
    s.addText(p[1], { x: px + 0.13, y: 2.05, w: w - 0.26, h: 1.5, fontFace: FONT, fontSize: 9.5, color: NAVY, isTextBox: true, margin: 0, lineSpacingMultiple: 1.2 });
    s.addText(p[2], { x: px + 0.13, y: 3.9, w: w - 0.26, h: 0.5, fontFace: FONT, fontSize: 8.5, color: MUTED, isTextBox: true, margin: 0 });
    if (i < phases.length - 1) {
      s.addText("→", { x: px + w, y: 2.7, w: phaseGap, h: 0.6, fontFace: FONT, fontSize: 16, color: MUTED, align: "center", isTextBox: true, margin: 0 });
    }
    px += w + phaseGap;
  });

  s.addShape("line", { x: 0.6, y: 4.85, w: PW - 1.2, h: 0, line: { color: BORDER, width: 0.75 } });

  s.addText("下一步", { x: 0.6, y: 5.05, w: 4, h: 0.4, fontFace: FONT, bold: true, fontSize: 16, color: NAVY, isTextBox: true, margin: 0 });
  s.addText(
    "請財務部、風控委員會與法遵室完成本報告會簽，核定 Phase 1 啟動時程與各平台曝險上限、雙幣理財 OTM 緩衝門檻，以及模型 A／B／C 或客製化配置權重。",
    { x: 0.6, y: 5.5, w: PW - 1.2, h: 0.8, fontFace: FONT, fontSize: 13, color: SLATE, isTextBox: true, margin: 0, lineSpacingMultiple: 1.25 }
  );

  footer(s, "16 / 16");
}

pres.writeFile({ fileName: process.argv[2] || "output.pptx" }).then((fileName) => {
  console.log("Written:", fileName);
});
