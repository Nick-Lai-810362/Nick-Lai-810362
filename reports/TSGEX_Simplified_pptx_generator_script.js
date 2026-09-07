const pptxgen = require("pptxgenjs");

// ---- Palette (same as detailed deck, per user spec) ----
const WHITE = "FFFFFF";
const NAVY = "0F172A";
const SLATE = "334155";
const ACCENT = "2563EB";
const LIGHT_TINT = "EFF6FF";
const LIGHT_TINT2 = "F8FAFC";
const BORDER = "E2E8F0";
const MUTED = "64748B";
const GOOD = "16A34A";
const AMBER = "B45309";

const FONT = "Microsoft JhengHei";

const pres = new pptxgen();
pres.layout = "LAYOUT_WIDE";
const PW = 13.333, PH = 7.5;

function newSlide(bg = WHITE) {
  const s = pres.addSlide();
  s.background = { color: bg };
  return s;
}
function footer(s, pageLabel) {
  s.addText("TSGEX 資產管理部｜內部機密｜簡明版", {
    x: 0.5, y: PH - 0.4, w: 6, h: 0.3, fontFace: FONT, fontSize: 9, color: MUTED, isTextBox: true, margin: 0,
  });
  s.addText(pageLabel, {
    x: PW - 2.5, y: PH - 0.4, w: 2, h: 0.3, fontFace: FONT, fontSize: 9, color: MUTED, align: "right", isTextBox: true, margin: 0,
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
    x: 0.6, y: 0.4, w: PW - 1.2, h: 0.7, fontFace: FONT, bold: true, fontSize: 27,
    color: NAVY, align: "left", isTextBox: true, margin: 0,
  });
  if (sub) {
    s.addText(sub, {
      x: 0.6, y: 1.05, w: PW - 1.2, h: 0.55, fontFace: FONT, fontSize: 13.5,
      color: MUTED, align: "left", isTextBox: true, margin: 0, lineSpacingMultiple: 1.15,
    });
  }
}
function card(s, x, y, w, h, title, body, opts = {}) {
  s.addShape("roundRect", {
    x, y, w, h, rectRadius: 0.08,
    fill: { color: opts.fill || LIGHT_TINT2 },
    line: { color: BORDER, width: 0.75 },
    shadow: { type: "outer", color: "1E293B", opacity: 0.08, blur: 6, offset: 2, angle: 90 },
  });
  if (title) {
    s.addText(title, {
      x: x + 0.22, y: y + 0.16, w: w - 0.44, h: 0.4, fontFace: FONT, bold: true,
      fontSize: opts.titleSize || 13.5, color: opts.titleColor || NAVY, align: "left", isTextBox: true, margin: 0,
    });
  }
  if (body) {
    s.addText(body, {
      x: x + 0.22, y: y + (title ? 0.58 : 0.16), w: w - 0.44, h: h - (title ? 0.76 : 0.32),
      fontFace: FONT, fontSize: opts.bodySize || 12, color: opts.bodyColor || SLATE,
      align: "left", valign: "top", isTextBox: true, margin: 0, lineSpacingMultiple: 1.25,
    });
  }
}
function statCallout(s, x, y, w, h, value, label, opts = {}) {
  s.addShape("roundRect", { x, y, w, h, rectRadius: 0.08, fill: { color: opts.fill || LIGHT_TINT }, line: { type: "none" } });
  s.addText(value, {
    x: x + 0.15, y: y + 0.12, w: w - 0.3, h: h - 0.55, fontFace: FONT, bold: true,
    fontSize: opts.valueSize || 26, color: opts.valueColor || ACCENT, align: "center", valign: "bottom", isTextBox: true, margin: 0,
  });
  s.addText(label, {
    x: x + 0.1, y: y + h - 0.42, w: w - 0.2, h: 0.35, fontFace: FONT, fontSize: 10.5,
    color: opts.labelColor || SLATE, align: "center", valign: "top", isTextBox: true, margin: 0,
  });
}
function stdTable(s, rows, opts) {
  const header = rows[0].map((t) => ({
    text: t, options: { fill: { color: NAVY }, color: WHITE, bold: true, fontSize: opts.fontSize || 11, align: "center", valign: "middle" },
  }));
  const body = rows.slice(1).map((r, ri) =>
    r.map((t) => ({
      text: t,
      options: { fill: { color: ri % 2 === 0 ? WHITE : LIGHT_TINT2 }, color: SLATE, fontSize: opts.fontSize || 11, align: "center", valign: "middle" },
    }))
  );
  s.addTable([header, ...body], {
    x: opts.x, y: opts.y, w: opts.w, colW: opts.colW,
    border: { type: "solid", color: BORDER, pt: 0.75 },
    autoPage: false, valign: "middle", margin: [0.06, 0.08, 0.06, 0.08], rowH: opts.rowH,
  });
}
// a plain-language "explainer" tag — small icon-less badge + text, used to translate jargon
function explainer(s, x, y, w, h, term, plain) {
  s.addShape("roundRect", { x, y, w, h, rectRadius: 0.07, fill: { color: LIGHT_TINT }, line: { type: "none" } });
  s.addText(term, {
    x: x + 0.18, y: y + 0.1, w: w - 0.36, h: 0.32, fontFace: FONT, bold: true, fontSize: 11.5, color: ACCENT, isTextBox: true, margin: 0,
  });
  s.addText(plain, {
    x: x + 0.18, y: y + 0.42, w: w - 0.36, h: h - 0.55, fontFace: FONT, fontSize: 10.5, color: SLATE, isTextBox: true, margin: 0, lineSpacingMultiple: 1.2,
  });
}

/* ============ SLIDE 1: TITLE ============ */
{
  const s = newSlide(WHITE);
  s.addShape("ellipse", { x: 10.4, y: -2.0, w: 5, h: 5, fill: { color: LIGHT_TINT }, line: { type: "none" } });
  s.addShape("ellipse", { x: -1.8, y: 5.4, w: 4, h: 4, fill: { color: LIGHT_TINT2 }, line: { color: BORDER, width: 0.75 } });

  s.addText("TSGEX 資產管理部　簡明版", {
    x: 0.9, y: 1.7, w: 11.5, h: 0.5, fontFace: FONT, fontSize: 15, color: ACCENT, bold: true, isTextBox: true, margin: 0, charSpacing: 2,
  });
  s.addText("公司閒置資金收益優化方案", {
    x: 0.9, y: 2.25, w: 11.5, h: 1.1, fontFace: FONT, fontSize: 40, color: NAVY, bold: true, isTextBox: true, margin: 0,
  });
  s.addText("以新台幣 500 萬元為例：五種常見「加密貨幣生息工具」一次看懂", {
    x: 0.9, y: 3.25, w: 11.5, h: 0.6, fontFace: FONT, fontSize: 18, color: SLATE, isTextBox: true, margin: 0,
  });
  s.addShape("line", { x: 0.9, y: 4.15, w: 3.2, h: 0, line: { color: ACCENT, width: 2 } });

  s.addText("寫給非加密貨幣背景的主管與同仁：專有名詞保留，但用白話說明每個機制在做什麼", {
    x: 0.9, y: 4.35, w: 10.5, h: 0.5, fontFace: FONT, fontSize: 12.5, color: MUTED, italic: true, isTextBox: true, margin: 0,
  });

  statCallout(s, 0.9, 5.15, 3.6, 1.4, "NT$5,000,000", "本次評估額度", { valueSize: 24 });
  statCallout(s, 4.7, 5.15, 3.6, 1.4, "5 種方法", "逐一拆解機制與風險", { valueSize: 24, valueColor: NAVY, fill: LIGHT_TINT2 });
  statCallout(s, 8.5, 5.15, 4.13, 1.4, "白話＋專有名詞", "看得懂，也講得出口", { valueSize: 20, valueColor: GOOD, fill: LIGHT_TINT2 });

  s.addText("內部機密｜2026年9月｜換算匯率約 1美元＝31.75新台幣", {
    x: 0.9, y: 6.75, w: 10, h: 0.35, fontFace: FONT, fontSize: 10.5, color: MUTED, isTextBox: true, margin: 0,
  });
}

/* ============ SLIDE 2: FRAMING ============ */
{
  const s = newSlide();
  sectionTitle(s, "我們想解決什麼問題？", "公司帳上有一筆暫時用不到的錢，放銀行活存利息很低，有沒有更好的做法？");

  card(s, 0.6, 1.75, 5.95, 2.1, "現況",
    "這筆錢目前主要放在銀行活存，利息接近 0。而美元的「無風險利率」（可以想成銀行間互相借錢的基準利率，代號叫 SOFR）目前約 3.66%，都比活存高出不少。",
    { fill: LIGHT_TINT2, bodySize: 13 });
  card(s, 6.75, 1.75, 5.98, 2.1, "機會",
    "加密貨幣交易平台上，有幾種「借錢給別人賺利息」或「賣保險賺保費」性質的產品，年化報酬可能明顯高於銀行利率——但機制不同，風險程度也差很多，需要逐一看懂。",
    { fill: LIGHT_TINT, bodySize: 13 });

  s.addText("這份簡報要回答三個問題", { x: 0.6, y: 4.15, w: 8, h: 0.4, fontFace: FONT, bold: true, fontSize: 16, color: NAVY, isTextBox: true, margin: 0 });

  const qs = [
    ["這 5 種方法，錢實際上是怎麼幫我們賺利息的？", "本金會不會因為市場漲跌而變少？"],
    ["用 NT$500 萬去做，一年大概能賺多少？", "有沒有比較「安全」跟比較「刺激」的組合？"],
  ];
  let qy = 4.7;
  [
    "① 這 5 種方法，錢實際上是怎麼幫我們賺利息的？",
    "② 本金會不會因為市場漲跌而變少（有沒有「賠錢」的可能）？",
    "③ 用 NT$500 萬去做，一年大概能賺多少？有沒有安全與積極的不同組合？",
  ].forEach((q) => {
    s.addText(q, { x: 0.6, y: qy, w: PW - 1.2, h: 0.5, fontFace: FONT, fontSize: 14, color: SLATE, isTextBox: true, margin: 0 });
    qy += 0.55;
  });
  footer(s, "2 / 12");
}

/* ============ SLIDE 3: FIVE METHODS OVERVIEW ============ */
{
  const s = newSlide();
  sectionTitle(s, "五種方法，一次看懂", "白話一句話＋風險等級");

  const items = [
    { n: "①", t: "Bitfinex\n美元出借", d: "把美元借給有抵押品的\n槓桿交易者賺利息", risk: "風險：低", color: GOOD, fill: LIGHT_TINT },
    { n: "②", t: "OKX\n活期理財", d: "錢存進交易所資金池，\n類似活存，隨時可領回", risk: "風險：低", color: GOOD, fill: LIGHT_TINT2 },
    { n: "③", t: "Binance\n活期理財", d: "同上，另一家交易所，\n可互相備援", risk: "風險：低", color: GOOD, fill: LIGHT_TINT2 },
    { n: "④", t: "OKX\n雙幣理財", d: "跟平台約定一個價格賺利息，\n搭配對的操作方式風險可控", risk: "風險：中等", color: AMBER, fill: LIGHT_TINT },
    { n: "⑤", t: "Binance\n雙幣理財", d: "同上，另一家交易所，\n機制幾乎相同", risk: "風險：中等", color: AMBER, fill: LIGHT_TINT },
  ];
  const cw = 2.32, gap = 0.16, startX = 0.6, y0 = 1.75, ch = 3.55;
  items.forEach((it, i) => {
    const x = startX + i * (cw + gap);
    s.addShape("roundRect", { x, y: y0, w: cw, h: ch, rectRadius: 0.1, fill: { color: it.fill }, line: { color: BORDER, width: 0.75 } });
    circleLabel(s, x + 0.18, y0 + 0.2, 0.5, it.n, { fill: WHITE, color: ACCENT, fontSize: 16 });
    s.addText(it.t, { x: x + 0.18, y: y0 + 0.85, w: cw - 0.36, h: 0.75, fontFace: FONT, bold: true, fontSize: 14, color: NAVY, isTextBox: true, margin: 0, lineSpacingMultiple: 1.05 });
    s.addText(it.d, { x: x + 0.18, y: y0 + 1.65, w: cw - 0.36, h: 1.1, fontFace: FONT, fontSize: 11, color: SLATE, isTextBox: true, margin: 0, lineSpacingMultiple: 1.25 });
    s.addShape("roundRect", { x: x + 0.18, y: y0 + 2.85, w: cw - 0.36, h: 0.45, rectRadius: 0.1, fill: { color: WHITE }, line: { color: it.color, width: 1 } });
    s.addText(it.risk, { x: x + 0.18, y: y0 + 2.85, w: cw - 0.36, h: 0.45, fontFace: FONT, bold: true, fontSize: 11.5, color: it.color, align: "center", valign: "middle", isTextBox: true, margin: 0 });
  });

  s.addText("「風險：低」不代表零風險——仍有交易所信用風險；詳細說明在後面各方法的頁面", {
    x: 0.6, y: 5.55, w: PW - 1.2, h: 0.4, fontFace: FONT, fontSize: 11, color: MUTED, italic: true, isTextBox: true, margin: 0,
  });
  footer(s, "3 / 12");
}

/* ============ SLIDE 4: BITFINEX ============ */
{
  const s = newSlide();
  sectionTitle(s, "方法① Bitfinex 美元出借", "白話說明：把美元借給「開槓桿」的交易者，對方要先抵押更多錢");

  explainer(s, 0.6, 1.65, 5.95, 1.75, "這是什麼？（保證金融資出借 Margin Funding）",
    "你把美元放進平台的「出借池」，有人想用槓桿做交易（等於跟平台多借一筆錢去買賣），就會用你的美元，並支付利息給你。這筆交易全程用美元計價，不受加密貨幣漲跌影響你的本金。");
  explainer(s, 6.75, 1.65, 5.98, 1.75, "為什麼算安全？（超額抵押＋強制平倉）",
    "借錢的人必須先抵押「超過」借款金額的資產（例如抵押 120 元才能借 100 元）。如果抵押品價值下跌到快不夠賠，系統會自動賣掉抵押品先還你錢——類似房貸繳不出來、銀行拍賣房子的概念。");

  stdTable(s, [
    ["情境", "年利率（已扣平台費）", "NT$500萬，一年大約賺"],
    ["保守（市場冷清）", "4.25%", "NT$212,500"],
    ["基準（近期市場行情）", "10.29%", "NT$514,500"],
    ["樂觀（市場火熱）", "17.0%以上", "NT$850,000以上"],
  ], { x: 0.6, y: 3.6, w: 8.1, colW: [3.0, 2.6, 2.5], fontSize: 12, rowH: 0.55 });

  card(s, 8.95, 3.6, 3.78, 2.35, "白話重點",
    "• 賺的是「利息」，不是賭價格漲跌\n• 本金不會因為比特幣漲跌而變少\n• 最大風險是「平台本身」出事（詳見第9頁）",
    { fill: LIGHT_TINT, bodySize: 11.5 });
  footer(s, "4 / 12");
}

/* ============ SLIDE 5: CEX FLEXIBLE SAVINGS ============ */
{
  const s = newSlide();
  sectionTitle(s, "方法②③ 交易所活期理財（OKX／Binance）", "白話說明：類似把錢存進「數位活存」，但要注意「宣傳利率」的陷阱");

  explainer(s, 0.6, 1.65, PW - 1.2, 1.5, "這是什麼？",
    "把美元（或美元穩定幣 USDT）存進交易所，交易所把大家的錢集中運用（借給其他人），再依「利率」分潤給你，隨時可以領回，很像數位版的活期存款。");

  card(s, 0.6, 3.3, 6.0, 2.35, "⚠ 常見的「宣傳利率」陷阱",
    "廣告上常看到「年化 10%」，但這個高利率通常只適用「前面一小筆錢」（例如前 500 美元，約新台幣 1.6 萬元），超過這筆金額的部分，利率會大幅降到 1.5%～3.5% 左右。",
    { fill: LIGHT_TINT, bodySize: 12.5 });

  stdTable(s, [
    ["平台", "廣告最高利率", "NT$500萬實際到手利率", "一年實際約賺"],
    ["OKX 活期理財", "10.0%", "約 3.0%", "約 NT$150,000"],
    ["Binance 活期理財", "6.0%", "約 1.5%", "約 NT$75,000"],
  ], { x: 6.9, y: 3.3, w: 5.83, colW: [1.7, 1.4, 1.53, 1.2], fontSize: 10, rowH: 0.6 });

  card(s, 6.9, 5.35, 5.83, 1.5, "這類方法的價值在哪？",
    "利率雖然不高，但「隨時可以領回」，適合當作臨時要用錢時的備援資金池，而不是主力賺利息的方法。",
    { fill: LIGHT_TINT2, bodySize: 11.5 });
  footer(s, "5 / 12");
}

/* ============ SLIDE 6: DUAL INVESTMENT ============ */
{
  const s = newSlide();
  sectionTitle(s, "方法④⑤ 雙幣理財（OKX／Binance）", "白話說明：跟平台約定一個價格賺利息，五種方法中年化最高，但要搭配正確做法");

  explainer(s, 0.6, 1.65, PW - 1.2, 1.55, "這是什麼？（選擇權權利金 Option Premium）",
    "你先約定一個「目標價格」，平台付你一筆錢（類似保險公司收的保費，這裡反過來是你收錢）。如果到期時價格沒有跌破（或漲破）目標價，你連本金帶「利息」全部拿回；但如果價格跌破（或漲破）目標價，你的本金會被「強制」換成當時已經比較不划算的另一種資產——等於你被迫低價買進或高價賣出。這時候不用急著認賠，換個方式繼續操作即可（下一頁說明）。");

  stdTable(s, [
    ["結果", "情境", "NT$500萬，一週後大約變成"],
    ["✅ 沒有跌破目標價（最常見）", "拿回本金＋額外利息", "NT$5,043,000（+0.86%）"],
    ["⚠ 小幅跌破目標價", "本金被換成較不划算的資產", "NT$4,868,000（-2.65%）"],
    ["🔴 單週大跌 25%（極端行情）", "本金被換成大幅貶值的資產", "NT$3,991,000（-20.19%）"],
  ], { x: 0.6, y: 3.4, w: PW - 1.2, colW: [3.6, 3.53, 3.6], fontSize: 11.5, rowH: 0.62 });

  card(s, 0.6, 5.6, PW - 1.2, 1.25, "白話重點",
    "廣告上看到的「年化 45%」，是「猜對方向」才有的報酬；猜錯的那一週帳面會變少，但不是永久的損失——只要不急著認賠賣掉，換個方式繼續操作，通常可以把本金拿回來，詳見下一頁。",
    { fill: LIGHT_TINT, bodySize: 12.5 });
  footer(s, "6 / 12");
}

/* ============ SLIDE 6B: TAKE-PROFIT DISCIPLINE (plain language) ============ */
{
  const s = newSlide();
  sectionTitle(s, "雙幣理財怎麼玩比較安全？一個簡單的紀律", "測試了整整一年、兩萬種可能的走勢，找到一個關鍵做法");

  explainer(s, 0.6, 1.65, PW - 1.2, 1.6, "如果猜錯方向，錢被換成別的資產，接下來怎麼辦？",
    "不要急著認賠賣掉。改用手上這批資產，重新約定「原本那個價格」繼續賺利息——只要之後價格漲回原本那個價格，就能把錢全部換回來，而且中間收的利息全部歸你，本金完全不會少。這個做法我們稱為「滾動操作」。");

  stdTable(s, [
    ["做法", "一整年下來，錢變少的機率"],
    ["猜錯了就一直用最新價格重新開始（不建議）", "74.5% ～ 85.1%"],
    ["猜錯了先滾動操作，等本金拿回來就先收手、不馬上再下注", "18.9% ～ 20.4%"],
  ], { x: 0.6, y: 3.55, w: PW - 1.2, colW: [6.5, 6.13], fontSize: 12, rowH: 0.75, centerCols: [1] });

  statCallout(s, 0.6, 5.15, 3.9, 1.6, "只多做一件事", "把「錢變少的機率」從7～8成\n降到約2成", { valueSize: 18, valueColor: GOOD });
  card(s, 4.7, 5.15, 3.9, 1.6, "這一件事是什麼？",
    "本金拿回來以後，先把錢放著（賺其他方法的利息），不要立刻又下一注——這是唯一的差別。",
    { fill: LIGHT_TINT, bodySize: 11.5 });
  card(s, 8.7, 5.15, 4.03, 1.6, "白話結論",
    "雙幣理財不是不能碰，是不能「一直重複下注」；照這個紀律操作，用NT$500萬的一部分來做，是合理的選項。",
    { fill: LIGHT_TINT2, bodySize: 11 });
  footer(s, "7 / 12");
}

/* ============ SLIDE 7: COMPARISON TABLE ============ */
{
  const s = newSlide();
  sectionTitle(s, "一張表看懂五種方法的差異", "簡化對比，更多細節在完整版報告");

  stdTable(s, [
    ["方法", "賺的是什麼", "本金會因市場漲跌變少嗎？", "多快可以領回", "NT$500萬約略年化"],
    ["① Bitfinex 出借", "借錢的利息", "不會", "數天～數月不等", "4.25%–17%+"],
    ["② OKX 活期", "存款的利差", "不會（幣值本身穩定）", "隨時", "約 3.0%"],
    ["③ Binance 活期", "存款的利差", "不會（幣值本身穩定）", "隨時", "約 1.5%"],
    ["④ OKX 雙幣理財", "猜價格的「獎金」", "會，猜錯先變少", "要等到結算日", "名目 4%–138%"],
    ["⑤ Binance 雙幣理財", "猜價格的「獎金」", "會，猜錯先變少", "要等到結算日", "官方 4%–138%"],
  ], { x: 0.6, y: 1.7, w: PW - 1.2, colW: [2.4, 2.1, 2.83, 2.0, 2.0], fontSize: 10.5, rowH: 0.68 });

  card(s, 0.6, 6.05, PW - 1.2, 0.85, null,
    "簡單說：①②③賺的是「利息」，本金不會因為比特幣漲跌而變少；④⑤賺的是「猜對價格的獎金」，猜錯本金會暫時變少，但只要照第7頁的紀律操作，一年下來變少的機率可以壓到約2成。",
    { fill: LIGHT_TINT, bodySize: 12 });
  footer(s, "8 / 12");
}

/* ============ SLIDE 8: NT$5M SUMMARY CHART ============ */
{
  const s = newSlide();
  sectionTitle(s, "如果 NT$500 萬全部投入某一種方法，一年大概賺多少？", "以「基準情境」試算，僅供比較用，非投資建議");

  s.addChart(pres.ChartType.bar, [
    {
      name: "一年預估獲利（新台幣）",
      labels: ["①Bitfinex\n出借", "②OKX\n活期", "③Binance\n活期", "④OKX\n雙幣(未賭錯)", "⑤Binance\n雙幣(未賭錯)"],
      values: [514500, 150000, 75000, 2250000, 2250000],
    },
  ], {
    x: 0.6, y: 1.7, w: 8.2, h: 4.2,
    barDir: "col", chartColors: [ACCENT],
    showTitle: true, title: "一年預估獲利（新台幣元）", titleFontFace: FONT, titleFontSize: 13, titleColor: NAVY,
    showValue: true, dataLabelPosition: "outEnd", dataLabelFontSize: 10, dataLabelColor: NAVY, dataLabelFormatCode: "#,##0",
    catAxisLabelFontFace: FONT, catAxisLabelFontSize: 10, catAxisLabelColor: SLATE,
    valAxisLabelFontFace: FONT, valAxisLabelFontSize: 9, valAxisLabelColor: MUTED,
    valGridLine: { color: BORDER, size: 0.75 }, catGridLine: { style: "none" }, showLegend: false,
  });

  card(s, 9.0, 1.7, 3.73, 2.0, "為什麼④⑤特別高？",
    "雙幣理財的「45%」是「沒有賭錯」的最佳情況，並未反映賭錯時可能虧損 20% 以上的情形——數字看起來漂亮，但風險也最高，不能只看這張圖的高度做決定。",
    { fill: LIGHT_TINT, bodySize: 11 });
  card(s, 9.0, 3.85, 3.73, 2.05, "務實的看法",
    "①Bitfinex 出借在「不賭價格」的前提下，一年約 NT$51 萬，是五種方法中「報酬與安全」平衡最好的選項。",
    { fill: LIGHT_TINT2, bodySize: 11.5 });
  footer(s, "9 / 12");
}

/* ============ SLIDE 9: ALLOCATION MODELS ============ */
{
  const s = newSlide();
  sectionTitle(s, "建議怎麼分配？三種組合方案", "NT$500萬，依「求穩」到「求高報酬」排列");

  s.addChart(pres.ChartType.bar, [
    { name: "一年預估獲利", labels: ["方案A\n求穩為主", "方案B\n穩中求進", "方案C\n積極型"], values: [607500, 868000, 1128000] },
  ], {
    x: 0.6, y: 1.65, w: 5.9, h: 3.3,
    barDir: "col", chartColors: [ACCENT],
    showTitle: true, title: "一年預估獲利（新台幣元）", titleFontFace: FONT, titleFontSize: 12, titleColor: NAVY,
    showValue: true, dataLabelPosition: "outEnd", dataLabelFontSize: 10.5, dataLabelColor: NAVY, dataLabelFormatCode: "#,##0",
    catAxisLabelFontFace: FONT, catAxisLabelFontSize: 10, catAxisLabelColor: SLATE,
    valAxisLabelFontFace: FONT, valAxisLabelFontSize: 9, valAxisLabelColor: MUTED,
    valGridLine: { color: BORDER, size: 0.75 }, catGridLine: { style: "none" }, showLegend: false,
  });

  stdTable(s, [
    ["方案", "①出借", "②③活期", "④⑤雙幣", "一年預估獲利"],
    ["A 求穩為主", "70%", "20%", "10%", "NT$607,500"],
    ["B 穩中求進", "55%", "20%", "25%", "NT$868,000"],
    ["C 積極型", "40%", "20%", "40%", "NT$1,128,000"],
  ], { x: 6.75, y: 1.65, w: 5.98, colW: [1.55, 1.15, 1.3, 1.15, 0.83], fontSize: 10, rowH: 0.6 });

  card(s, 6.75, 3.9, 5.98, 1.0, null,
    "「④⑤雙幣」比重越高，帳面預估獲利越好看，但也代表本金因為賭錯而變少的機會越大。",
    { fill: LIGHT_TINT, bodySize: 11 });

  card(s, 0.6, 5.1, PW - 1.2, 1.6, "怎麼選？",
    "如果這筆錢是「不能有本金損失」的閒錢，建議從方案A開始；如果可以承受「部分金額因賭錯而暫時變少」，再考慮拉高④⑤的比重。三個方案僅為示範權重，實際比重應由財務部與風控委員會依風險承受度共同核定。",
    { fill: LIGHT_TINT2, bodySize: 12 });
  footer(s, "10 / 12");
}

/* ============ SLIDE 10: IMPORTANT REMINDERS ============ */
{
  const s = newSlide();
  sectionTitle(s, "幾個重要提醒", "白話版風險與安全措施說明");

  const rows = [
    ["換匯風險", "NT$500萬要先換成美元／美元穩定幣才能投入這些平台，等到要換回台幣時，如果匯率有變動，換回來的台幣金額可能比預期多或少。"],
    ["平台本身的風險", "錢是放在 Bitfinex／OKX／Binance 這些交易所上，如果平台發生資安事件或經營出問題，仍有本金拿不回來的可能——這是所有方法都共同存在的風險，因此不會把所有錢都放在同一家平台。"],
    ["帳號安全機制", "只開放「借出、申購」的權限，把「提領、轉帳」的功能直接關閉，就算帳號密碼外洩，錢也無法被轉走。"],
    ["先小額試做，再放大金額", "建議先用一小部分金額實際操作 2–3 個月，確認一切運作順利、數字對得起來，再考慮是否放大到完整的 NT$500 萬。"],
  ];
  let y = 1.75;
  rows.forEach((r) => {
    circleLabel(s, 0.6, y, 0.5, "•", { fill: LIGHT_TINT, fontSize: 20 });
    s.addText(r[0], { x: 1.35, y: y - 0.02, w: 2.6, h: 0.9, fontFace: FONT, bold: true, fontSize: 13, color: NAVY, isTextBox: true, margin: 0, valign: "middle" });
    s.addText(r[1], { x: 4.15, y: y - 0.02, w: 8.55, h: 0.9, fontFace: FONT, fontSize: 11.5, color: SLATE, isTextBox: true, margin: 0, valign: "middle", lineSpacingMultiple: 1.2 });
    y += 1.05;
  });
  footer(s, "11 / 12");
}

/* ============ SLIDE 11: NEXT STEPS ============ */
{
  const s = newSlide();
  sectionTitle(s, "下一步", "簡化版三步驟");

  const phases = [
    ["第一步", "把權限設定好、內部簽核", "2–4 週"],
    ["第二步", "先小額試做 2–3 個月，看實際數字", "2–3 個月"],
    ["第三步", "數字沒問題，再放大到完整額度", "試做結束後 1 個月內決定"],
  ];
  let px = 0.6;
  const phaseW = 3.8, phaseGap = 0.35;
  phases.forEach((p, i) => {
    s.addShape("roundRect", { x: px, y: 1.9, w: phaseW, h: 2.6, rectRadius: 0.1, fill: { color: LIGHT_TINT2 }, line: { color: BORDER, width: 0.75 } });
    circleLabel(s, px + 0.25, 2.15, 0.55, String(i + 1), { fill: WHITE, fontSize: 20 });
    s.addText(p[0], { x: px + 0.25, y: 2.85, w: phaseW - 0.5, h: 0.4, fontFace: FONT, bold: true, fontSize: 15, color: ACCENT, isTextBox: true, margin: 0 });
    s.addText(p[1], { x: px + 0.25, y: 3.3, w: phaseW - 0.5, h: 0.9, fontFace: FONT, fontSize: 12, color: NAVY, isTextBox: true, margin: 0, lineSpacingMultiple: 1.25 });
    s.addText(p[2], { x: px + 0.25, y: 4.15, w: phaseW - 0.5, h: 0.3, fontFace: FONT, fontSize: 10, color: MUTED, isTextBox: true, margin: 0 });
    if (i < phases.length - 1) {
      s.addText("→", { x: px + phaseW, y: 2.9, w: phaseGap, h: 0.6, fontFace: FONT, fontSize: 20, color: MUTED, align: "center", isTextBox: true, margin: 0 });
    }
    px += phaseW + phaseGap;
  });

  s.addShape("line", { x: 0.6, y: 4.9, w: PW - 1.2, h: 0, line: { color: BORDER, width: 0.75 } });
  s.addText("想確認的事", { x: 0.6, y: 5.1, w: 4, h: 0.4, fontFace: FONT, bold: true, fontSize: 16, color: NAVY, isTextBox: true, margin: 0 });
  s.addText(
    "這 NT$500 萬額度是否核准？想從哪個方案（A／B／C）開始試做？對「雙幣理財」的比重是否有上限要求？",
    { x: 0.6, y: 5.55, w: PW - 1.2, h: 0.7, fontFace: FONT, fontSize: 13.5, color: SLATE, isTextBox: true, margin: 0, lineSpacingMultiple: 1.3 }
  );
  footer(s, "12 / 12");
}

pres.writeFile({ fileName: process.argv[2] || "output.pptx" }).then((fileName) => {
  console.log("Written:", fileName);
});
