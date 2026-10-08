// 半决赛路演 PPT 生成脚本（pptxgenjs）。用法：node docs/slides/semifinal/build.js [输出路径]
// 叙事结构按《巡知项目思路与路演 PPT 规划》定稿：8 分钟、正文 16 页 + 备用 3 页。
// 背景：bg/ 下放「封面」「内容」「结尾」.jpg/.png 即替换占位图（缺哪张就用对应的「-占位.png」）。
// 截图复用 ../img/（计划 0018 验收截图裁剪）；数字来自 README、决策 D16–D22、reports/0017 与 main 上的测试结果。
const fs = require("fs");
const path = require("path");
const pptxgen = require("pptxgenjs");
const React = require("react");
const ReactDOMServer = require("react-dom/server");
const sharp = require("sharp");
const lu = require("react-icons/lu");

const OUT = process.argv[2] || path.join(__dirname, "巡知_半决赛路演.pptx");
const IMG = (f) => path.join(__dirname, "..", "img", f);
function bg(name) {
  for (const ext of [".jpg", ".jpeg", ".png"]) {
    const p = path.join(__dirname, "bg", name + ext);
    if (fs.existsSync(p)) return p;
  }
  return path.join(__dirname, "bg", name + "-占位.png");
}

const FONT = "Microsoft YaHei";
const K = {
  navy: "1B2F5B", blue: "2F6FB5", blueSoft: "E3EEFA", blueLine: "B9D2EE", pale: "F3F8FD",
  gold: "C08A1E", goldBright: "D9A520", goldSoft: "FBF3E0",
  ink: "1F2937", sub: "4B5563", muted: "6B7280", line: "DCE3EC", white: "FFFFFF",
  healthy: "3A9B6C", early: "E9A823", sympt: "A8231C", unknown: "DFE4E1",
  confirm: "5B21B6", confirmSoft: "EFE9FB", reshoot: "1D4ED8", reshootSoft: "E8EFFD",
  coverage: "0369A1", coverageSoft: "E5F6FE", random: "4B5563", randomSoft: "EEF0F3",
  okSoft: "E6F4EC", okInk: "1F6B47", wipSoft: "FDF3DC", wipInk: "8A5A00", todoSoft: "EEF0F3",
};
const W = 10, H = 5.625, MX = 0.55;

async function icon(name, color = K.blue, size = 256) {
  const svg = ReactDOMServer.renderToStaticMarkup(React.createElement(lu[name], { color: "#" + color, size: String(size) }));
  const buf = await sharp(Buffer.from(svg)).png().toBuffer();
  return "image/png;base64," + buf.toString("base64");
}

(async () => {
  const pres = new pptxgen();
  pres.layout = "LAYOUT_16x9";
  pres.title = "巡知 AgriScout 半决赛路演";
  pres.author = "AgriScout 团队";
  pres.theme = { headFontFace: FONT, bodyFontFace: FONT };

  pres.defineSlideMaster({ title: "COVER", background: { path: bg("封面") } });
  pres.defineSlideMaster({ title: "END", background: { path: bg("结尾") } });
  pres.defineSlideMaster({
    title: "CONTENT",
    background: { path: bg("内容") },
    objects: [
      { roundRect: { x: W - 2.05, y: 0.28, w: 1.55, h: 0.32, fill: { color: K.white }, line: { color: K.blueLine, width: 0.75 }, rectRadius: 0.16 } },
      { ellipse: { x: W - 1.93, y: 0.39, w: 0.1, h: 0.1, fill: { color: K.goldBright }, line: { color: K.goldBright } } },
      { text: { text: "巡知 AgriScout", options: { x: W - 1.78, y: 0.28, w: 1.25, h: 0.32, fontFace: FONT, fontSize: 9.5, bold: true, color: K.navy, valign: "middle", margin: 0 } } },
    ],
    slideNumber: { x: W - 0.95, y: H - 0.32, w: 0.45, h: 0.22, fontFace: FONT, fontSize: 9, color: K.muted, align: "right" },
  });

  const T = (s, text, o) => s.addText(text, { isTextBox: true, fontFace: FONT, margin: 0, valign: "top", color: K.ink, ...o });
  const card = (s, x, y, w, h, fill = K.white, line = K.line) =>
    s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x, y, w, h, rectRadius: 0.1, fill: { color: fill }, line: { color: line, width: 0.75 },
      shadow: { type: "outer", color: "9FB4CC", opacity: 0.18, blur: 6, offset: 1.5, angle: 90 } });
  const pill = (s, x, y, w, text, fg = K.white, bgc = K.blue, fs = 10.5, h = 0.3) => {
    s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x, y, w, h, rectRadius: h / 2, fill: { color: bgc }, line: { color: bgc } });
    T(s, text, { x, y, w, h, fontSize: fs, bold: true, color: fg, align: "center", valign: "middle" });
  };
  const ic = async (s, name, x, y, size, color = K.blue, circle = true) => {
    if (circle) s.addShape(pres.shapes.OVAL, { x, y, w: size, h: size, fill: { color: K.blueSoft }, line: { color: K.blueSoft } });
    const pad = circle ? size * 0.24 : 0;
    s.addImage({ data: await icon(name, color), x: x + pad, y: y + pad, w: size - 2 * pad, h: size - 2 * pad });
  };
  const arrow = (s, x, y, w, h, color = K.blue) =>
    s.addShape(pres.shapes.LINE, { x, y, w, h, line: { color, width: 1.5, endArrowType: "triangle" } });
  const shot = (s, file, x, y, w, h) => {
    s.addImage({ path: IMG(file), x, y, w, h, altText: file });
    s.addShape(pres.shapes.RECTANGLE, { x, y, w, h, fill: { type: "none" }, line: { color: K.line, width: 0.75 } });
  };
  const PARTS = { 问题: "01", 答案: "02", 证据: "03", 落地: "04", 备用: "附" };

  function content(part, title, quote) {
    const s = pres.addSlide({ masterName: "CONTENT", sectionTitle: part });
    T(s, PARTS[part], { x: MX, y: 0.26, w: 0.5, h: 0.36, fontSize: 20, bold: true, color: K.goldBright, valign: "middle" });
    pill(s, MX + 0.5, 0.3, 0.62, part, K.white, K.blue, 10, 0.28);
    T(s, title, { x: MX, y: 0.68, w: 8.9, h: 0.55, fontSize: 24, bold: true, color: K.navy, valign: "middle" });
    if (quote) {
      card(s, MX, 4.78, W - 2 * MX - 0.5, 0.46, K.white, K.line);
      T(s, "“", { x: MX + 0.14, y: 4.72, w: 0.4, h: 0.5, fontSize: 30, bold: true, color: K.goldBright, fontFace: "Georgia" });
      T(s, quote, { x: MX + 0.55, y: 4.78, w: W - 2 * MX - 1.2, h: 0.46, fontSize: 12.5, bold: true, color: K.navy, valign: "middle" });
    }
    return s;
  }
  function bullets(s, items, o) {
    s.addText(items.map((it, i) => ({ text: it, options: { bullet: { indent: 11 }, breakLine: i < items.length - 1, paraSpaceAfter: 5 } })),
      { isTextBox: true, fontFace: FONT, fontSize: 12, color: K.ink, valign: "top", margin: 0, ...o });
  }

  // ===== 1 封面 =====
  pres.addSection({ title: "开场" });
  {
    const s = pres.addSlide({ masterName: "COVER", sectionTitle: "开场" });
    pill(s, MX, 0.75, 3.3, "【待填：比赛名称】· 半决赛路演", K.navy, K.goldSoft, 11, 0.34);
    T(s, "巡知 AgriScout", { x: MX, y: 1.35, w: 6, h: 0.85, fontSize: 40, bold: true, color: K.navy, valign: "middle" });
    T(s, "设施大棚黄瓜霜霉病的风险驱动闭环主动采集", { x: MX, y: 2.25, w: 6.2, h: 0.45, fontSize: 19, bold: true, color: K.blue });
    const three = [["LuEye", "看得到叶背"], ["LuQrCode", "认得出每株"], ["LuSunrise", "知道何时看哪里"]];
    for (let i = 0; i < 3; i++) {
      const x = MX + i * 1.95;
      await ic(s, three[i][0], x, 3.0, 0.42);
      T(s, three[i][1], { x: x + 0.5, y: 3.0, w: 1.4, h: 0.42, fontSize: 12, bold: true, color: K.navy, valign: "middle" });
    }
    T(s, "团队：【待填】　指导教师：【待填】　学校：【待填】", { x: MX, y: 4.55, w: 6, h: 0.3, fontSize: 11, color: K.sub });
    s.addNotes("（约 15 秒）大家好，我们的项目叫巡知。一句话：在设施大棚里，让小车看得到叶背、认得出每一株，并且知道什么时候去看、先看哪几株。");
  }

  // ===== 2 问题：痛点 =====
  pres.addSection({ title: "问题" });
  {
    const s = content("问题", "棚里有风险，可病在哪几株的叶背上？", "环境预警只能说「今天风险高」，说不出是哪几株。");
    // 场景配图位
    s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x: MX, y: 1.4, w: 3.3, h: 3.2, rectRadius: 0.1, fill: { color: K.pale }, line: { color: K.blueLine, width: 1, dashType: "dash" } });
    await ic(s, "LuWarehouse", MX + 1.3, 2.3, 0.7, K.blue, false);
    T(s, "【待填：大棚翻叶看病的现场照片】", { x: MX + 0.2, y: 3.15, w: 2.9, h: 0.5, fontSize: 11, color: K.muted, align: "center" });
    const pains = [
      ["LuEyeOff", "看不到", "早期征兆在下部叶片的叶背，俯拍和固定摄像头拍不到"],
      ["LuSearch", "认不出", "每天的照片对不上同一株，看不出病斑在不在发展"],
      ["LuHand", "看不过来", "人工要逐株翻叶，做不到每天每株"],
      ["LuMapPinOff", "定位不到", "环境预警只知道棚里风险高，不知道是哪几株"],
    ];
    for (let i = 0; i < 4; i++) {
      const x = 4.15 + (i % 2) * 2.7, y = 1.4 + Math.floor(i / 2) * 1.65;
      card(s, x, y, 2.55, 1.5);
      await ic(s, pains[i][0], x + 0.18, y + 0.18, 0.5);
      T(s, pains[i][1], { x: x + 0.78, y: y + 0.2, w: 1.7, h: 0.45, fontSize: 15, bold: true, color: K.navy, valign: "middle" });
      T(s, pains[i][2], { x: x + 0.18, y: y + 0.78, w: 2.2, h: 0.65, fontSize: 10.5, color: K.sub });
    }
    s.addNotes("（约 45 秒，开场从种植户的场景讲起）黄瓜霜霉病在大棚里很常见。种植户要一株株翻开叶子看，棚一大就看不过来；装了温湿度预警，也只知道今天风险高，不知道该先看哪几株。我们把它归成四个痛点：看不到、认不出、看不过来、定位不到。");
  }

  // ===== 3 核心问题 =====
  {
    const s = content("问题", "核心问题：在病刚出现时，拍清那几株的叶背", "不改造大棚、不用高光谱，用普通相机把叶背拍清楚。");
    // 叶片剖面示意
    const lx = MX + 0.3, ly = 2.35;
    T(s, "俯拍：只看到正面", { x: lx + 0.1, y: 1.4, w: 2.4, h: 0.3, fontSize: 11, color: K.muted });
    await ic(s, "LuCamera", lx + 0.6, 1.72, 0.42, K.muted, false);
    s.addShape(pres.shapes.LINE, { x: lx + 0.81, y: 2.17, w: 0, h: 0.28, line: { color: K.muted, width: 1.25, dashType: "dash", endArrowType: "triangle" } });
    s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x: lx, y: ly + 0.15, w: 4.2, h: 0.28, rectRadius: 0.14, fill: { color: "4E9F5E" }, line: { color: "3D8A4C" } });
    T(s, "叶片正面：早期几乎看不出", { x: lx + 0.9, y: ly + 0.15, w: 3, h: 0.28, fontSize: 10, color: K.white, bold: true, valign: "middle" });
    s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x: lx, y: ly + 0.43, w: 4.2, h: 0.2, rectRadius: 0.1, fill: { color: "B7D8B5" }, line: { color: "9CC79A" } });
    [0.6, 1.3, 1.5, 2.4, 3.1, 3.3].forEach((dx) => s.addShape(pres.shapes.OVAL, { x: lx + dx, y: ly + 0.6, w: 0.22, h: 0.12, fill: { color: "8E7FA6" }, line: { color: "8E7FA6" } }));
    T(s, "叶背：早期征兆和确诊特征集中在这里", { x: lx + 0.2, y: ly + 0.82, w: 3.9, h: 0.3, fontSize: 11, bold: true, color: K.navy });
    await ic(s, "LuCamera", lx + 3.3, ly + 1.55, 0.42, K.blue, false);
    s.addShape(pres.shapes.LINE, { x: lx + 2.95, y: ly + 0.8, w: 0.4, h: 0.75, flipV: true, line: { color: K.blue, width: 1.5, endArrowType: "triangle" } });
    T(s, "低位仰拍 + 补光", { x: lx + 1.6, y: ly + 1.65, w: 1.6, h: 0.3, fontSize: 11, bold: true, color: K.blue, align: "right" });
    // 右侧：两个事实 + 约束
    const rx = 5.35;
    const facts = [
      ["LuLeaf", "在下部叶背", "早期征兆和确诊特征集中在下部叶片的叶背"],
      ["LuSunrise", "在清晨高湿时", "部分征兆只在清晨高湿时明显；夜间结露加重病情"],
    ];
    for (let i = 0; i < 2; i++) {
      const y = 1.4 + i * 1.05;
      card(s, rx, y, 4.1, 0.9);
      await ic(s, facts[i][0], rx + 0.15, y + 0.2, 0.5);
      T(s, facts[i][1], { x: rx + 0.8, y: y + 0.1, w: 3.2, h: 0.32, fontSize: 13.5, bold: true, color: K.navy, valign: "middle" });
      T(s, facts[i][2], { x: rx + 0.8, y: y + 0.45, w: 3.2, h: 0.4, fontSize: 10.5, color: K.sub });
    }
    T(s, "约束", { x: rx, y: 3.62, w: 1, h: 0.28, fontSize: 11, bold: true, color: K.gold });
    ["不改造大棚", "不用高光谱", "普通 RGB 相机"].forEach((t, i) => pill(s, rx + i * 1.38, 3.95, 1.28, t, K.navy, K.goldSoft, 10.5));
    s.addNotes("（约 45 秒）为什么难：霜霉病的早期征兆集中在下部叶片的叶背，而且部分征兆只在清晨高湿时明显。所以问题落到一句话：不改造大棚、不用昂贵设备，在病刚出现时把该看的那几株的叶背拍清楚、认准是哪一株，再交给人确认。");
  }

  // ===== 4 总创新 =====
  pres.addSection({ title: "答案" });
  {
    const s = content("答案", "总创新：风险驱动的闭环主动采集", "怎么拍，由风险和拍摄质量实时决定。");
    const cx = 3.45, cy = 2.95, nw = 1.8;
    s.addShape(pres.shapes.OVAL, { x: cx - 0.95, y: cy - 0.62, w: 1.9, h: 1.24, fill: { color: K.navy }, line: { color: K.navy } });
    T(s, "风险驱动的\n闭环主动采集", { x: cx - 0.95, y: cy - 0.62, w: 1.9, h: 1.24, fontSize: 12.5, bold: true, color: K.white, align: "center", valign: "middle" });
    const nodes = [
      { x: cx - 0.9, y: 1.3, n: "三", t: "何时看哪里", d: "按风险排名单" },
      { x: cx + 1.15, y: cy - 0.4, n: "一", t: "拍清叶背", d: "不合格当场补拍" },
      { x: cx - 0.9, y: 3.85, n: "二", t: "对齐同一株", d: "株号 + 编码器" },
      { x: cx - 2.95, y: cy - 0.4, n: "人", t: "人工确认", d: "只看被推送的株" },
    ];
    for (const nd of nodes) {
      card(s, nd.x, nd.y, nw, 0.8, nd.n === "人" ? K.goldSoft : K.white, nd.n === "人" ? "E8D2A0" : K.blueLine);
      s.addShape(pres.shapes.OVAL, { x: nd.x + 0.12, y: nd.y + 0.17, w: 0.46, h: 0.46, fill: { color: nd.n === "人" ? K.goldBright : K.blue }, line: { type: "none" } });
      T(s, nd.n, { x: nd.x + 0.12, y: nd.y + 0.17, w: 0.46, h: 0.46, fontSize: 13, bold: true, color: K.white, align: "center", valign: "middle" });
      T(s, nd.t, { x: nd.x + 0.66, y: nd.y + 0.1, w: 1.12, h: 0.32, fontSize: 12, bold: true, color: K.navy, valign: "middle" });
      T(s, nd.d, { x: nd.x + 0.66, y: nd.y + 0.43, w: 1.12, h: 0.3, fontSize: 9, color: K.sub, valign: "middle" });
    }
    // 顺时针箭头
    arrow(s, cx + 0.9, 1.75, 0.95, 0.78);
    arrow(s, cx + 2.05, cy + 0.42, -1.15, 0.83);
    arrow(s, cx - 0.9, 4.25, -1.15, -0.88);
    arrow(s, cx - 2.05, cy - 0.42, 1.15, -0.78);
    // 右侧：为什么按依赖递进
    const rx = 6.55;
    T(s, "三点按依赖递进", { x: rx, y: 1.35, w: 3.2, h: 0.35, fontSize: 14, bold: true, color: K.navy });
    bullets(s, [
      "拍不清叶背，就没有可对齐的图",
      "对不上同一株，就没有每株状态",
      "没有每株状态，风险就分配不到具体植株",
    ], { x: rx, y: 1.8, w: 2.9, h: 1.5, fontSize: 11.5 });
    card(s, rx, 3.35, 2.9, 1.15, K.pale, K.blueLine);
    T(s, "风险不减少巡检：只用来分配补拍和人工确认，低频全覆盖和随机抽查一直保留。", { x: rx + 0.15, y: 3.42, w: 2.6, h: 1.0, fontSize: 11, color: K.navy, valign: "middle" });
    s.addNotes("（约 40 秒）我们的总创新叫风险驱动的闭环主动采集。三项创新不是三个并列功能，而是一个圈：先决定拍谁，再把叶背拍清楚，再对齐到同一株，人确认后的结论又决定第二天拍谁。要强调：风险只用来分配补拍和人工，不会因为风险低就少巡。");
  }

  // ===== 5 系统架构 =====
  {
    const s = content("答案", "系统架构：车上管拍好，平台管拍谁，人只管确认", "车上判断拍得好不好，平台决定明天看哪株，人只确认被推送的株。");
    const layers = [
      ["应用层", "LuMonitorSmartphone", "工作台 · 手机待确认 · 展示屏 · 单株时间线", "人工确认"],
      ["决策层", "LuListChecks", "棚内环境指数 + 每株状态 → 每天四张巡检名单", "创新三"],
      ["数据层", "LuDatabase", "照片按株号归档 · 株档案 · 每天观测挂到同一株", "创新二"],
      ["采集层", "LuCamera", "小车：云台 + 补光 + 编码器 + 二维码 · 车上质量判断与补拍 · 断网续传", "创新一"],
    ];
    for (let i = 0; i < 4; i++) {
      const y = 1.4 + i * 0.83;
      card(s, MX, y, 7.4, 0.7, i === 0 ? K.pale : K.white, K.blueLine);
      pill(s, MX + 0.15, y + 0.2, 0.85, layers[i][0], K.white, K.navy, 10.5);
      await ic(s, layers[i][1], MX + 1.15, y + 0.13, 0.44);
      T(s, layers[i][2], { x: MX + 1.7, y: y + 0.05, w: 5.6, h: 0.6, fontSize: 11.5, color: K.ink, valign: "middle" });
      pill(s, MX + 7.6, y + 0.2, 1.15, layers[i][3], K.navy, K.goldSoft, 10.5);
      if (i < 3) s.addShape(pres.shapes.LINE, { x: MX + 8.17, y: y + 0.5, w: 0, h: 0.33, line: { color: K.gold, width: 1, dashType: "dash" } });
    }
    s.addNotes("（约 30 秒）四层：采集层是小车，负责把叶背拍好，对应创新一；数据层把每天的照片按株号归档，对应创新二；决策层根据环境和每株状态排出每天的名单，对应创新三；应用层把名单里的几株推到手机上给人确认。");
  }

  // ===== 6 创新一 =====
  {
    const s = content("答案", "创新一：带质量反馈的叶背主动采集", "停车低位仰拍叶背并补光，拍不好当场补拍；普通相机加云台就够。");
    // 仰角扇形示意
    const ox = MX + 0.5, oy = 3.85;
    s.addShape(pres.shapes.LINE, { x: MX, y: oy + 0.35, w: 3.9, h: 0, line: { color: K.line, width: 1 } });
    await ic(s, "LuCamera", ox - 0.25, oy - 0.05, 0.45, K.navy, false);
    const rays = [[0, "正面 0°"], [35, "叶背 35°"], [50, "叶背 50°"]];
    rays.forEach(([deg, label]) => {
      const L = 2.8, r = (deg * Math.PI) / 180, dx = L * Math.cos(r), dy = L * Math.sin(r);
      s.addShape(pres.shapes.LINE, { x: ox + 0.2, y: oy + 0.17 - dy, w: dx, h: dy, flipV: true, line: { color: deg ? K.blue : K.muted, width: 1.5, endArrowType: "triangle" } });
      T(s, label, { x: ox + 0.25 + dx + 0.05, y: oy + 0.05 - dy, w: 1, h: 0.25, fontSize: 10, bold: true, color: deg ? K.blue : K.muted });
    });
    T(s, "补光 · 相机离地约 0.2 m", { x: MX, y: 1.45, w: 3.5, h: 0.3, fontSize: 11, color: K.sub });
    T(s, "示例视角；待试拍校准", { x: MX, y: 4.33, w: 3.5, h: 0.25, fontSize: 9.5, color: K.muted });
    // 补拍流程
    const fx = 5.0;
    const steps = [["LuCamera", "停车拍一张"], ["LuScanLine", "车上判断：清晰度、过曝、过暗、逆光"], ["LuRefreshCw", "不合格：仰角 +5° 重拍，最多 3 次"], ["LuCloudUpload", "每次尝试都上传，留作质量证据"]];
    for (let i = 0; i < steps.length; i++) {
      const y = 1.4 + i * 0.78;
      card(s, fx, y, 4.45, 0.62);
      await ic(s, lu[steps[i][0]] ? steps[i][0] : "LuCircleCheck", fx + 0.12, y + 0.09, 0.44);
      T(s, steps[i][1], { x: fx + 0.7, y, w: 3.65, h: 0.62, fontSize: 12, color: K.ink, valign: "middle", bold: i === 2 });
      if (i < steps.length - 1) arrow(s, fx + 0.34, y + 0.62, 0, 0.16, K.blueLine);
    }
    s.addNotes("（约 40 秒）创新一解决看不到。小车在株前停下，低位仰拍叶背并补光。每张照片在车上就判断清晰度、曝光和逆光，不合格就把仰角加 5 度重拍，最多 3 次。散户大棚多半没网，所以判断放在车上算。成本上只用普通 RGB 相机、树莓派和云台，不用高光谱，也不改造大棚。阈值是经验初值，等试拍校准。");
  }

  // ===== 7 创新二 =====
  {
    const s = content("答案", "创新二：同株时序追踪", "编码器加吊线二维码，把每天的照片对齐到同一株；不用轨道、不用 RTK。");
    // 垄行俯视
    const gx = MX + 0.15, gy = 1.55, rowsN = 4, colsN = 7, dx = 0.5, dy = 0.62;
    for (let r = 0; r < rowsN; r++) {
      T(s, `${r + 1} 垄`, { x: gx - 0.05, y: gy + r * dy + 0.05, w: 0.45, h: 0.3, fontSize: 9.5, color: K.muted });
      for (let c = 0; c < colsN; c++) {
        const hit = r === 2 && c === 4;
        s.addShape(pres.shapes.OVAL, { x: gx + 0.45 + c * dx, y: gy + r * dy, w: 0.36, h: 0.36, fill: { color: hit ? K.early : "6DB57F" }, line: { color: hit ? K.gold : "4E9F5E", width: hit ? 2 : 0.75 } });
      }
      await ic(s, "LuQrCode", gx + 0.45 + colsN * dx + 0.02, gy + r * dy + 0.04, 0.28, K.navy, false);
    }
    pill(s, gx + 0.45 + 4 * dx - 0.35, gy + 3 * dy + 0.45, 1.1, "R03-P005", K.navy, K.goldSoft, 10);
    await ic(s, "LuBot", gx - 0.05, gy + 4 * dy + 0.1, 0.36, K.blue, false);
    arrow(s, gx + 0.35, gy + 4 * dy + 0.28, 2.6, 0, K.blue);
    T(s, "编码器测行内距离", { x: gx + 0.45, y: gy + 4 * dy + 0.32, w: 2.2, h: 0.25, fontSize: 9.5, color: K.blue });
    // 右侧截图 + 说明
    const iw = 3.9, ih = iw * 774 / 1224;
    shot(s, "timeline.jpg", 5.55, 1.38, iw, ih);
    bullets(s, [
      "每株一个株号，标签内容就是株号",
      "上传时按株号自动归档，找不到就建档待核对",
      "每株状态：人工结论优先，模型分只作占位",
    ], { x: 5.55, y: 1.38 + ih + 0.12, w: iw, h: 0.8, fontSize: 10.5 });
    s.addNotes("（约 40 秒）创新二解决认不出。每株有株号，比如第 3 垄第 5 株就是 R03-P005；吊线或立柱上的二维码告诉小车这是哪一株，编码器量行内距离。这样每天的照片都挂到同一株下面，右边就是单株时间线。不用轨道、不用 RTK。");
  }

  // ===== 8 创新三 =====
  {
    const s = content("答案", "创新三：环境风险驱动的采集与确认分配", "温湿度决定何时去，每株状态决定拍谁、推谁给人；风险不减少巡检。");
    card(s, MX, 1.4, 4.2, 3.2);
    await ic(s, "LuThermometer", MX + 0.18, 1.55, 0.46);
    T(s, "棚内环境指数（近 72 小时）", { x: MX + 0.75, y: 1.55, w: 3.3, h: 0.46, fontSize: 13, bold: true, color: K.navy, valign: "middle" });
    s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x: MX + 0.18, y: 2.15, w: 3.85, h: 0.5, rectRadius: 0.06, fill: { color: K.pale }, line: { color: K.blueLine } });
    T(s, "指数 = 1 − exp(−(适宜 + 湿润小时) / 24)", { x: MX + 0.18, y: 2.15, w: 3.85, h: 0.5, fontSize: 12, bold: true, color: K.navy, align: "center", valign: "middle" });
    bullets(s, [
      "适宜：15–25℃ 且相对湿度 ≥85%",
      "湿润：相对湿度 ≥95% 或露点差 ≤1℃",
      "前夜湿润 ≥4 小时 → 次日 05:30–08:30 清晨叶背窗口",
      "读数不足时为空，不当作低风险",
    ], { x: MX + 0.2, y: 2.8, w: 3.85, h: 1.7, fontSize: 10.5 });
    const lists = [
      ["推给人确认", "每天 5 株，按模型分排序", K.confirm, K.confirmSoft],
      ["叶背补拍", "预算随环境指数在 10%–25% 间变化", K.reshoot, K.reshootSoft],
      ["低频全覆盖", "7 天没看到的株，不限预算", K.coverage, K.coverageSoft],
      ["随机抽查", "每天抽 5%，至少 1 株", K.random, K.randomSoft],
    ];
    T(s, "每天四张互斥名单", { x: 5.0, y: 1.4, w: 4, h: 0.32, fontSize: 13, bold: true, color: K.navy });
    lists.forEach(([n, d, fg, bgc], i) => {
      const x = 5.0 + (i % 2) * 2.25, y = 1.82 + Math.floor(i / 2) * 1.05;
      card(s, x, y, 2.1, 0.92);
      pill(s, x + 0.14, y + 0.13, 1.2, n, fg, bgc, 10.5, 0.28);
      T(s, d, { x: x + 0.14, y: y + 0.47, w: 1.85, h: 0.4, fontSize: 10, color: K.sub });
    });
    T(s, "人判健康后若又拍到早期分数的新叶背，会重新推给人（planner-v1）。公式与参数是启发式，待试拍校准。", { x: 5.0, y: 3.98, w: 4.45, h: 0.6, fontSize: 10, color: K.gold });
    s.addNotes("（约 45 秒）创新三解决何时看、看哪里。近 72 小时的适宜和湿润小时算出环境指数；前一夜湿润 4 小时以上，就安排第二天清晨去拍叶背。每天给出四张名单：推给人确认、叶背补拍、全覆盖和随机抽查。如实说明：这是启发式规则，不是训练出来的模型，参数等试拍校准。");
  }

  // ===== 9 对比 =====
  {
    const s = content("答案", "和已有方案有何不同", "单项都有先例，我们用风险和拍摄质量把它们串成闭环。");
    const hdr = (t) => ({ text: t, options: { bold: true, color: K.white, fill: { color: K.navy }, fontSize: 12 } });
    const rows = [
      [hdr("已有方案"), hdr("做了什么"), hdr("巡知多做的一步")],
      ["温室黄瓜叶部病害巡检与识别机器人（CN221048423U）", "巡检机器人 + 识别", "拍完当场判断质量，不合格补拍"],
      ["Viewnetic（US11483471B2）", "补光仰拍叶背", "每天的叶背对齐到同一株，看病斑是否发展"],
      ["农大 / 北大，Frontiers 2026", "环境引导的三阶段早期检测", "环境和每株状态决定补拍谁、推谁给人"],
    ];
    s.addTable(rows, {
      x: MX, y: 1.45, w: 8.9, colW: [3.5, 2.3, 3.1], fontFace: FONT, fontSize: 11.5, color: K.ink, fill: { color: K.white },
      border: { type: "solid", pt: 0.75, color: K.line }, rowH: 0.62, valign: "middle", margin: [0, 0.12, 0, 0.12],
    });
    T(s, "「健康 / 早期 / 明显」三阶段标注口径引自 Frontiers 2026，不算我们的创新；早期确认是闭环的产出。", { x: MX, y: 4.1, w: 8.9, h: 0.5, fontSize: 10.5, color: K.muted });
    s.addNotes("（约 25 秒）评委一定会问和已有方案的区别。巡检识别机器人、补光仰拍叶背、环境引导的早期检测都有先例，单独哪一项都不能当创新点。我们的不同在于把它们按依赖接成闭环。");
  }

  // ===== 10 方法已验证 =====
  pres.addSection({ title: "证据" });
  {
    const s = content("证据", "方法已验证：识别与选样我们做过客观评估", "小麦阶段的成果证明方法做得出来，不用来说明大棚上的效果。");
    const stats = [
      ["0.82", "F1", "条锈病图块识别", "公开田间数据 NWRD 官方测试集；ROC-AUC 0.93"],
      ["40–50%", "标注量", "主动选样省下的标注", "病株稀少（阳性 ≤10%）时，100–120 个标注达到随机选 200 个的效果"],
      ["H1–H3", "离线重放", "上线前先比策略", "巡检策略、标注选样都能在同一份真值上离线比较"],
    ];
    for (let i = 0; i < 3; i++) {
      const x = MX + i * 3.0;
      card(s, x, 1.45, 2.8, 2.35);
      s.addText([{ text: stats[i][0], options: { fontSize: 30, bold: true, color: K.goldBright } }, { text: "  " + stats[i][1], options: { fontSize: 12, color: K.sub } }],
        { isTextBox: true, x: x + 0.2, y: 1.6, w: 2.5, h: 0.7, fontFace: FONT, margin: 0, valign: "middle" });
      T(s, stats[i][2], { x: x + 0.2, y: 2.38, w: 2.45, h: 0.35, fontSize: 13, bold: true, color: K.navy });
      T(s, stats[i][3], { x: x + 0.2, y: 2.78, w: 2.45, h: 0.95, fontSize: 10.5, color: K.sub });
    }
    card(s, MX, 3.95, 8.9, 0.68, K.goldSoft, "E8D2A0");
    T(s, "如实说明：识别对象是小麦条锈病，不是黄瓜霜霉病；原始比例（约 1/3 阳性）下三种选样没有差别，稀释条件是看到结果后追加的；小麦风险模型不用于大棚。", { x: MX + 0.2, y: 3.95, w: 8.5, h: 0.68, fontSize: 10.5, color: "7A5410", valign: "middle" });
    s.addNotes("（约 30 秒）项目前期做的是小麦，那些成果在这里只证明方法我们做得出来，也做过客观评估：识别 F1 0.82；病株稀少时主动选样能省四到五成标注。下面这行限制条件要讲出来，评委会认可这种诚实。");
  }

  // ===== 11 当前进展 =====
  {
    const s = content("证据", "当前进展：大棚软件主线已跑通，下一步试拍", "软件闭环已经在模拟大棚里转起来；还差真车和大棚实拍。");
    const rows = [
      ["按株建档、单株时间线", "已完成", "ok"],
      ["棚内温湿度、环境指数、每天四张名单", "已完成", "ok"],
      ["车端质量判断与补拍、分步上传", "已完成（假硬件）", "ok"],
      ["前端：工作台、手机确认、展示屏", "已完成", "ok"],
      ["大棚模拟与巡检策略比较", "已完成", "ok"],
      ["小车离线执行巡检计划", "进行中", "wip"],
      ["真车硬件、大棚实拍、霜霉病识别", "未开始", "todo"],
    ];
    rows.forEach(([a, b, st], i) => {
      const y = 1.42 + i * 0.44;
      T(s, a, { x: MX, y, w: 3.4, h: 0.36, fontSize: 11, color: K.ink, valign: "middle" });
      const m = { ok: [K.okInk, K.okSoft], wip: [K.wipInk, K.wipSoft], todo: [K.random, K.todoSoft] }[st];
      pill(s, MX + 3.45, y + 0.04, 1.25, b, m[0], m[1], 9.5, 0.28);
    });
    const iw = 3.9, ih = iw * 720 / 1440;
    shot(s, "workbench.jpg", 5.45, 1.42, iw, ih);
    const st = [["302", "项后端测试全过"], ["24", "张表"], ["16", "个迁移"]];
    st.forEach(([n, d], i) => {
      const x = 5.45 + i * 1.3;
      T(s, n, { x, y: 1.42 + ih + 0.12, w: 1.3, h: 0.45, fontSize: 22, bold: true, color: K.goldBright, valign: "middle" });
      T(s, d, { x, y: 1.42 + ih + 0.56, w: 1.3, h: 0.25, fontSize: 9.5, color: K.sub });
    });
    T(s, "模拟里同样的照片和人工预算下，风险驱动确认出 13.25 株、固定巡检 5.9 株（20 个种子均值）。模拟只证明流程，不是效果证据。", { x: 5.45, y: 4.22, w: iw, h: 0.5, fontSize: 9, color: K.muted });
    s.addNotes("（约 30 秒）软件主线已经跑通，main 分支 302 项后端测试全过。我们还做了大棚模拟，同样的照片和人工预算下，风险驱动比固定巡检确认出更多病株；但模拟里的病害规律是我们设计进去的，只能证明流程跑通。最大的短板是还没有真车和大棚实拍照片，这就是下一页的计划。");
  }

  // ===== 12 验证计划 =====
  {
    const s = content("证据", "验证计划：先试拍，再按株跟踪一整茬", "一茬一茬验证：先确认拍得到，再看能提前多少发现病株。");
    const ms = [
      ["10 月", "软件准备", "小车离线执行巡检计划；器件选型（云台、编码器、标签、温湿度记录仪）"],
      ["11 月前", "大棚试拍", "仰拍能否看清叶背、清晨窗口是否存在、补拍一次多久、过道多宽"],
      ["冬季", "识别基线", "公开数据先训「霜霉病 / 健康」；日光温室继续采集"],
      ["春茬", "按株跟踪验证", "整茬按株跟踪，与人工巡棚对比提前量和人工投入"],
    ];
    const y0 = 2.0;
    s.addShape(pres.shapes.LINE, { x: MX + 0.2, y: y0, w: 8.5, h: 0, line: { color: K.blueLine, width: 2 } });
    ms.forEach(([when, what, d], i) => {
      const x = MX + i * 2.25;
      s.addShape(pres.shapes.OVAL, { x: x + 0.12, y: y0 - 0.14, w: 0.28, h: 0.28, fill: { color: K.goldBright }, line: { color: K.white, width: 2 } });
      T(s, when, { x, y: 1.4, w: 2, h: 0.35, fontSize: 15, bold: true, color: K.gold });
      card(s, x, y0 + 0.35, 2.1, 2.0);
      T(s, what, { x: x + 0.15, y: y0 + 0.5, w: 1.85, h: 0.35, fontSize: 13, bold: true, color: K.navy });
      T(s, d, { x: x + 0.15, y: y0 + 0.92, w: 1.85, h: 1.35, fontSize: 10.5, color: K.sub });
    });
    s.addNotes("（约 30 秒）试拍窗口很紧：河南塑料大棚的秋茬大约 11 月结束，错过就要等春茬或在日光温室冬季继续。所以 10 月把软件准备好，11 月前试拍，冬季做识别基线，春茬整茬按株跟踪，和人工巡棚对比。");
  }

  // ===== 13 用户与商业模式 =====
  pres.addSection({ title: "落地" });
  {
    const s = content("落地", "用户与商业模式：先进规整大棚，再进散户", "我国设施面积 4270 多万亩，八成以上种蔬菜。");
    const nums = [
      ["4270 万亩+", "全国设施面积，占世界 80% 以上"],
      ["80%+", "设施面积用于种蔬菜"],
      ["2.65 亿吨", "设施蔬菜年产量，占蔬菜总产量 1/3"],
      ["128 万公顷", "全国黄瓜生产面积（FAO 2020）"],
    ];
    nums.forEach(([n, d], i) => {
      const x = MX + (i % 2) * 2.25, y = 1.42 + Math.floor(i / 2) * 1.32;
      card(s, x, y, 2.1, 1.18);
      T(s, n, { x: x + 0.15, y: y + 0.12, w: 1.9, h: 0.5, fontSize: 20, bold: true, color: K.goldBright, valign: "middle" });
      T(s, d, { x: x + 0.15, y: y + 0.63, w: 1.85, h: 0.5, fontSize: 10, color: K.sub });
    });
    T(s, "来源：农业农村部计划财务司（2024-12）；光明网科普引 FAO 2020。设施黄瓜面积【待补】", { x: MX, y: 4.1, w: 4.4, h: 0.5, fontSize: 9, color: K.muted });
    const stepsX = 5.3;
    const steps = [
      ["LuBuilding2", "第一步", "规整的大棚基地、合作社", "过道规整，用小车"],
      ["LuGraduationCap", "第二步", "农技服务站、植保服务队", "一套设备服务多个棚【待核实】"],
      ["LuHand", "第三步", "散户塑料大棚", "手持杆式或手推式设备，离线采集"],
    ];
    for (let i = 0; i < 3; i++) {
      const y = 1.42 + i * 0.86;
      card(s, stepsX, y, 4.15, 0.74);
      await ic(s, steps[i][0], stepsX + 0.12, y + 0.14, 0.46);
      pill(s, stepsX + 0.7, y + 0.1, 0.7, steps[i][1], K.white, K.blue, 9.5, 0.26);
      T(s, steps[i][2], { x: stepsX + 1.5, y: y + 0.08, w: 2.6, h: 0.3, fontSize: 11.5, bold: true, color: K.navy, valign: "middle" });
      T(s, steps[i][3], { x: stepsX + 0.7, y: y + 0.42, w: 3.4, h: 0.28, fontSize: 10, color: K.sub, valign: "middle" });
    }
    T(s, "收费方式与定价：【待填】", { x: stepsX, y: 4.08, w: 4.15, h: 0.3, fontSize: 11, bold: true, color: K.gold });
    s.addNotes("（约 40 秒）市场数字来自农业农村部网站和 FAO。我们先服务过道规整的大棚基地和合作社，再通过农技服务组织扩到更多棚，散户用轻便的手持或手推设备。定价和收费方式请团队补上。第二步的服务模式是推测，需要团队核实后再讲。");
  }

  // ===== 14 社会价值 =====
  {
    const s = content("落地", "社会价值：让病在叶背阶段就被看到", "设施高湿环境病虫害高发、乱用药屡禁不止；早看到，才能少用药。");
    const vals = [
      ["LuSprout", "少用药", "病在叶背阶段就被看到、被确认，处理更早，减少大面积打药的需要【效果待田间验证】"],
      ["LuUsers", "省翻叶人工", "人只确认被推送的几株，不必每天逐株翻叶"],
      ["LuFileSearch", "结论可追溯", "每条结论都能追到原图、拍摄质量和确认人"],
      ["LuHandCoins", "低成本可推广", "普通相机 + 树莓派，不改造大棚；散户可用手持设备"],
    ];
    for (let i = 0; i < 4; i++) {
      const x = MX + (i % 2) * 4.5, y = 1.42 + Math.floor(i / 2) * 1.62;
      card(s, x, y, 4.3, 1.45);
      await ic(s, vals[i][0], x + 0.2, y + 0.22, 0.58);
      T(s, vals[i][1], { x: x + 0.95, y: y + 0.2, w: 3.2, h: 0.4, fontSize: 15, bold: true, color: K.navy, valign: "middle" });
      T(s, vals[i][2], { x: x + 0.95, y: y + 0.65, w: 3.2, h: 0.72, fontSize: 10.5, color: K.sub });
    }
    s.addNotes("（约 25 秒）农业农村部的文章提到，设施封闭高湿环境病虫害高发、乱用药屡禁不止。巡知的价值是让病在叶背阶段就被看到，省掉逐株翻叶的人工，每个结论都可追溯，而且成本低。少用药的效果需要春茬田间验证后才能给数字。");
  }

  // ===== 15 团队 =====
  {
    const s = content("落地", "团队与需要的支持", "四个方向对应四个子系统；我们最需要大棚场地和农技专家。");
    const team = [
      ["LuWrench", "小车与硬件", "云台、补光、编码器、标签"],
      ["LuCpu", "车端采集软件", "质量判断、补拍、断网续传"],
      ["LuNetwork", "平台与决策", "按株归档、环境指数、巡检名单"],
      ["LuFlaskConical", "识别与数据", "霜霉病识别、试拍数据、标注"],
    ];
    for (let i = 0; i < 4; i++) {
      const x = MX + i * 2.25;
      card(s, x, 1.42, 2.1, 2.05);
      await ic(s, team[i][0], x + 0.75, 1.58, 0.6);
      T(s, team[i][1], { x: x + 0.1, y: 2.27, w: 1.9, h: 0.32, fontSize: 13, bold: true, color: K.navy, align: "center" });
      T(s, team[i][2], { x: x + 0.12, y: 2.62, w: 1.86, h: 0.42, fontSize: 9.5, color: K.sub, align: "center" });
      T(s, "【待填：姓名 · 专业】", { x: x + 0.1, y: 3.08, w: 1.9, h: 0.28, fontSize: 9.5, color: K.gold, align: "center" });
    }
    const need = [["LuWarehouse", "大棚场地：秋茬试拍、春茬整茬跟踪"], ["LuGraduationCap", "农技专家：复核阈值与人工结论"], ["LuHandCoins", "经费：【待填】"]];
    for (let i = 0; i < 3; i++) {
      const x = MX + i * 3.0;
      await ic(s, need[i][0], x, 3.72, 0.42);
      T(s, need[i][1], { x: x + 0.5, y: 3.72, w: 2.4, h: 0.42, fontSize: 10.5, bold: true, color: K.navy, valign: "middle" });
    }
    s.addNotes("（约 25 秒）团队按四个子系统分工，名字请团队补上。我们最需要的支持是大棚场地和农技专家，经费需求也请补上。");
  }

  // ===== 16 致谢 =====
  pres.addSection({ title: "结尾" });
  {
    const s = pres.addSlide({ masterName: "END", sectionTitle: "结尾" });
    T(s, "感谢各位评委", { x: 0, y: 1.25, w: W, h: 0.8, fontSize: 36, bold: true, color: K.navy, align: "center", valign: "middle" });
    s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x: 1.6, y: 2.3, w: 6.8, h: 0.62, rectRadius: 0.31, fill: { color: K.white }, line: { color: K.blueLine } });
    T(s, "挑对时机，拍到叶背，认准每一株，只把值得看的推给人", { x: 1.6, y: 2.3, w: 6.8, h: 0.62, fontSize: 15, bold: true, color: K.gold, align: "center", valign: "middle" });
    T(s, "巡知 AgriScout", { x: 0, y: 3.15, w: W, h: 0.35, fontSize: 13, color: K.blue, align: "center", bold: true });
    s.addNotes("（约 10 秒）挑对时机，拍到叶背，认准每一株，只把值得看的推给人。谢谢各位评委。");
  }

  // ===== 备用 A–C =====
  pres.addSection({ title: "备用" });
  const hdr = (t) => ({ text: t, options: { bold: true, color: K.white, fill: { color: K.navy }, fontSize: 11 } });
  const tbl = (s, rows, colW, rowH = 0.5) => s.addTable(rows, {
    x: MX, y: 1.42, w: 8.9, colW, fontFace: FONT, fontSize: 10.5, color: K.ink, fill: { color: K.white },
    border: { type: "solid", pt: 0.75, color: K.line }, rowH, valign: "middle", margin: [0, 0.1, 0, 0.1],
  });
  {
    const s = content("备用", "备用 A · 观察依据与先例", null);
    tbl(s, [
      [hdr("依据"), hdr("内容"), hdr("我们怎么用")],
      ["为什么看叶背", "早期征兆和确诊特征集中在下部叶片的叶背（APS 黄瓜霜霉病诊断指南等）", "低位仰拍 + 补光"],
      ["为什么看清晨", "部分征兆只在清晨高湿时明显；夜间结露加重病情", "前夜湿润 ≥4 小时排清晨窗口"],
      ["适宜发病条件", "约 15–25℃、相对湿度 85% 以上", "环境指数的适宜小时"],
      ["CN221048423U", "温室黄瓜叶部病害巡检与识别机器人", "「小车 + 识别」不当创新点"],
      ["US11483471B2（Viewnetic）", "补光仰拍叶背", "「仰拍叶背」不当创新点"],
      ["Frontiers 2026（农大 / 北大）", "环境引导的三阶段早期检测", "引用「健康 / 早期 / 明显」口径"],
    ], [2.2, 4.1, 2.6]);
    s.addNotes("答辩备用：被问到观察依据和先例时翻到这页。");
  }
  {
    const s = content("备用", "备用 B · 参数从哪里来", null);
    tbl(s, [
      [hdr("参数"), hdr("当前值"), hdr("状态")],
      ["叶背视角与补拍", "正面 0°、叶背 35° / 50°；不合格 +5°，最多 3 次", "经验初值，待试拍校准"],
      ["图像质量 iq-rule-v1", "清晰度、亮度、过曝 / 欠曝、逆光阈值", "经验初值，待试拍校准"],
      ["适宜 / 湿润小时", "15–25℃ 且 RH≥85%；RH≥95% 或露点差 ≤1℃", "带文献出处，待农技复核"],
      ["清晨窗口", "前夜湿润 ≥4 小时 → 次日 05:30–08:30", "待试拍验证窗口是否存在"],
      ["人工预算", "每天 5 株", "可按基地人手调整"],
      ["补拍预算", "随环境指数在 10%–25% 间变化", "启发式，待校准"],
      ["全覆盖 / 抽查", "7 天没看到必拍；每天抽 5%，至少 1 株", "保证不因风险低少巡"],
    ], [2.2, 4.1, 2.6], 0.42);
    s.addNotes("答辩备用：被问到参数怎么定时翻到这页。所有参数都写在代码里并带出处注释，试拍后用实测替换。");
  }
  {
    const s = content("备用", "备用 C · 风险与应对", null);
    tbl(s, [
      [hdr("风险"), hdr("应对")],
      ["试拍窗口紧：秋茬约 11 月结束", "10 月备好软件；错过就转日光温室冬季采集，春茬整茬验证"],
      ["过道窄、路况差（泥、软管、采收筐）", "小车只承诺规整大棚；散户用手持杆式或手推式设备，同一套软件"],
      ["散户大棚没电没网", "质量判断在车上算，照片逐点落盘，有网时再上传；计划提前下载"],
      ["参数未校准", "所有阈值带出处、可配置；试拍后用实测替换，再跑离线比较"],
      ["霜霉病识别还没做", "识别完成前模型分只作占位，不是诊断；人工结论优先"],
      ["模型漏掉新病灶", "风险不减少巡检：低频全覆盖和随机抽查一直保留"],
    ], [3.4, 5.5], 0.5);
    s.addNotes("答辩备用：被问到风险时翻到这页。");
  }

  await pres.writeFile({ fileName: OUT });
  console.log("wrote", OUT);
})();
