#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
光遇每日任务 - 数据生成脚本（只依赖 Python 标准库，供 GitHub Actions 定时运行）

输出 data.json：页面同源读取，因此没有任何跨域问题。
数据源：
  A  SkyDailyInfo（网易精灵接口）→ 任务清单 / 天气 / 日历 / 先祖位置 / 活动
  C  9game 九游 → 每日任务图文（完成方法+位置+标注步骤图）/ 落石点 / 大蜡烛 / 免费魔法 / 活动代币
  B  sky-auto（已停更）→ 仅保留与今日任务名匹配的图文 + 固定参考，其余自动隐藏
"""

import datetime
import html as htmllib
import json
import os
import re
import sys
import urllib.request

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")
URL_A = "https://raw.githubusercontent.com/oivio-up/SkyDailyInfo/main/README.md"
URL_B = "https://raw.githubusercontent.com/xiaoyanu/sky-auto/main/README.md"
URL_C_LIST = "https://www.9game.cn/skygy/"
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data.json")

IMG_MD_RE = re.compile(r"!\[[^\]]*\]\((https?://[^)\s]+)\)")


# ----------------------------------------------------------------- 工具
def fetch(url, timeout=40):
    req = urllib.request.Request(url, headers={
        "User-Agent": UA,
        "Accept": "*/*",
        "Accept-Encoding": "identity",
        "Accept-Language": "zh-CN,zh;q=0.9",
    })
    with urllib.request.urlopen(req, timeout=timeout) as r:
        raw = r.read()
        ct = r.headers.get("Content-Type", "") or ""
        m = re.search(r"charset=([\w\-]+)", ct)
        enc = m.group(1) if m else "utf-8"
        try:
            return raw.decode(enc, errors="replace")
        except LookupError:
            return raw.decode("utf-8", errors="replace")


def text(v):
    return {"t": "text", "v": v}


def img(v):
    return {"t": "img", "v": v}


def heading(v):
    return {"t": "head", "v": v}


def note(v):
    return {"t": "note", "v": v}


def strip_images(s):
    out = []
    for line in s.replace("\r\n", "\n").split("\n"):
        if line.strip().startswith("!["):
            continue
        out.append(line.rstrip())
    return "\n".join(out)


def clean_text(s):
    out, last_blank = [], False
    for raw in s.replace("\r\n", "\n").split("\n"):
        t = raw.strip()
        if not t:
            if not last_blank and out:
                out.append("")
            last_blank = True
            continue
        if t in ("---", "***", "___"):
            continue
        out.append(t)
        last_blank = False
    while out and not out[-1]:
        out.pop()
    return "\n".join(out)


# ----------------------------------------------------------------- 源 A
def parse_source_a(md):
    info = {"key": "A", "name": "SkyDailyInfo", "url": URL_A, "ok": False,
            "updated": None, "content_date": None, "error": "", "sections": []}
    if not md:
        info["error"] = "内容为空"
        return info

    block = md
    s = md.find("<!-- DAILY_TASK_START -->")
    e = md.find("<!-- DAILY_TASK_END -->")
    if s >= 0 and e > s:
        block = md[s + len("<!-- DAILY_TASK_START -->"):e]

    m = re.search(r"最后更新[:：]\s*([^\r\n(（]+)", block)
    if m:
        raw = m.group(1).strip()
        info["updated"] = raw
        for fmt in ("%Y年%m月%d日 %H:%M:%S", "%Y年%m月%d日 %H:%M", "%Y年%m月%d日"):
            try:
                info["content_date"] = datetime.datetime.strptime(raw, fmt).strftime("%Y-%m-%d")
                break
            except ValueError:
                pass

    tasks, weather_sec, calendar_sec, detail_sec, events_sec = [], None, None, None, None

    for head, body in split_sections(block):
        if "今日旅行指南" in head:
            for t in parse_task_lines(body):
                tasks.append(t)
        elif "天气预报" in head:
            if weather_sec is None:
                weather_sec = {"title": "🌤️ 天气预报", "blocks": []}
            txt = clean_text(strip_images(body))
            if txt:
                weather_sec["blocks"].append(text(txt))
            for u in IMG_MD_RE.findall(body):
                weather_sec["blocks"].append(img(u))
        elif "日历" in head:
            urls = IMG_MD_RE.findall(body)
            if urls:
                if calendar_sec is None:
                    calendar_sec = {"title": "📅 本月日历", "blocks": []}
                calendar_sec["blocks"].append(img(urls[0]))
        elif "攻略" in head:
            for d in parse_details(body):
                if detail_sec is None:
                    detail_sec = {"title": "📖 先祖位置攻略（补充）", "blocks": []}
                detail_sec["blocks"].append(heading("📍 " + d["title"]))
                if d["text"]:
                    detail_sec["blocks"].append(text(d["text"]))
                for u in d["images"]:
                    detail_sec["blocks"].append(img(u))
        elif "活动" in head:
            txt = clean_text(strip_images(body)) or "今日暂无特殊活动"
            if events_sec is None:
                events_sec = {"title": "🎪 今日活动", "blocks": []}
            events_sec["blocks"].append(text(txt))

    secs = []
    task_sec = None
    if tasks:
        task_sec = {"title": "🎯 今日任务（清单）", "blocks": [text(t) for t in tasks], "kind": "tasks"}
        secs.append(task_sec)
    for x in (weather_sec, calendar_sec, detail_sec, events_sec):
        if x:
            secs.append(x)

    info["sections"] = secs
    info["ok"] = bool(secs)
    if not info["ok"]:
        info["error"] = "页面结构可能已变化，未解析到内容"
    return info


def split_sections(block):
    out = []
    ms = list(re.finditer(r"^###(?!#)\s*(.+?)\s*$", block, re.M))
    for i, m in enumerate(ms):
        start = m.end()
        end = ms[i + 1].start() if i + 1 < len(ms) else len(block)
        out.append((m.group(1).strip(), block[start:end]))
    return out


def parse_task_lines(body):
    fence = re.search(r"```[^\n]*\n(.*?)```", body, re.S)
    src = fence.group(1) if fence else body
    tasks = []
    for line in src.replace("\r\n", "\n").split("\n"):
        m = re.match(r"^(\d+)\s*[\.、]\s*(.+)$", line.strip())
        if not m:
            continue
        t = re.sub(r"\s*[>》]+.*$", "", m.group(2).strip()).strip()
        if t:
            tasks.append("%s. %s" % (m.group(1), t))
    return tasks


def parse_details(body):
    out = []
    ms = list(re.finditer(r"^####\s*(.+?)\s*$", body, re.M))
    for i, m in enumerate(ms):
        start = m.end()
        end = ms[i + 1].start() if i + 1 < len(ms) else len(body)
        chunk = body[start:end]
        out.append({
            "title": re.sub(r"^[📍\s]+", "", m.group(1).strip()).strip(),
            "images": IMG_MD_RE.findall(chunk),
            "text": clean_text(strip_images(chunk)),
        })
    return out


# ----------------------------------------------------------------- 源 C
def icon_for_c(title):
    for k, v in (("每日任务", "📖 "), ("落石", "🪨 "), ("日程", "📋 "),
                 ("大蜡烛", "🕯️ "), ("魔法", "✨ "), ("代币", "🪙 ")):
        if k in title:
            return v
    return "🎉 "


def discover_today(list_html, today):
    md = "%d.%d" % (today.month, today.day)
    for m in re.finditer(r'<a[^>]+href="([^"]+)"[^>]*>([^<]{0,80})</a>', list_html):
        label = htmllib.unescape(m.group(2))
        if "每日任务" not in label or md not in label:
            continue
        href = m.group(1)
        if href.startswith("//"):
            href = "https:" + href
        elif href.startswith("/"):
            href = "https://www.9game.cn" + href
        if href.startswith("http"):
            return href, label.strip()
    return None, None


END_MARKERS = ["（以上内容转自", "以上内容转自", "本文仅用作社区交流", "相关阅读", "最新文章",
               "玩家评论", "全部评论", "其他玩家还在玩", "游戏专题", "加入九游群聊",
               "猜你喜欢", "热门游戏"]
MARK_RE = re.compile(r"^[【『]([^】』]{1,24})[】』]\s*(.*)$")


def parse_source_c(article_html, url, label):
    info = {"key": "C", "name": "9game 九游", "url": url, "list_label": label, "ok": False,
            "updated": None, "content_date": None, "error": "", "sections": []}
    if not article_html:
        info["error"] = "内容为空"
        return info

    m = re.search(r"发布时间[:：]\s*(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})", article_html)
    if m:
        info["updated"] = m.group(1)
        info["content_date"] = m.group(1)[:10]

    s = article_html.find("发布时间")
    if s < 0:
        info["error"] = "页面结构可能已变化（找不到发布时间）"
        return info
    ends = [article_html.find(k, s) for k in END_MARKERS]
    ends = [e for e in ends if e > s]
    e = min(ends) if ends else min(s + 40000, len(article_html))
    body = article_html[s:e]

    body = re.sub(r"(?s)<script.*?</script>", "", body)
    body = re.sub(r"(?s)<style.*?</style>", "", body)
    body = re.sub(r'<img[^>]*?src="([^"]+)"[^>]*>', r"\n@@IMG@@\1\n", body)
    body = re.sub(r"(?i)<br\s*/?>", "\n", body)
    body = re.sub(r"(?i)</p>", "\n", body)
    body = re.sub(r"(?i)</div>", "\n", body)
    body = re.sub(r"<[^>]+>", "\n", body)
    body = htmllib.unescape(body)

    secs, cur, started = [], None, False
    for raw in body.split("\n"):
        line = raw.strip()
        if not line:
            continue
        mk = MARK_RE.match(line)
        if mk:
            started = True
            title = mk.group(1).strip()
            cur = {"title": icon_for_c(title) + title, "blocks": []}
            secs.append(cur)
            rest = mk.group(2).strip()
            if rest:
                cur["blocks"].append(text(rest))
            continue
        if not started or cur is None:
            continue
        if line.startswith("@@IMG@@"):
            u = line[7:].strip()
            if u.startswith("http"):
                cur["blocks"].append(img(u))
            continue
        if len(line) <= 1:
            continue
        cur["blocks"].append(text(line))

    secs = [x for x in secs if x["blocks"]]
    info["sections"] = secs
    info["ok"] = bool(secs)
    if not info["ok"]:
        info["error"] = "正文解析为空"
    return info


# ----------------------------------------------------------------- 源 B（存档，已停更）
TASK_KEYWORDS = ["光芒", "招手", "礼物", "舞者", "冥想", "光点", "烛火", "长凳", "螃蟹", "星光",
                 "水母", "遥鲲", "冥龙", "风筝", "神坛", "温泉", "沉船", "浮石", "仙乡", "老奶奶",
                 "说书人", "建筑师", "领航员", "舰长", "地理学家", "渔夫", "低语者", "敬礼", "正步",
                 "气功", "先祖", "蘑菇", "巨兽", "荒漠", "庭院", "庇护所", "密林", "边陲", "拱门",
                 "滑冰场", "圆梦村", "剧场", "秘密花园", "黑暗植物", "蜡烛", "光之翼", "花"]


def parse_source_b(md, today_tasks):
    info = {"key": "B", "name": "sky-auto（已停更）", "url": URL_B, "ok": False,
            "updated": None, "content_date": None, "error": "", "sections": []}
    if not md:
        info["error"] = "内容为空"
        return info

    m = re.search(r"(?m)^date:\s*(.+)$", md)
    if m:
        info["updated"] = m.group(1).strip()

    dates = re.findall(r"1_kol_(\d{8})_", md)
    if dates:
        info["content_date"] = "%s-%s-%s" % (max(dates)[:4], max(dates)[4:6], max(dates)[6:])

    # 按 **粗体** 切板块
    body = re.sub(r"(?m)^#\s+.*$", "", md)
    raw, cur = [], None

    def is_card(t):
        if len(t) > 2 and t.startswith("任务") and t[2] in "一二三四五六":
            return True
        return any(k in t for k in ("季节蜡烛", "大蜡烛", "今日免费魔法", "免费魔法",
                                    "黑暗藤蔓", "一起听", "伊甸"))

    for line in body.replace("\r\n", "\n").split("\n"):
        line = line.strip()
        if not line:
            continue
        h = re.match(r"^\*\*(.+?)\*\*$", line)
        if h:
            inner = h.group(1).strip()
            im = re.match(r"^!\[[^\]]*\]\((https?://[^)\s]+)\)$", inner)
            if im:
                if cur:
                    cur["blocks"].append(img(im.group(1)))
                continue
            if not inner:
                continue
            if is_card(inner):
                cur = {"title": inner, "blocks": []}
                raw.append(cur)
            elif cur is not None:
                cur["blocks"].append(heading(inner))
            continue
        if cur is None:
            continue
        if line in ("---", "***"):
            continue
        inline = IMG_MD_RE.findall(line)
        if inline:
            rest = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", line).strip().strip("*").strip()
            if rest:
                cur["blocks"].append(text(rest))
            for u in inline:
                cur["blocks"].append(img(u))
            continue
        cur["blocks"].append(text(line.strip("*").strip()))

    raw = [x for x in raw if x["blocks"]]
    stale = bool(info["content_date"]) and info["content_date"] != today_tasks["date"]

    if not stale:
        info["sections"] = raw
        info["ok"] = bool(raw)
        return info

    kept = []
    for sec in raw:
        t = sec["title"]
        if "一起听" in t or "黑暗藤蔓" in t:
            kept.append(tag_archive(sec, "固定参考", info["content_date"]))
            continue
        if not (len(t) > 2 and t.startswith("任务") and t[2] in "一二三四五六"):
            continue
        for task in today_tasks["list"]:
            if any(k in task and k in t for k in TASK_KEYWORDS):
                kept.append(tag_archive(sec, "与今日任务匹配", info["content_date"]))
                break

    warn = {"title": "🗂️ 图文存档源说明（重要）", "kind": "warn", "blocks": [note(
        "存档源 sky-auto 表面上每天照常提交，但它的上游 KOL「Sky孤独旅人」已于 %s 宣布停止每日更新，"
        "图文从那天起就没变过。下面只保留与今日任务名称匹配的攻略和固定参考；"
        "季节蜡烛 / 大蜡烛 / 免费魔法等每天会变的内容已自动隐藏。" % info["content_date"])]}
    info["sections"] = [warn] + kept
    info["ok"] = True
    info["stale"] = True
    return info


def tag_archive(sec, reason, date_str):
    blocks = [note("存档内容（素材 %s，%s），仅供参考" % (date_str, reason))]
    blocks += sec["blocks"]
    return {"title": "🗂️ " + sec["title"], "blocks": blocks, "kind": "archive"}


# ----------------------------------------------------------------- 主流程
def main():
    now = datetime.datetime.now()
    today = now.strftime("%Y-%m-%d")
    warnings = []

    # 源 A
    info_a = {"key": "A", "name": "SkyDailyInfo", "url": URL_A, "ok": False, "sections": [],
              "updated": None, "content_date": None, "error": ""}
    try:
        info_a = parse_source_a(fetch(URL_A))
    except Exception as ex:
        info_a["error"] = str(ex)
        warnings.append("SkyDailyInfo 抓取失败：%s" % ex)

    # 源 C：先看列表页，再抓今天的文章
    info_c = {"key": "C", "name": "9game 九游", "url": URL_C_LIST, "ok": False, "sections": [],
              "updated": None, "content_date": None, "error": ""}
    try:
        list_html = fetch(URL_C_LIST)
        art_url, label = discover_today(list_html, now)
        if art_url:
            info_c = parse_source_c(fetch(art_url), art_url, label)
        else:
            info_c["error"] = "9game 还没发布今天的图文（通常上午 10:30-11:20 发布）"
            warnings.append(info_c["error"])
    except Exception as ex:
        info_c["error"] = str(ex)
        warnings.append("9game 抓取失败：%s" % ex)

    # 源 B：存档
    today_tasks = {"date": today, "list": []}
    for sec in info_a.get("sections", []):
        if sec.get("kind") == "tasks":
            today_tasks["list"] = [b["v"] for b in sec["blocks"] if b["t"] == "text"]
    info_b = {"key": "B", "name": "sky-auto（已停更）", "url": URL_B, "ok": False, "sections": [],
              "updated": None, "content_date": None, "error": ""}
    try:
        info_b = parse_source_b(fetch(URL_B), today_tasks)
    except Exception as ex:
        info_b["error"] = str(ex)

    for info in (info_a, info_c):
        if info.get("ok") and info.get("content_date") and info["content_date"] != today:
            info["stale"] = True
            warnings.append("%s 的内容日期是 %s，不是今天" % (info["name"], info["content_date"]))

    # 标记每个板块的来源，供客户端上色/归类
    for sec in info_a.get("sections", []):
        sec["src"] = "A"
    for sec in info_c.get("sections", []):
        sec["src"] = "C"
    for sec in info_b.get("sections", []):
        sec["src"] = "B"

    # 合并顺序：A 任务清单 → C 每日任务 → C 其它 → A 天气/日历/先祖/活动 → B 存档
    sections = []
    for sec in info_a.get("sections", []):
        if sec.get("kind") == "tasks":
            sections.append(sec)
    c_secs = info_c.get("sections", [])
    sections += [s for s in c_secs if "每日任务" in s["title"]]
    sections += [s for s in c_secs if "每日任务" not in s["title"]]
    sections += [s for s in info_a.get("sections", []) if s.get("kind") != "tasks"]
    sections += info_b.get("sections", [])

    data = {
        "generated_at": now.strftime("%Y-%m-%d %H:%M:%S"),
        "today": today,
        "sources": [strip_sections(x) for x in (info_a, info_c, info_b)],
        "warnings": warnings,
        "sections": sections,
    }

    # 内容没变化时沿用旧的生成时间，让文件逐字节不变 → git 不会产生无意义提交
    old = None
    try:
        with open(OUT, "r", encoding="utf-8") as f:
            old = json.load(f)
    except Exception:
        old = None
    unchanged = False
    if isinstance(old, dict) and same_content(old, data):
        data["generated_at"] = old.get("generated_at", data["generated_at"])
        unchanged = True

    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)

    img_count = sum(1 for s in sections for b in s["blocks"] if b["t"] == "img")
    print("已生成 %s%s" % (OUT, "（内容无变化，未改动）" if unchanged else ""))
    print("  今日 %s，板块 %d 个，图片 %d 张" % (today, len(sections), img_count))

    # 顺便产出一份"单文件离线版"，放在网页版目录和程序目录（方便双击）
    here = os.path.dirname(os.path.abspath(__file__))
    write_standalone(data, [
        os.path.join(here, "光遇每日任务.html"),
        os.path.join(os.path.dirname(here), "光遇每日任务.html"),
    ])
    for x in data["sources"]:
        print("  [%s] %s  内容日期=%s  %s" % (x["key"], "OK" if x["ok"] else "失败",
                                            x["content_date"] or "未知", x["error"] or ""))
    for w in warnings:
        print("  ⚠ %s" % w)
    return 0


def same_content(a, b):
    x, y = dict(a), dict(b)
    x.pop("generated_at", None)
    y.pop("generated_at", None)
    return x == y


def write_standalone(data, out_paths):
    """生成"单文件离线版"：把数据内嵌进 HTML，双击 file:// 就能看（不需要任何服务器）"""
    here = os.path.dirname(os.path.abspath(__file__))
    tpl_path = os.path.join(here, "index.html")
    try:
        with open(tpl_path, "r", encoding="utf-8") as f:
            tpl = f.read()
    except Exception as ex:
        print("  ⚠ 生成单文件离线版失败（读不到 index.html）：%s" % ex)
        return
    # 防止数据里出现 </script> 把脚本标签提前闭合
    snap = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
    html = tpl.replace("var SNAPSHOT = null;", "var SNAPSHOT = " + snap + ";")
    if html == tpl:
        print("  ⚠ index.html 里没找到 SNAPSHOT 占位符，跳过单文件生成")
        return
    for p in out_paths:
        try:
            with open(p, "w", encoding="utf-8") as f:
                f.write(html)
            print("  单文件离线版：%s（%.0f KB，双击即可打开）" % (p, os.path.getsize(p) / 1024.0))
        except Exception as ex:
            print("  ⚠ 写入 %s 失败：%s" % (p, ex))


def strip_sections(info):
    out = dict(info)
    out.pop("sections", None)
    return out


if __name__ == "__main__":
    sys.exit(main())
