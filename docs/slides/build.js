// 项目概览 PPT 生成脚本（pptxgenjs）。用法：node docs/slides/build.js [输出路径]
// 截图来自计划 0018 阶段 B 验收截图（裁剪后放在 img/），数字来自 README、决策 D16–D21 与 0017 策略比较报告。
const path = require("path");
const pptxgen = require("pptxgenjs");

const OUT = process.argv[2] || path.join(__dirname, "agriscout-overview.pptx");
const IMG = (f) => path.join(__dirname, "img", f);
const FONT = "Microsoft YaHei";

// 颜色取自 frontend/src/styles/tokens.css
const K = {
  ink: "1A221E", sub: "4A554F", muted: "66726B", line: "D2D9D5", bg2: "F6F8F7", bg3: "EEF2F0",
  brand: "15803D", brandDark: "0E4F26", brandDeep: "0A381B", brandSoft: "E8F2EC", brandMid: "8AC09E",
  healthy: "3A9B6C", early: "E9A823", earlyInk: "8A5A00", earlySoft: "FDF3DC",
  sympt: "A8231C", symptSoft: "FBE7E5", unknown: "DFE4E1",
  warn: "B45309", warnSoft: "F8EEE6",
  confirm: "5B21B6", confirmSoft: "EFE9FB", reshoot: "1D4ED8", reshootSoft: "E8EFFD",
  coverage: "0369A1", coverageSoft: "E5F6FE", random: "4B5563", randomSoft: "EEF0F3",
};

const pres = new pptxgen();
pres.layout = "LAYOUT_16x9"; // 10 × 5.625 in
pres.title = "巡知 AgriScout 项目概览";
pres.author = "AgriScout 团队";
pres.theme = { headFontFace: FONT, bodyFontFace: FONT };

const W = 10, H = 5.625, MX = 0.5;

pres.defineSlideMaster({
  title: "DARK",
  background: { color: K.brandDeep },
});
pres.defineSlideMaster({
  title: "CONTENT",
  background: { color: "FFFFFF" },
  objects: [
    { text: { text: "巡知 AgriScout", options: { x: MX, y: H - 0.38, w: 3, h: 0.25, fontFace: FONT, fontSize: 9, color: K.muted, margin: 0 } } },
  ],
  slideNumber: { x: W - 0.9, y: H - 0.38, w: 0.4, h: 0.25, fontFace: FONT, fontSize: 9, color: K.muted, align: "right" },
});

const T = (slide, text, o) => slide.addText(text, { isTextBox: true, fontFace: FONT, margin: 0, valign: "top", color: K.ink, ...o });

function content(section, title, kicker) {
  const s = pres.addSlide({ masterName: "CONTENT", sectionTitle: section });
  if (kicker) T(s, kicker, { x: MX, y: 0.3, w: 9, h: 0.25, fontSize: 11, color: K.brand, bold: true });
  T(s, title, { x: MX, y: 0.55, w: 9, h: 0.5, fontSize: 24, bold: true, valign: "middle" });
  return s;
}

// 主题图形：「垄 × 株」状态方块（与前端 PlantGrid 同色）
function cell(s, x, y, size, color, shape) {
  s.addShape(pres.shapes.RECTANGLE, { x, y, w: size, h: size, fill: { color }, line: { color: "FFFFFF", width: 0.75 } });
  const m = size * 0.3;
  if (shape === "tri") s.addShape(pres.shapes.ISOSCELES_TRIANGLE, { x: x + m, y: y + m, w: size - 2 * m, h: size - 2 * m, fill: { color: "6B4500" }, line: { type: "none" } });
  if (shape === "sq") s.addShape(pres.shapes.RECTANGLE, { x: x + m, y: y + m, w: size - 2 * m, h: size - 2 * m, fill: { color: "FFFFFF" }, line: { type: "none" } });
}

function chip(s, x, y, w, text, fg, bg, fs = 11) {
  s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x, y, w, h: 0.3, rectRadius: 0.06, fill: { color: bg }, line: { color: bg } });
  T(s, text, { x, y, w, h: 0.3, fontSize: fs, color: fg, bold: true, align: "center", valign: "middle" });
}

function card(s, x, y, w, h, fill = K.bg2) {
  s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x, y, w, h, rectRadius: 0.08, fill: { color: fill }, line: { color: K.line, width: 0.75 } });
}

function shot(s, file, x, y, w, h, caption) {
  s.addImage({ path: IMG(file), x, y, w, h, altText: caption || file });
  s.addShape(pres.shapes.RECTANGLE, { x, y, w, h, fill: { type: "none" }, line: { color: K.line, width: 0.75 } });
  if (caption) T(s, caption, { x, y: y + h + 0.06, w, h: 0.25, fontSize: 10, color: K.muted });
}

function bullets(s, items, o) {
  s.addText(items.map((it, i) => ({
    text: it, options: { bullet: { indent: 12 }, breakLine: i < items.length - 1, paraSpaceAfter: 7 },
  })), { isTextBox: true, fontFace: FONT, fontSize: 13, color: K.ink, valign: "top", margin: 0, ...o });
}

// ---------- 1 封面 ----------
pres.addSection({ title: "开篇" });
{
  const s = pres.addSlide({ masterName: "DARK", sectionTitle: "开篇" });
  T(s, "2027 第二十届「挑战杯」· 科技发明制作 A 类", { x: MX, y: 0.7, w: 6, h: 0.3, fontSize: 12, color: K.brandMid, bold: true });
  T(s, "巡知 AgriScout", { x: MX, y: 1.25, w: 6, h: 0.8, fontSize: 40, bold: true, color: "FFFFFF", valign: "middle" });
  T(s, "设施大棚黄瓜霜霉病的\n风险驱动闭环主动采集", { x: MX, y: 2.2, w: 5.6, h: 1.0, fontSize: 22, color: "FFFFFF", valign: "top" });
  T(s, "小车低位拍叶背 · 每株每天对齐 · 环境与状态决定补拍和人工确认", { x: MX, y: 3.45, w: 5.6, h: 0.3, fontSize: 12, color: K.brandMid });
  T(s, "项目概览 · 2026-10", { x: MX, y: 4.75, w: 4, h: 0.3, fontSize: 11, color: K.brandMid });
  // 右侧：一小块「垄 × 株」状态网格
  const pattern = [
    "hhhhehhhhh", "hhhhhhehhh", "hhehhshhhh", "hhhhhhhhuh", "hhhhehhhhh", "hhhhhhhheh",
  ];
  const sz = 0.33, gx = 6.15, gy = 1.05;
  pattern.forEach((row, r) => [...row].forEach((ch, c) => {
    const map = { h: [K.healthy], e: [K.early, "tri"], s: [K.sympt, "sq"], u: [K.unknown] };
    cell(s, gx + c * sz, gy + r * sz, sz, ...map[ch]);
  }));
  T(s, "● 健康  ▲ 早期  ■ 明显  ○ 不明", { x: gx, y: gy + 6 * sz + 0.12, w: 3.3, h: 0.25, fontSize: 10, color: K.brandMid });
  s.addNotes("开场：巡知是一套面向设施大棚的病害主动巡检系统。第一版只做黄瓜霜霉病。右边的小网格就是系统里每株一个格子的状态图，后面会反复出现。");
}

// ---------- 2 问题 ----------
pres.addSection({ title: "问题与创新" });
{
  const s = content("问题与创新", "霜霉病早期征兆难看到、难跟踪、难定位", "要解决的问题");
  const items = [
    ["在叶背", "早期征兆和确诊特征集中在下部叶片的叶背，正面俯拍看不到"],
    ["在清晨", "部分征兆只在清晨高湿时明显，白天巡棚容易错过"],
    ["靠翻叶", "人工要逐株翻叶，做不到每天每株都看"],
    ["不到株", "环境预警只能说「今天风险高」，定位不到具体植株"],
  ];
  const cw = 4.35, ch = 1.25;
  items.forEach(([k, v], i) => {
    const x = MX + (i % 2) * (cw + 0.3), y = 1.35 + Math.floor(i / 2) * (ch + 0.25);
    card(s, x, y, cw, ch);
    s.addShape(pres.shapes.OVAL, { x: x + 0.25, y: y + 0.3, w: 0.65, h: 0.65, fill: { color: K.brandSoft }, line: { color: K.brandSoft } });
    T(s, String(i + 1), { x: x + 0.25, y: y + 0.3, w: 0.65, h: 0.65, fontSize: 20, bold: true, color: K.brand, align: "center", valign: "middle" });
    T(s, k, { x: x + 1.1, y: y + 0.22, w: cw - 1.3, h: 0.35, fontSize: 16, bold: true });
    T(s, v, { x: x + 1.1, y: y + 0.6, w: cw - 1.3, h: 0.55, fontSize: 12, color: K.sub });
  });
  T(s, "场景：日光温室、塑料大棚；适宜发病约 15–25℃、相对湿度 85% 以上，夜间结露加重病情。散户大棚多半没电没网、过道窄。", {
    x: MX, y: 4.45, w: 9, h: 0.5, fontSize: 11, color: K.muted,
  });
  s.addNotes("问题来自计划 0013 背景节。重点是前两条：看叶背、看清晨，这两点决定了采集方式；后两条说明为什么需要按株分配人工。");
}

// ---------- 3 先例 ----------
{
  const s = content("问题与创新", "单项技术都有先例，我们的创新在于把它们闭环", "已有先例（决策 D16）");
  const hdr = { bold: true, color: "FFFFFF", fill: { color: K.brandDark }, fontSize: 12 };
  const rows = [
    [{ text: "先例", options: hdr }, { text: "做了什么", options: hdr }, { text: "对我们的含义", options: hdr }],
    ["CN221048423U 温室黄瓜叶部病害巡检机器人", "巡检机器人 + 识别", "「小车 + 识别」不能当创新点"],
    ["US11483471B2（Viewnetic）", "补光仰拍叶背", "「仰拍叶背」本身不能当创新点"],
    ["Frontiers in Plant Science，2026（农大 / 北大）", "环境引导的三阶段早期检测", "引用其「健康 / 早期 / 明显」标注口径"],
  ];
  s.addTable(rows, {
    x: MX, y: 1.3, w: 9, colW: [3.6, 2.5, 2.9], fontFace: FONT, fontSize: 12, color: K.ink,
    border: { type: "solid", pt: 0.75, color: K.line }, rowH: 0.45, valign: "middle", margin: [0, 0.1, 0, 0.1],
  });
  card(s, MX, 3.5, 9, 1.15, K.brandSoft);
  T(s, "总创新：风险驱动的闭环主动采集", { x: MX + 0.3, y: 3.65, w: 8.4, h: 0.35, fontSize: 16, bold: true, color: K.brandDark });
  T(s, "怎么拍、拍哪株、什么时候拍、推谁给人确认，由每株的风险和拍摄质量实时决定；早期确认是闭环的产出，不单列为创新点。", {
    x: MX + 0.3, y: 4.05, w: 8.4, h: 0.5, fontSize: 12, color: K.sub,
  });
  s.addNotes("答辩时评委很可能问「和那个专利有什么不同」。我们的回答是：单项都有先例，创新在于把质量反馈、同株追踪和风险分配串成闭环。");
}

// ---------- 4 三个创新点 ----------
{
  const s = content("问题与创新", "三个创新点按依赖顺序递进", "看不到 → 认不出 → 何时看、看哪里");
  const cols = [
    ["一", "看不到", "带质量反馈的叶背主动采集", "停车后低位按预设仰角拍叶背并补光，逐张判断质量，不合格就补拍", "普通 RGB 相机 + 树莓派 + 云台，不用高光谱，不改造大棚"],
    ["二", "认不出", "同株时序追踪", "用编码器加吊线或立柱上的标签，把每天的图像对齐到同一株，给出每株状态和把握程度", "不用轨道，不用 RTK"],
    ["三", "何时看、看哪里", "环境风险驱动的采集与确认分配", "根据温湿度、结露和每株状态，决定巡检时机、补拍哪些株、把哪些株推给人确认", "人只需确认被推送的植株"],
  ];
  const cw = 2.8, gap = 0.3, y0 = 1.3, chh = 3.35;
  cols.forEach(([n, q, name, how, cost], i) => {
    const x = MX + i * (cw + gap);
    card(s, x, y0, cw, chh, "FFFFFF");
    s.addShape(pres.shapes.OVAL, { x: x + 0.2, y: y0 + 0.2, w: 0.5, h: 0.5, fill: { color: K.brand }, line: { color: K.brand } });
    T(s, n, { x: x + 0.2, y: y0 + 0.2, w: 0.5, h: 0.5, fontSize: 16, bold: true, color: "FFFFFF", align: "center", valign: "middle" });
    T(s, q, { x: x + 0.85, y: y0 + 0.25, w: cw - 1, h: 0.4, fontSize: 13, color: K.brand, bold: true, valign: "middle" });
    T(s, name, { x: x + 0.2, y: y0 + 0.85, w: cw - 0.4, h: 0.65, fontSize: 15, bold: true });
    T(s, how, { x: x + 0.2, y: y0 + 1.5, w: cw - 0.4, h: 1.0, fontSize: 11, color: K.sub });
    s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x: x + 0.15, y: y0 + 2.5, w: cw - 0.3, h: 0.7, rectRadius: 0.06, fill: { color: K.brandSoft }, line: { color: K.brandSoft } });
    T(s, "降低的成本：" + cost, { x: x + 0.25, y: y0 + 2.53, w: cw - 0.5, h: 0.64, fontSize: 10, color: K.brandDark, valign: "middle" });
    if (i < 2) T(s, "→", { x: x + cw, y: y0 + 0.2, w: gap, h: 0.5, fontSize: 16, color: K.muted, align: "center", valign: "middle" });
  });
  s.addNotes("三个创新点有依赖顺序：先要拍到叶背，才谈得上同株对比；有了每株状态，才能按风险分配补拍和人工。每一点都写明它降低了什么成本，这是组员讨论后定的讲法。");
}

// ---------- 5 闭环 ----------
pres.addSection({ title: "系统" });
{
  const s = content("系统", "每天一圈：计划、采集、归档、评估、确认", "闭环怎么转");
  const nodes = [
    ["每日巡检计划", "planner-v0 给出四张名单"],
    ["停车拍叶背", "低位仰拍 + 补光"],
    ["车上判断质量", "iq-rule-v1，不合格补拍"],
    ["按株号归档", "分步上传，断网续传"],
    ["评估每株状态", "模型分 + dm-env-v0 环境指数"],
    ["推给人确认", "手机上看叶背选结论"],
  ];
  const nw = 1.38, gap = 0.144, y = 1.55, nh = 1.2;
  nodes.forEach(([a, b], i) => {
    const x = MX + i * (nw + gap);
    const hl = i === 0 || i === 5;
    card(s, x, y, nw, nh, hl ? K.brandSoft : K.bg2);
    T(s, String(i + 1), { x: x + 0.12, y: y + 0.1, w: 0.4, h: 0.3, fontSize: 12, bold: true, color: K.brand });
    T(s, a, { x: x + 0.12, y: y + 0.38, w: nw - 0.2, h: 0.35, fontSize: 12, bold: true });
    T(s, b, { x: x + 0.12, y: y + 0.72, w: nw - 0.2, h: 0.42, fontSize: 9.5, color: K.sub });
    if (i < 5) s.addShape(pres.shapes.LINE, { x: x + nw + 0.01, y: y + nh / 2, w: gap - 0.02, h: 0, line: { color: K.muted, width: 1.25, endArrowType: "triangle" } });
  });
  // 回环
  const yl = y + nh + 0.3, xr = MX + 5 * (nw + gap) + nw / 2, xl = MX + nw / 2;
  s.addShape(pres.shapes.LINE, { x: xr, y: y + nh, w: 0, h: 0.3, line: { color: K.brand, width: 1.5 } });
  s.addShape(pres.shapes.LINE, { x: xl, y: yl, w: xr - xl, h: 0, line: { color: K.brand, width: 1.5 } });
  s.addShape(pres.shapes.LINE, { x: xl, y: y + nh, w: 0, h: 0.3, flipV: true, line: { color: K.brand, width: 1.5, endArrowType: "triangle" } });
  T(s, "人工结论优先进入每株状态，决定次日计划", { x: 3, y: yl + 0.05, w: 4, h: 0.3, fontSize: 11, color: K.brand, align: "center", bold: true });
  card(s, MX, 3.75, 9, 0.75, K.warnSoft);
  T(s, "风险不用来减少巡检：只用来分配补拍时间和人工确认时间；始终保留低频全覆盖和随机抽查，避免漏掉模型没注意到的新病灶。", {
    x: MX + 0.25, y: 3.75, w: 8.5, h: 0.75, fontSize: 12, color: K.warn, valign: "middle",
  });
  s.addNotes("这是整个系统的主线。注意下方这条原则：风险高的株多拍、多看，但不会因为某株风险低就不去看它，这是为了防止模型盲区。");
}

// ---------- 6 创新一 ----------
{
  const s = content("系统", "创新一：拍不清就当场补拍，每次尝试都留证据", "带质量反馈的叶背主动采集");
  bullets(s, [
    "停车后按视角序列拍：叶背低位仰拍并补光，正面另拍",
    "车上逐张做图像质量判断 iq-rule-v1：清晰度、亮度、过曝 / 欠曝、逆光",
    "不合格当场补拍；每次尝试都上传，记录第几次拍、是否合格、质量明细",
    "散户大棚多半没网：判断在车上算，照片逐点落盘，断网续传",
    "补拍记录也是将来训练「叶背是否露出」判别的数据",
  ], { x: MX, y: 1.3, w: 3.9, h: 3.4 });
  shot(s, "replay.jpg", 4.9, 1.25, 4.6, 4.6 * 900 / 1224, null);
  T(s, "巡检回放：R02-P003 叶背第 1 次模糊不合格，第 2 次合格（模拟器合成叶片图）", { x: 4.9, y: 4.7, w: 4.6, h: 0.25, fontSize: 10, color: K.muted });
  s.addNotes("截图里的叶片是模拟器合成图，不是实拍。质量阈值是经验初值，等试拍照片校准。");
}

// ---------- 7 创新二 ----------
{
  const s = content("系统", "创新二：每天的照片对齐到同一株", "同株时序追踪");
  bullets(s, [
    "每株一个株号，如 R03-P017（第 3 垄第 17 株）",
    "标签内容就是株号（默认二维码），配合编码器定位",
    "上传时按株号自动关联；找不到就建档，待人核对",
    "单株时间线：每天正面、叶背分栏，灰显不合格，标出补拍",
    "每株状态：人工结论优先；只有模型分时仅作占位，不是诊断",
  ], { x: MX, y: 1.3, w: 3.9, h: 3.4 });
  const iw = 4.85, ih = iw * 774 / 1224;
  shot(s, "timeline.jpg", 4.65, 1.25, iw, ih, "单株时间线：同一株按天排列，绿框是人工确认挂上的那张");
  s.addNotes("不用轨道、不用 RTK，就能把每天的图对到同一株。株号格式和标签方式是 0014、0016-B 定的，标签贴在哪里等试拍再定。");
}

// ---------- 8 创新三 ----------
{
  const s = content("系统", "创新三：环境和每株状态决定补拍谁、推谁给人", "环境风险驱动的采集与确认分配");
  T(s, "棚内环境指数（dm-env-v0）", { x: MX, y: 1.25, w: 4.2, h: 0.3, fontSize: 13, bold: true });
  bullets(s, [
    "近 72 小时适宜、湿润小时数 → 指数 0–1",
    "读数不足时为空，不当作低风险",
    "前夜湿润 ≥4 小时，给出次日清晨叶背窗口",
  ], { x: MX, y: 1.6, w: 4.2, h: 1.1, fontSize: 11.5 });
  T(s, "每天四张互斥名单（planner-v0）", { x: MX, y: 2.75, w: 4.2, h: 0.3, fontSize: 13, bold: true });
  const lists = [
    ["推给人确认", "受人工预算限制，默认每天 5 株", K.confirm, K.confirmSoft],
    ["叶背补拍", "预算随环境指数在 10%–25% 间变化", K.reshoot, K.reshootSoft],
    ["低频全覆盖", "7 天没看到的株，不限预算", K.coverage, K.coverageSoft],
    ["随机抽查", "每天固定种子抽 5%，至少 1 株", K.random, K.randomSoft],
  ];
  lists.forEach(([n, d, fg, bg], i) => {
    const y = 3.12 + i * 0.4;
    chip(s, MX, y, 1.2, n, fg, bg, 10.5);
    T(s, d, { x: MX + 1.3, y, w: 2.9, h: 0.3, fontSize: 11, color: K.sub, valign: "middle" });
  });
  const iw = 4.6, ih = iw * 734 / 1224;
  shot(s, "plan.jpg", 4.9, 1.25, iw, ih, "巡检计划页：每条任务带打分分量，便于审计");
  T(s, "公式与参数是启发式，不是训练出的模型；参数待试拍校准、阈值待农技复核。", { x: 4.9, y: 4.4, w: iw, h: 0.45, fontSize: 10.5, color: K.warn });
  s.addNotes("这里要如实讲：planner-v0 是启发式规则，不是训练出来的模型。大棚没有训练好的风险模型，小麦的 risk-lr-v1 不能用在大棚。");
}

// ---------- 9 人工确认 ----------
{
  const s = content("系统", "人在棚里拿手机确认，结论直接关掉任务", "人工确认");
  const ph = 3.75, pw = ph * 750 / 1624;
  shot(s, "phone-confirm.jpg", MX + 0.2, 1.2, pw, ph, null);
  T(s, "手机宽度 375 px 可用", { x: MX, y: 1.2 + ph + 0.06, w: pw + 0.4, h: 0.25, fontSize: 10, color: K.muted, align: "center" });
  const steps = [
    ["待确认列表", "模型推给人的株按分数排序，按株合并任务"],
    ["看叶背大图", "侧滑面板看要确认的叶背和近 30 天照片"],
    ["选一个结论", "健康 / 早期 / 明显 / 其他，结论挂在最近一张合格叶背上"],
    ["自动跳下一株", "提交后关闭该株的确认任务；只读账号只能翻看"],
  ];
  const x0 = 3.4;
  steps.forEach(([a, b], i) => {
    const y = 1.3 + i * 0.85;
    s.addShape(pres.shapes.OVAL, { x: x0, y, w: 0.5, h: 0.5, fill: { color: K.brandSoft }, line: { color: K.brandSoft } });
    T(s, String(i + 1), { x: x0, y, w: 0.5, h: 0.5, fontSize: 15, bold: true, color: K.brand, align: "center", valign: "middle" });
    T(s, a, { x: x0 + 0.7, y: y - 0.02, w: 5.3, h: 0.3, fontSize: 14, bold: true });
    T(s, b, { x: x0 + 0.7, y: y + 0.3, w: 5.3, h: 0.3, fontSize: 11.5, color: K.sub });
  });
  T(s, "标注口径沿用「健康 / 早期 / 明显」三阶段（引用，不是创新点）", { x: x0, y: 4.75, w: 6, h: 0.25, fontSize: 10, color: K.muted });
  s.addNotes("人的时间是最贵的，所以确认流程做成一株一屏、提交就跳下一株。人工结论会覆盖模型分，成为这株的当前状态。");
}

// ---------- 10 平台 ----------
{
  const s = content("系统", "平台：一屏看清每个大棚、每一株", "工作台与展示屏");
  const iw = 6.4, ih = iw * 900 / 1600;
  shot(s, "screen.jpg", MX, 1.2, iw, ih, "展示屏：「垄 × 株」状态网格、棚内温湿度、今日计划和等人确认");
  const x = MX + iw + 0.3, w = 9 - iw - 0.3;
  const stats = [["0.2 秒", "3000 株状态网格首屏渲染（中位）"], ["4 + 4", "株状态四色、任务类型四色，均另配形状或线型"], ["3 种", "管理员 / 操作员 / 只读，全部接口需登录"]];
  stats.forEach(([n, d], i) => {
    const y = 1.2 + i * 1.2;
    T(s, n, { x, y, w, h: 0.55, fontSize: 26, bold: true, color: K.brand, valign: "middle" });
    T(s, d, { x, y: y + 0.55, w, h: 0.5, fontSize: 11, color: K.sub });
  });
  s.addNotes("颜色过了色盲模拟和灰度检查，状态不只靠颜色区分。展示屏适合比赛展台，鼠标悬停暂停轮播。");
}

// ---------- 11 模拟比较 ----------
pres.addSection({ title: "验证" });
{
  const s = content("验证", "同样的照片和人工预算，风险驱动确认出更多病株", "大棚模拟 · 巡检策略离线比较（0017）");
  card(s, MX, 1.15, 9, 0.42, K.warnSoft);
  T(s, "模拟结论只证明流程：病害规律与可见性参数是设计进模拟器的假设，下面的数字不能当作效果证据。", {
    x: MX + 0.2, y: 1.15, w: 8.6, h: 0.42, fontSize: 11.5, bold: true, color: K.warn, valign: "middle",
  });
  const labels = ["固定巡检", "固定·清晨拍", "固定·按模型分确认", "风险驱动"];
  s.addChart(pres.charts.BAR, [
    { name: "确认出的病株", labels, values: [5.9, 6.4, 11.45, 13.25] },
    { name: "其中明显期前确认", labels, values: [1.65, 2.25, 3.25, 6.1] },
  ], {
    x: MX, y: 1.7, w: 5.5, h: 3.15, barDir: "col", barGrouping: "clustered",
    chartColors: [K.brand, K.early], showValue: true, dataLabelPosition: "outEnd",
    dataLabelFontSize: 10, dataLabelFontFace: FONT, dataLabelColor: K.ink,
    catAxisLabelFontSize: 10, catAxisLabelFontFace: FONT, catAxisLabelColor: K.sub,
    valAxisLabelFontSize: 9, valAxisLabelColor: K.muted, valAxisLabelFontFace: FONT,
    valGridLine: { color: "E3E8E5", size: 0.5 }, catGridLine: { style: "none" },
    showLegend: true, legendPos: "t", legendFontSize: 10, legendFontFace: FONT,
    showTitle: true, title: "每季平均株数（发病 17.8 株）", titleFontSize: 11, titleFontFace: FONT, titleColor: K.ink,
  });
  const x = 6.3, w = 3.2;
  const stats = [
    ["137 → 22", "次/季 无效确认（确认为健康）"],
    ["2400 → 1592", "张/季 照片"],
    ["−0.25 天", "提前量均值仍在 0 附近"],
  ];
  stats.forEach(([n, d], i) => {
    const y = 1.75 + i * 0.85;
    T(s, n, { x, y, w, h: 0.45, fontSize: 22, bold: true, color: K.brandDark, valign: "middle" });
    T(s, d, { x, y: y + 0.43, w, h: 0.3, fontSize: 10.5, color: K.sub });
  });
  T(s, "日光温室 120 株 · 30 天 · 20 个种子 · 每天照片 ≤80 张、人工 ≤5 株。差别多半来自「按模型分派人确认」；塑料大棚趋势相同。", {
    x: 6.3, y: 4.25, w: 3.2, h: 0.75, fontSize: 9.5, color: K.muted,
  });
  s.addNotes("数字是 20 个种子的均值，来自 reports/0017。务必先讲上面那句：模拟只证明流程跑通。拆开看，照片不变只换派人方式就能确认出 11.45 株，说明大部分收益来自把人工花在高分株上；只把巡检挪到清晨几乎没变化。提前量均值仍接近 0，是要改进的地方。");
}

// ---------- 12 方法资产 ----------
{
  const s = content("验证", "方法已在小麦数据上验证，作为可复用资产保留", "小麦阶段的证据（D16 保留，不再扩展）");
  const stats = [
    ["0.82", "F1", "条锈病图块分类 rust-cls-v1", "NWRD 公开田间数据官方测试集；ROC-AUC 0.93"],
    ["100–120", "标注", "主动选样达到随机选样 200 个的效果", "NWRD 真实图块，候选池阳性 ≤10% 时；原始比例下无差别"],
    ["5", "个特征", "可训练风险模型 risk-lr-v1", "本区域图像、历史、邻近区域；训练与线上共用同一特征实现"],
  ];
  const cw = 2.8, gap = 0.3;
  stats.forEach(([n, u, a, b], i) => {
    const x = MX + i * (cw + gap), y = 1.35;
    card(s, x, y, cw, 2.6, "FFFFFF");
    s.addText([{ text: n, options: { fontSize: 32, bold: true, color: K.brand } }, { text: " " + u, options: { fontSize: 13, color: K.sub } }],
      { isTextBox: true, x: x + 0.2, y: y + 0.2, w: cw - 0.4, h: 0.75, fontFace: FONT, margin: 0, valign: "middle" });
    T(s, a, { x: x + 0.2, y: y + 1.0, w: cw - 0.4, h: 0.55, fontSize: 13, bold: true });
    T(s, b, { x: x + 0.2, y: y + 1.6, w: cw - 0.4, h: 0.85, fontSize: 10.5, color: K.sub });
  });
  T(s, "如实说明：抽稀阳性比例是看到原始结果后追加的对照，结论需在试验田数据上复验；risk-lr-v1 在小麦模拟季上训练，不用于大棚。", {
    x: MX, y: 4.2, w: 9, h: 0.55, fontSize: 11, color: K.muted,
  });
  s.addNotes("方向从小麦大田改到大棚之后，这些成果作为「方法可行」的证据保留：图块分类流程可复用到霜霉病，主动选样思路就是创新三里推人确认的基础。");
}

// ---------- 13 架构与工程 ----------
{
  const s = content("验证", "端—边—云分工，平台业务不依赖数据从哪来", "系统架构与工程纪律");
  const tiers = [
    ["采集端 · 小车", "树莓派 + USB 摄像头", ["云台、补光、编码器先有接口与假实现", "质量判断与补拍在车上", "逐点落盘、断网续传"]],
    ["场边主机", "Jetson TX2（选型待定）", ["推理服务 + 轻量平台", "现场不依赖公网", "手机、平板浏览器访问"]],
    ["平台", "FastAPI + Vue 3", ["上传快速返回，后台异步分析", "规则建议冻结快照，可追溯", "登录与三种角色权限"]],
  ];
  const cw = 2.7, gap = 0.45, y = 1.3, ch = 2.15;
  tiers.forEach(([a, b, list], i) => {
    const x = MX + i * (cw + gap);
    card(s, x, y, cw, ch, i === 2 ? K.brandSoft : K.bg2);
    T(s, a, { x: x + 0.2, y: y + 0.15, w: cw - 0.4, h: 0.35, fontSize: 14, bold: true });
    T(s, b, { x: x + 0.2, y: y + 0.5, w: cw - 0.4, h: 0.3, fontSize: 11, color: K.brand, bold: true });
    bullets(s, list, { x: x + 0.2, y: y + 0.9, w: cw - 0.35, h: 1.2, fontSize: 10.5 });
    if (i < 2) {
      s.addShape(pres.shapes.LINE, { x: x + cw + 0.05, y: y + ch / 2, w: gap - 0.1, h: 0, line: { color: K.muted, width: 1.25, endArrowType: "triangle" } });
      T(s, "HTTP", { x: x + cw, y: y + ch / 2 - 0.3, w: gap, h: 0.22, fontSize: 8, color: K.muted, align: "center" });
    }
  });
  T(s, "工程纪律（违反即返工）", { x: MX, y: 3.65, w: 4, h: 0.3, fontSize: 12, bold: true });
  const rules = ["协议即合同", "采集端只走 HTTP", "照片内容寻址", "规则单一事实源", "Agent 只读 / 只起草", "证据闸门", "测试全绿才提交"];
  const rw = (9 - 3 * 0.15) / 4;
  rules.forEach((r, i) => chip(s, MX + (i % 4) * (rw + 0.15), 4.05 + Math.floor(i / 4) * 0.42, rw, r, K.brandDark, K.bg3, 10.5));
  s.addNotes("模拟器、真车都通过同一份巡检包协议接入，平台代码不因数据源改变而修改。AI 只做解释层：诊断 Agent 只读，规则修订 Agent 只能起草、必须影子运行加人工审批。");
}

// ---------- 14 进度 ----------
pres.addSection({ title: "进度" });
{
  const s = content("进度", "软件闭环已打通，下一步是进棚试拍", "进度与下一步");
  const done = [
    ["0014", "按株建档、协议 v2、单株时间线"],
    ["0015", "棚内环境、每株状态、巡检计划"],
    ["0016-A/B", "车上质量判断补拍、分步上传、株号定位"],
    ["0017", "大棚模拟与巡检策略离线比较"],
    ["0018", "前端按大棚工作流重做"],
  ];
  const next = [
    ["0016-C", "小车离线执行巡检计划"],
    ["试拍", "河南塑料大棚：仰拍能否看清叶背、清晨窗口、补拍耗时、过道宽度"],
    ["WP5", "霜霉病识别基线：公开数据先训「霜霉病 / 健康」"],
    ["器件", "云台、编码器、标签、冠层温湿度记录仪选型"],
    ["申报书", "团队按新方向重写"],
  ];
  const col = (title, list, x, fg, bg, mark) => {
    T(s, title, { x, y: 1.25, w: 4.3, h: 0.3, fontSize: 14, bold: true, color: fg });
    list.forEach(([k, v], i) => {
      const y = 1.65 + i * 0.6;
      chip(s, x, y, 1.0, k, fg, bg, 10);
      T(s, v, { x: x + 1.12, y: y - 0.03, w: 3.25, h: 0.55, fontSize: 11, color: K.ink, valign: "top" });
    });
  };
  col("已完成（2026-10）", done, MX, K.brandDark, K.brandSoft);
  col("下一步", next, 5.2, K.warn, K.warnSoft);
  T(s, "时间约束：作品须在 2027-06-01 前完成；校赛约 2027 年 3 月；秋茬约 11 月结束，试拍窗口有限。", { x: MX, y: 4.75, w: 9, h: 0.3, fontSize: 10.5, color: K.muted });
  s.addNotes("硬件相关部分先写接口和假实现，器件定型后再接真驱动。试拍要尽早，秋茬结束后只剩日光温室可用。");
}

// ---------- 15 结尾 ----------
{
  const s = pres.addSlide({ masterName: "DARK", sectionTitle: "进度" });
  T(s, "把有限的巡检和人工，\n花在最可能出问题的那几株上", { x: MX, y: 0.9, w: 9, h: 1.3, fontSize: 28, bold: true, color: "FFFFFF" });
  T(s, "还需要田间回答的问题", { x: MX, y: 2.6, w: 6, h: 0.3, fontSize: 13, bold: true, color: K.brandMid });
  const qs = [
    "低位仰拍加补光，能否稳定拍清黄瓜下部叶背",
    "清晨高湿窗口是否真实存在、能否赶上",
    "planner-v0 的参数和环境阈值，用实测数据校准后效果如何",
    "与人工巡棚相比，同样人力能提前多少发现病株",
  ];
  s.addText(qs.map((q, i) => ({ text: q, options: { bullet: { indent: 12 }, breakLine: i < qs.length - 1, paraSpaceAfter: 6 } })),
    { isTextBox: true, x: MX, y: 3.0, w: 8.5, h: 1.6, fontFace: FONT, fontSize: 13, color: "FFFFFF", margin: 0, valign: "top" });
  T(s, "巡知 AgriScout · 谢谢", { x: MX, y: 4.95, w: 5, h: 0.3, fontSize: 11, color: K.brandMid });
  s.addNotes("结尾如实说清还没验证的部分，这也是评审看重的科学性。最后一条就是比赛规则里说的「可测量的效果」，需要田间对比实验回答。");
}

pres.writeFile({ fileName: OUT }).then(() => console.log("wrote", OUT));
