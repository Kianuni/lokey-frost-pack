#!/usr/bin/env python3
"""
lokey-frost-pack Offline .lokeypack Compiler (LKLF-v2 + LNLM-v2)
Compiles gaboolic/rime-frost YAML dictionaries + English mixed-input lists +
conversational/neural tables into a standalone, 8-byte aligned, zero-copy
`mmap`-ready `.lokeypack` binary (`rime-frost.lokeypack`).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import struct
import subprocess
import sys
import zlib
from collections import defaultdict
from pathlib import Path

SYLLABLE_RE = re.compile(r"^[a-z]{1,7}$")
INVALID_NON_MANDARIN_SYLLABLES = frozenset({
    # Japanese romaji readings leaking from name.dict.yaml & non-Mandarin syllable typo `junding`
    "azusawa", "chiaki", "chihara", "fujii", "fujita", "harase", "hasegawa",
    "hashimoto", "hayashi", "hiroi", "ishikawa", "ito", "junding", "kato",
    "kobayashi", "koichi", "konaka", "kyoko", "masuda", "matsumoto", "maya",
    "miki", "muneaki", "nakamura", "naruse", "oji", "okino", "saito", "sato",
    "shogo", "takahashi", "utano", "yamamoto", "yoko", "yutaka",
})
NOISY_DE_VERB_PREFIXES = frozenset({"跑", "走", "写", "看", "吃", "睡", "飞", "跳", "打", "做", "说", "唱", "游", "骑"})
ASCII_WORD_RE = re.compile(r"^[A-Za-z][A-Za-z0-9._+-]{1,23}$")
ASCII_PHRASE_RE = re.compile(r"^[A-Za-z][A-Za-z0-9 ._'+&-]{1,31}$")
NON_ALNUM_RE = re.compile(r"[^a-z0-9]")

# Curated rime-frost Chinese tables (excluding huge noisy 0-weight composite dump).
CORE_CN_TABLES = [
    ("cn_dicts/8105.dict.yaml", 0.5),         # All standard characters kept even if rare reading w=0
    ("cn_dicts/41448.dict.yaml", 0.2),        # Extended rare CJK characters (single chars)
    ("cn_dicts/base.dict.yaml", 1.0),         # Core everyday lexicon
    ("cn_dicts/ext.dict.yaml", 1.0),          # Modern extended lexicon
    ("cn_dicts/others.dict.yaml", 8.0),       # Idiomatic expressions / slang
    ("cn_dicts/corrections.dict.yaml", 220.0) # Mispronunciation rescues (e.g. hun dun -> 馄饨)
]

CELL_TABLES_ALLOW_ZERO = {
    "computer.dict.yaml",
    "exthot.dict.yaml",
    "idiom.dict.yaml",
}

CELL_TABLES_POSITIVE_ONLY = {
    "animal.dict.yaml",
    "chess.dict.yaml",
    "chess2.dict.yaml",
    "composite.dict.yaml",
    "food.dict.yaml",
    "game.dict.yaml",
    "geography.dict.yaml",
    "history.dict.yaml",
    "industry_product.dict.yaml",
    "inputmethod.dict.yaml",
    "literature.dict.yaml",
    "luna.dict.yaml",
    "media.dict.yaml",
    "medication.dict.yaml",
    "music.dict.yaml",
    "name.dict.yaml",
    "name2.dict.yaml",
    "place.dict.yaml",
    "shulihua.dict.yaml",
    "sport.dict.yaml",
}

# Built-in high-frequency conversational next-word bigrams & chat associations
CURATED_CONVERSATIONAL_ASSOC: dict[str, list[str]] = {
    "明天": ["我们", "见", "早上", "下午", "去", "晚上", "再说", "有空", "休息", "开始"],
    "没有": ["问题", "什么", "识别", "办法", "人", "时间", "关系", "看到", "收到", "必要", "延迟"],
    "识别": ["出来", "成功", "失败", "码", "不出", "不了", "结果", "率", "到"],
    "我们": ["可以", "一起", "的", "在", "去", "明天", "今天", "现在", "已经", "见", "都是"],
    "你们": ["可以", "现在", "一起", "在", "去", "明天", "今天", "有空", "已经", "见", "都是"],
    "今天": ["下午", "晚上", "早上", "我们", "有空", "天气", "的", "去", "是", "休息"],
    "上午": ["开会", "有空", "上课", "有课", "见", "出发"],
    "中午": ["吃饭", "休息", "有空", "一起", "见"],
    "下午": ["有空", "有课", "开会", "上课", "休息", "见", "出发"],
    "晚上": ["吃饭", "有空", "一起", "见", "休息"],
    "昨天": ["晚上", "下午", "已经", "的", "看到", "说的", "去"],
    "现在": ["可以", "出去", "在", "已经", "去", "怎么样", "开始", "还没有", "有空"],
    "什么": ["时候", "意思", "情况", "问题", "东西", "都", "样的", "事", "人"],
    "怎么": ["样", "办", "回事", "了", "说", "弄", "走", "去", "可能"],
    "为什么": ["不", "要", "会", "没有", "不能", "这么", "呢"],
    "可以": ["吗", "吧", "啊", "的", "一起", "去", "试试", "看看", "直接", "用", "说"],
    "已经": ["收到", "完成", "好了", "到了", "开始", "发了", "没有", "在", "是"],
    "谢谢": ["你", "大家", "老板", "老师", "你们", "您", "啦"],
    "不好": ["意思", "说", "看", "吗", "用", "吃", "听"],
    "你好": ["呀", "吗", "请问", "啊"],
    "请问": ["一下", "你", "这个", "怎么", "有", "现在"],
    "需要": ["什么", "我", "帮忙", "注意", "多久", "多少"],
    "觉得": ["怎么样", "很", "不错", "可以", "挺好", "自己", "呢"],
    "希望": ["可以", "能", "你", "大家", "下次", "能够"],
    "如果": ["有", "可以", "没有", "你", "是", "需要", "不是"],
    "因为": ["我", "这个", "没有", "时间", "所以", "今天"],
    "所以": ["我", "我们", "就", "现在", "需要", "才"],
    "但是": ["我", "没有", "现在", "还是", "可以", "觉得"],
    "还是": ["可以", "没有", "要", "先", "算了", "觉得", "一样的"],
    "不能": ["用", "去", "这么", "再", "接受", "理解", "少"],
    "不会": ["吧", "有", "是", "再", "用", "的"],
    "不要": ["紧", "忘记", "着急", "去", "太", "这样"],
    "知道": ["了", "吗", "怎么", "什么", "这个", "为什么"],
    "看到": ["了", "你", "这个", "消息", "没有"],
    "收到": ["了", "消息", "通知", "谢谢"],
    "发给": ["我", "你", "他", "大家", "我们"],
    "人工": ["智能", "客服", "服务", "审核"],
    "智能": ["手机", "化", "纠错", "助手", "家居", "识别", "输入", "模型", "客服", "驾驶"],
    "输入": ["法", "引擎", "框", "密码", "内容", "设备", "效率"],
    "联想": ["词", "到", "集团", "能力", "电脑"],
    "纠错": ["能力", "引擎", "功能", "效果", "模型"],
    "我": ["们", "在", "今天", "明天", "现在", "收到", "一会", "一会儿", "要", "去", "觉得", "想", "可以", "没有", "已经"],
    "你": ["们", "好", "在", "今天", "明天", "现在", "觉得", "可以", "看看", "有"],
    "他": ["们", "在", "说", "是", "的", "已经", "没有"],
    "她": ["们", "在", "说", "是", "的", "已经", "没有"],
    "这": ["个", "里", "样", "是", "边", "次", "些", "么"],
    "那": ["个", "里", "样", "么", "边", "是", "就", "些"],
    "明": ["天", "白", "年", "显", "确", "日"],
    "没": ["有", "事", "问题", "关系", "办法", "空", "看到"],
    "没事": ["的", "吧", "啊", "儿", "了", "就好"],
    "真的": ["吗", "啊", "很", "是", "假不了", "不错"],
    "好的": ["呢", "呀", "啊", "吧", "谢谢", "收到"],
    "是的": ["呢", "呀", "啊", "吧"],
    "一会": ["要", "去", "见", "再说", "出去", "看", "还有"],
    "一会儿": ["要", "见", "再说", "去", "出去", "看"],
    "回头": ["见", "再说", "聊", "看"],
    "下次": ["见", "再说", "再聊", "一起"],
    "是": ["的", "吗", "啊", "吧", "不是", "呢", "什么", "我", "你"],
    "对": ["的", "吗", "啊", "吧", "不对", "不起", "了", "呢"],
    "行": ["吧", "吗", "啊", "的", "不行", "了"],
    "不": ["是", "好", "会", "能", "要", "知道", "过", "可以", "用"],
    "在": ["哪", "哪里", "吗", "家", "一起", "这", "路上", "忙"],
    "有": ["没有", "空", "时间", "什么", "点", "人", "问题", "可能"],
    "好": ["的", "吧", "啊", "呀", "吗", "啦", "像", "看", "久不见", "吃"],
    "去": ["哪", "哪里", "买", "看", "看看", "试试", "吃饭", "找", "做"],
    "出去": ["买", "买饭", "买菜", "吃饭", "吃", "玩", "走走", "看看", "逛逛", "一下", "一趟"],
    "去买": ["饭", "菜", "水", "药", "东西", "点", "个"],
    "买": ["饭", "菜", "水", "药", "东西", "了", "个", "点", "单"],
    "去哪": ["吃饭", "儿", "里", "玩", "了", "啊", "呀", "呢", "看", "找"],
    "在哪": ["吃饭", "儿", "里", "呢", "啊", "呀", "上班", "工作", "住", "看"],
    "干嘛": ["呢", "啊", "呀", "去"],
    "嗯": ["呢", "嗯", "呐", "啊", "好的", "可以"],
    "情况": ["呢", "下", "是", "吗", "的", "怎么样", "如何", "啊"],
    "来": ["了", "试试", "看看", "吧", "啊", "看", "说", "不及", "帮忙", "做"],
    "我来": ["试试", "看看", "说", "做", "帮", "写", "发"],
    "试试": ["看", "快速", "快速输入", "输入", "吧", "这个", "效果", "能不能", "一下"],
    "看看": ["这个", "那个", "吧", "呢", "怎么样", "效果", "能不能", "有", "什么", "情况"],
    "有点": ["甜", "热", "冷", "累", "卡", "贵", "慢", "难", "意思", "不对"],
    "见面": ["吧", "了", "再说", "聊", "的", "会"],
    "刚进": ["电梯", "门", "来", "去", "公司"],
    "要不": ["试试", "去", "一起", "算了", "先", "看看"],
    "感觉": ["好像", "不错", "怎么样", "还可以", "挺好", "有点"],
    "别": ["睡", "急", "忘了", "说", "动", "生气"],
    "这个": ["输入法", "问题", "时间", "时候", "怎么样", "可以", "方法", "东西", "模型", "很好用", "功能", "情况"],
    "那个": ["时候", "地方", "问题", "人", "东西", "怎么样", "可以"],
    "这种": ["情况", "问题", "方法", "感觉", "方式", "句子"],
    "输入法": ["怎么样", "很好用", "好用", "体验", "词库", "识别", "流畅", "不错"],
    "问题": ["不大", "是", "解决了", "吗", "呢", "在于", "怎么"],
    "时间": ["可以", "吗", "到了", "不够", "还早", "不早了", "来得及"],
    "时候": ["过来", "回来", "去", "见", "到", "开始", "可以"],
    "出来": ["吃饭", "玩", "看看", "了", "吧", "一下", "走走"],
    "过来": ["吃饭", "看看", "吧", "一下", "了", "吗", "拿"],
    "回去": ["吃饭", "休息", "睡觉", "吧", "了", "看看", "再说"],
    "回来": ["吃饭", "了", "吧", "再说", "看看", "休息"],
    "快速": ["输入", "补全", "响应", "识别", "打字", "查找", "上手", "发展", "解决"],
    "自动": ["补全", "识别", "纠错", "回复", "保存", "更新", "完成", "生成"],
    "补全": ["句子", "内容", "信息", "功能", "效果", "了"],
    "根据": ["语义", "上下文", "上文", "情况", "需要", "提示", "内容", "习惯"],
    "语义": ["来", "补全", "理解", "识别", "分析", "模型", "纠错"],
    "本地": ["模型", "的", "运行", "词库", "数据", "存储", "识别"],
    "模型": ["来", "自动", "识别", "推理", "效果", "升级", "大小"],
    "而且": ["是", "无延迟", "还", "没有", "很", "非常", "可以"],
    "同时": ["叠加", "进行", "支持", "发生", "还", "也"],
    "无延迟": ["的", "补全", "输入", "响应", "体验"],
    "不好意思": ["我", "刚刚", "刚才", "刚睡醒", "打扰", "让你", "来晚了", "忘记", "啊"],
    "刚睡醒": ["没看到", "不好意思", "有点", "还在"],
    "没看到": ["你", "消息", "你的", "不好意思", "刚刚"],
    "今天晚上": ["我们", "一起", "一起去", "去", "吃", "吃什么", "吃火锅", "有空", "见"],
    "一起": ["去", "吃", "吃饭", "吃火锅", "看看", "玩", "走", "吧"],
    "一起去": ["吃", "吃饭", "吃火锅", "看", "看看", "玩", "买", "逛街"],
    "想": ["要", "去", "买", "吃", "试试", "看看", "知道", "问", "你", "说"],
    "要": ["出去", "去", "买", "不", "不要", "什么", "是", "求"],
    "刚": ["到", "才", "好", "来", "去", "走", "出", "下", "上", "进", "回", "开始", "吃完", "下班"],
    "刚到": ["家", "地下", "楼下", "公司", "门口", "学校", "车站", "机场", "地铁", "这里", "那", "那里"],
    "我刚": ["到", "来", "下", "出", "进", "回", "去", "走", "吃完", "下班", "看到"],
    "到": ["了", "家", "地下", "楼下", "公司", "门口", "哪", "哪里", "时候", "底", "处", "达", "现在", "位"],
    "到哪": ["了", "里", "儿", "去", "呢", "啊", "呀"],
    "再": ["去", "去看看", "说", "说吧", "看看", "看", "想想", "试试", "问问", "找找", "来", "见", "次", "等", "买"],
    "再去": ["看看", "看", "买", "吃", "吃饭", "找", "问", "试试"],
    "先": ["去", "试试", "看看", "看", "吃", "吃饭", "走", "说", "回", "睡", "做"],
    "先去": ["吃饭", "看看", "看", "买", "买饭", "忙", "睡", "洗澡"],
    "还": ["没", "没有", "是", "有", "好", "要", "能", "可以", "行", "在"],
    "还没": ["吃", "吃饭", "到", "睡", "有", "来", "去", "下班", "开始", "好"],
    "都": ["不", "不知道", "没", "没有", "是", "可以", "好", "有", "在", "去", "知道"],
    "喝": ["水", "什么", "奶茶", "咖啡", "牛奶", "豆浆", "茶", "酒", "啤酒", "可乐", "果汁", "汤", "粥", "点水", "热水", "开水"],
    "想喝": ["水", "什么", "奶茶", "咖啡", "牛奶", "豆浆", "茶", "可乐", "果汁", "汤", "粥", "点水", "热水"],
    "要喝": ["水", "什么", "奶茶", "咖啡", "牛奶", "豆浆", "茶", "可乐", "果汁", "汤", "粥", "点水", "热水"],
    "去喝": ["水", "奶茶", "咖啡", "茶", "酒", "啤酒", "汤", "粥"],
    "坐": ["地铁", "高铁", "飞机", "公交", "车", "火车", "动车", "电梯", "下", "下来", "船", "出租车"],
    "地铁": ["去", "站", "上", "里", "口", "回来", "回去", "上班", "回家", "了", "吗"],
    "高铁": ["去", "站", "上", "回来", "回去", "到", "了", "吗"],
    "飞机": ["去", "上", "回来", "回去", "到", "了", "吗"],
    "坐地铁": ["去", "回来", "回去", "上班", "回家", "到", "吧", "吗"],
    "坐高铁": ["去", "回来", "回去", "到", "吧", "吗"],
    "坐飞机": ["去", "回来", "回去", "到", "吧", "吗"],
    "已": ["收到", "发", "发送", "完成", "付款", "到", "解决", "提交", "更新", "读"],
}


# Built-in high-frequency tech/mixed casing overrides, multi-word brands/phrases, contractions & everyday English rank boost
CURATED_ENGLISH_BOOST: dict[str, tuple[str, int]] = {
    # Apple Ecosystem & Devices
    "iphone": ("iPhone", -1650),
    "iphonese": ("iPhone SE", -1750),
    "iphonepro": ("iPhone Pro", -1750),
    "iphonepromax": ("iPhone Pro Max", -1750),
    "iphoneair": ("iPhone Air", -1780),
    "ipad": ("iPad", -1800),
    "ipadpro": ("iPad Pro", -1780),
    "ipadair": ("iPad Air", -1780),
    "ipadmini": ("iPad mini", -1780),
    "ios": ("iOS", -1600),
    "ipados": ("iPadOS", -1750),
    "macos": ("macOS", -1720),
    "watchos": ("watchOS", -1800),
    "tvos": ("tvOS", -1820),
    "visionos": ("visionOS", -1800),
    "macbook": ("MacBook", -1750),
    "macbookpro": ("MacBook Pro", -1700),
    "macbookair": ("MacBook Air", -1700),
    "macmini": ("Mac mini", -1780),
    "macstudio": ("Mac Studio", -1780),
    "macpro": ("Mac Pro", -1800),
    "imac": ("iMac", -1780),
    "airpods": ("AirPods", -1720),
    "airpodspro": ("AirPods Pro", -1700),
    "airpodsmax": ("AirPods Max", -1720),
    "airtag": ("AirTag", -1780),
    "airdrop": ("AirDrop", -1750),
    "airplay": ("AirPlay", -1780),
    "carplay": ("CarPlay", -1760),
    "apple": ("Apple", -1750),
    "applestore": ("Apple Store", -1680),
    "appstore": ("App Store", -1680),
    "macappstore": ("Mac App Store", -1740),
    "appleid": ("Apple ID", -1720),
    "applepay": ("Apple Pay", -1720),
    "applewatch": ("Apple Watch", -1720),
    "applemusic": ("Apple Music", -1740),
    "appletv": ("Apple TV", -1740),
    "applecare": ("AppleCare", -1760),
    "appleintelligence": ("Apple Intelligence", -1700),
    "icloud": ("iCloud", -1750),
    "facetime": ("FaceTime", -1750),
    "faceid": ("Face ID", -1720),
    "touchid": ("Touch ID", -1740),
    "imessage": ("iMessage", -1760),
    "homepod": ("HomePod", -1780),
    "homepodmini": ("HomePod mini", -1780),
    "visionpro": ("Vision Pro", -1760),
    "testflight": ("TestFlight", -1740),
    "appclips": ("App Clips", -1820),
    "liveactivities": ("Live Activities", -1820),
    "dynamicisland": ("Dynamic Island", -1800),
    "magasafe": ("MagSafe", -1820),
    "magsafe": ("MagSafe", -1780),
    "siri": ("Siri", -1820),
    "safari": ("Safari", -1800),
    "xcode": ("Xcode", -1780),
    "swift": ("Swift", -1820),
    "swiftui": ("SwiftUI", -1750),
    "uikit": ("UIKit", -1780),
    "appkit": ("AppKit", -1800),
    "coreml": ("Core ML", -1780),
    "lokey": ("Lokey", -1680),
    # AI, Developer, Cloud & Proxy Ecosystem
    "github": ("GitHub", -1680),
    "gitlab": ("GitLab", -1780),
    "claude": ("Claude", -1740),
    "claudecode": ("Claude Code", -1740),
    "gemini": ("Gemini", -1740),
    "chatgpt": ("ChatGPT", -1680),
    "openai": ("OpenAI", -1720),
    "deepseek": ("DeepSeek", -1720),
    "copilot": ("Copilot", -1780),
    "cursor": ("Cursor", -1820),
    "perplexity": ("Perplexity", -1800),
    "midjourney": ("Midjourney", -1800),
    "huggingface": ("Hugging Face", -1780),
    "ollama": ("Ollama", -1820),
    "surge": ("Surge", -1720),
    "shadowrocket": ("Shadowrocket", -1720),
    "quantumult": ("Quantumult", -1760),
    "quantumultx": ("Quantumult X", -1720),
    "stash": ("Stash", -1820),
    "singbox": ("sing-box", -1760),
    "clashverge": ("Clash Verge", -1760),
    "tailscale": ("Tailscale", -1760),
    "wireguard": ("WireGuard", -1760),
    "cloudflare": ("Cloudflare", -1760),
    "python": ("Python", -1800),
    "typescript": ("TypeScript", -1760),
    "javascript": ("JavaScript", -1760),
    "golang": ("Golang", -1820),
    "rust": ("Rust", -1850),
    "kotlin": ("Kotlin", -1820),
    "nodejs": ("Node.js", -1760),
    "nextjs": ("Next.js", -1780),
    "vuejs": ("Vue.js", -1800),
    "reactjs": ("React", -1800),
    "pytorch": ("PyTorch", -1780),
    "tensorflow": ("TensorFlow", -1780),
    "vscode": ("VS Code", -1720),
    "visualstudiocode": ("Visual Studio Code", -1720),
    "androidstudio": ("Android Studio", -1760),
    "docker": ("Docker", -1820),
    "kubernetes": ("Kubernetes", -1800),
    "linux": ("Linux", -1820),
    "ubuntu": ("Ubuntu", -1820),
    "android": ("Android", -1780),
    "windows": ("Windows", -1780),
    # Global Apps, Platforms & Hardware Standards
    "google": ("Google", -1720),
    "googlemaps": ("Google Maps", -1720),
    "googledrive": ("Google Drive", -1740),
    "googleplay": ("Google Play", -1740),
    "googlecloud": ("Google Cloud", -1760),
    "gmail": ("Gmail", -1750),
    "chrome": ("Chrome", -1780),
    "youtube": ("YouTube", -1700),
    "wechat": ("WeChat", -1700),
    "whatsapp": ("WhatsApp", -1720),
    "telegram": ("Telegram", -1720),
    "instagram": ("Instagram", -1740),
    "tiktok": ("TikTok", -1720),
    "twitter": ("Twitter", -1780),
    "facebook": ("Facebook", -1780),
    "linkedin": ("LinkedIn", -1780),
    "reddit": ("Reddit", -1780),
    "discord": ("Discord", -1760),
    "slack": ("Slack", -1820),
    "notion": ("Notion", -1780),
    "figma": ("Figma", -1780),
    "netflix": ("Netflix", -1760),
    "spotify": ("Spotify", -1760),
    "bilibili": ("Bilibili", -1780),
    "playstation": ("PlayStation", -1760),
    "nintendoswitch": ("Nintendo Switch", -1760),
    "steam": ("Steam", -1820),
    "microsoft": ("Microsoft", -1760),
    "amazon": ("Amazon", -1780),
    "tesla": ("Tesla", -1800),
    "nvidia": ("NVIDIA", -1760),
    "starbucks": ("Starbucks", -1780),
    "mcdonalds": ("McDonald's", -1780),
    "cocacola": ("Coca-Cola", -1780),
    "wifi": ("Wi-Fi", -1680),
    "bluetooth": ("Bluetooth", -1720),
    "typec": ("Type-C", -1720),
    "usbc": ("USB-C", -1720),
    "qrcode": ("QR Code", -1740),
    "simcard": ("SIM Card", -1760),
    "esim": ("eSIM", -1740),
    "fullaccess": ("Full Access", -1760),
    "darkmode": ("Dark Mode", -1780),
    # Tech Acronyms
    "api": ("API", -1750),
    "sdk": ("SDK", -1820),
    "ui": ("UI", -1800),
    "ux": ("UX", -1850),
    "ai": ("AI", -1650),
    "llm": ("LLM", -1780),
    "app": ("App", -1650),
    "bug": ("Bug", -1800),
    "ok": ("OK", -1600),
    "vip": ("VIP", -1780),
    "pdf": ("PDF", -1800),
    "ppt": ("PPT", -1800),
    "excel": ("Excel", -1820),
    "word": ("Word", -1920),
    "vpn": ("VPN", -1800),
    "dns": ("DNS", -1820),
    "ssh": ("SSH", -1820),
    "url": ("URL", -1820),
    "http": ("HTTP", -1850),
    "https": ("HTTPS", -1820),
    "json": ("JSON", -1820),
    "yaml": ("YAML", -1850),
    "sql": ("SQL", -1850),
    "gpu": ("GPU", -1800),
    "cpu": ("CPU", -1800),
    "ram": ("RAM", -1880),
    "ssd": ("SSD", -1850),
    "usb": ("USB", -1820),
    # English Contractions & Everyday Phrases / Cities
    "dont": ("don't", -1820),
    "cant": ("can't", -1850),
    "wont": ("won't", -1850),
    "didnt": ("didn't", -1820),
    "doesnt": ("doesn't", -1820),
    "isnt": ("isn't", -1820),
    "arent": ("aren't", -1840),
    "wasnt": ("wasn't", -1840),
    "werent": ("weren't", -1840),
    "havent": ("haven't", -1840),
    "hasnt": ("hasn't", -1840),
    "hadnt": ("hadn't", -1860),
    "wouldnt": ("wouldn't", -1820),
    "couldnt": ("couldn't", -1820),
    "shouldnt": ("shouldn't", -1820),
    "thats": ("that's", -1850),
    "whats": ("what's", -1850),
    "lets": ("let's", -1860),
    "theres": ("there's", -1850),
    "oclock": ("o'clock", -1860),
    "helloworld": ("Hello World", -1720),
    "goodmorning": ("good morning", -1740),
    "goodafternoon": ("good afternoon", -1760),
    "goodevening": ("good evening", -1760),
    "goodnight": ("good night", -1740),
    "thankyou": ("thank you", -1720),
    "excuseme": ("excuse me", -1760),
    "seeyou": ("see you", -1760),
    "ofcourse": ("of course", -1780),
    "newyork": ("New York", -1740),
    "hongkong": ("Hong Kong", -1740),
    "sanfrancisco": ("San Francisco", -1760),
    "losangeles": ("Los Angeles", -1760),
    "siliconvalley": ("Silicon Valley", -1780),
    "unitedstates": ("United States", -1760),
    "unitedkingdom": ("United Kingdom", -1780),
    # High-Frequency Everyday English Vocabulary (ensuring clean prefix completion & compound joining)
    "hello": ("hello", -1820),
    "world": ("world", -1880),
    "thanks": ("thanks", -1850),
    "please": ("please", -1880),
    "sorry": ("sorry", -1880),
    "welcome": ("welcome", -1880),
    "email": ("email", -1850),
    "store": ("store", -1900),
    "shop": ("shop", -1950),
    "music": ("music", -1900),
    "video": ("video", -1900),
    "photo": ("photo", -1920),
    "phone": ("phone", -1900),
    "message": ("message", -1900),
    "system": ("system", -1900),
    "update": ("update", -1900),
    "version": ("version", -1900),
    "network": ("network", -1900),
    "browser": ("browser", -1920),
    "keyboard": ("keyboard", -1880),
    "setting": ("setting", -1940),
    "settings": ("settings", -1880),
    "account": ("account", -1900),
    "password": ("password", -1880),
    "download": ("download", -1880),
    "upload": ("upload", -1920),
    "install": ("install", -1900),
    "search": ("search", -1900),
    "delete": ("delete", -1920),
    "cancel": ("cancel", -1920),
    "confirm": ("confirm", -1920),
    "english": ("English", -1840),
    "chinese": ("Chinese", -1860),
    "international": ("international", -1880),
    "information": ("information", -1880),
    "application": ("application", -1880),
    "development": ("development", -1900),
    "performance": ("performance", -1900),
    "experience": ("experience", -1900),
    "computer": ("computer", -1900),
    "internet": ("Internet", -1860),
    "software": ("software", -1900),
    "hardware": ("hardware", -1920),
    "database": ("database", -1900),
    "security": ("security", -1900),
    "privacy": ("privacy", -1900),
    "offline": ("offline", -1900),
    "online": ("online", -1900),
    "server": ("server", -1900),
    "client": ("client", -1920),
    "model": ("model", -1920),
    "memory": ("memory", -1920),
    "screen": ("screen", -1920),
    "camera": ("camera", -1920),
    "battery": ("battery", -1920),
    "coffee": ("coffee", -1900),
    "morning": ("morning", -1920),
    "tonight": ("tonight", -1920),
    "tomorrow": ("tomorrow", -1900),
    "weekend": ("weekend", -1920),
    "meeting": ("meeting", -1900),
    "office": ("office", -1920),
    "company": ("company", -1920),
    "project": ("project", -1900),
    "product": ("product", -1900),
    "problem": ("problem", -1900),
    "question": ("question", -1900),
    "answer": ("answer", -1920),
    "example": ("example", -1900),
    "support": ("support", -1900),
    "service": ("service", -1900),
    "feature": ("feature", -1920),
    "release": ("release", -1920),
    "package": ("package", -1940),
    "library": ("library", -1940),
    "default": ("default", -1920),
    "profile": ("profile", -1920),
    "button": ("button", -1940),
    "window": ("window", -1940),
    "folder": ("folder", -1940),
    "document": ("document", -1920),
    "address": ("address", -1920),
    "number": ("number", -1920),
    "friend": ("friend", -1920),
    "family": ("family", -1920),
    "school": ("school", -1920),
    "airport": ("airport", -1920),
    "station": ("station", -1920),
    "hotel": ("hotel", -1940),
    "ticket": ("ticket", -1920),
    "market": ("market", -1920),
    "payment": ("payment", -1920),
    "awesome": ("awesome", -1920),
    "perfect": ("perfect", -1900),
}


def align8(buf: bytearray) -> None:
    rem = len(buf) % 8
    if rem:
        buf.extend(b"\x00" * (8 - rem))


def parse_rime_dict(path: Path):
    in_body = False
    with path.open("r", encoding="utf-8", errors="ignore") as f:
        for raw in f:
            line = raw.rstrip("\r\n")
            if not in_body:
                if line.strip() == "...":
                    in_body = True
                continue
            if not line or line.startswith("#") or "\t" not in line:
                continue
            parts = line.split("\t")
            text = parts[0].strip()
            code = parts[1].strip() if len(parts) > 1 else ""
            if not text or not code:
                continue
            w_str = parts[2].strip() if len(parts) > 2 else ""
            weight = float(w_str) if w_str.replace(".", "", 1).isdigit() else 0.0
            yield text, code, weight


def pack_code_be(ascii_str: str) -> int:
    raw = ascii_str.encode("ascii")[:8]
    raw = raw + b"\x00" * (8 - len(raw))
    return struct.unpack(">Q", raw)[0]


class TrieBuilderNode:
    __slots__ = ("children", "words", "depth", "flat_index", "max_subtree_score")

    def __init__(self, depth: int):
        self.children: dict[int, TrieBuilderNode] = {}
        self.words: list[tuple[int, int, int]] = []  # (str_off, str_len, score_q8)
        self.depth = depth
        self.flat_index = 0
        self.max_subtree_score = -32000


def commit_choice_index(data_dir: Path):
    """Store quantized LNLM commit decisions alongside exact-reading lookups."""
    entries = defaultdict(dict)
    source = data_dir / "commit-deltas.tsv"
    for row in source.read_text(encoding="utf-8").splitlines():
        reading, *parameters = row.split("\t")
        assert len(parameters) == 8 and len(bytes.fromhex(parameters[6])) == 32
        if parameters[-1] == "-":
            parameters[-1] = ""
        entries["$" + reading]["|".join(parameters)] = 0
    return entries


def counted_object_phrases(frost_dir):
    """Recover short verb + classifier + noun requests from independent corpus evidence."""
    verbs = set("取拿领收借还订留占找买卖选换送递寄发倒泡喝端吃点穿脱洗带搬修装写读印填签拍骑坐开叫打切剥煮炒添加扔捡挑种摘捧插铺捎")
    classifiers = set("个张支本把双杯辆份块间条瓶碗盘封件台套场根盒袋口包片副壶桶首盏幅顶颗枚架卷盆")
    # Unsegmented corpus trigrams include fragments such as 一个做 and 一个在.
    # Only productive count nouns can fill this slot. Corpus evidence below
    # determines which classifiers and which verbs actually take each noun.
    nouns = set("座位票纸表图卡照券床桌椅凳笔书信画报伞刀锁钥匙鞋袜裤衣帽茶水酒汤奶饭粥面饼菜糖药花草树苗瓜果梨桃鱼虾肉蛋球灯车船房门窗店包袋盒瓶碗盘杯锅盆布线绳板砖钱章单号码词歌曲诗剧课班假字句名碟牌")
    # Transfer only between verbs used for the same kind of action. A raw
    # two-character count may span a word boundary, so by itself it cannot
    # justify combinations such as a cooking verb with a ticket.
    families = ("买取拿领借订", "留占订找", "找挑选换", "带拿取捎", "递送寄发",
                "喝泡倒端添", "吃点煮炒", "穿换脱洗", "写读印填签", "开骑坐叫",
                "装搬铺挂", "拍印发", "摘挑买", "种插摘")
    counted, observed = {}, defaultdict(dict)
    with (frost_dir / "others" / "3字统计结果.txt").open(encoding="utf-8-sig") as source:
        for line in source:
            term, _, raw = line.rstrip().partition("\t")
            if len(term) != 3 or term[1] not in classifiers or term[2] not in nouns or not raw.isdecimal():
                continue
            if term[0] == "一":
                counted[term[1:]] = int(raw)
            elif term[0] in verbs:
                observed[term[1:]][term[0]] = int(raw)

    with (frost_dir / "others" / "zhihu_deal_sort_merge.txt").open(encoding="utf-8-sig") as source:
        objects = defaultdict(dict)
        for line in source:
            term, _, raw = line.rstrip().partition("\t")
            if len(term) == 2 and term[0] in verbs and term[1] in nouns and raw.isdecimal():
                objects[term[1]][term[0]] = int(raw)

    for tail, examples in observed.items():
        # Require both a quantified noun and a verb taking that classified
        # noun. An unseen verb may transfer only if its own verb-object pair
        # is attested (an arbitrary Cartesian product produces nonsense).
        quantity = counted.get(tail, 0)
        if quantity < 25 or max(examples.values()) < 15:
            continue
        for verb, pair_count in objects[tail[1]].items():
            direct = examples.get(verb, 0)
            transfer = any(verb in family and any(examples.get(v, 0) >= 15 for v in family)
                           for family in families)
            if pair_count >= 5 and (direct >= 15 or transfer):
                support = min(800, math.sqrt(quantity * pair_count) + examples.get(verb, 0))
                yield verb + tail, support


def mixed_phrase_index(entries, frost_dir, norm_z, data_dir: Path):
    """Compile short multiword readings without expanding the interactive Viterbi beam."""
    readings = {}
    for (word, syllables), weight in entries.items():
        if len(word) == len(syllables) and weight >= 5:
            if word not in readings or readings[word][1] < weight:
                readings[word] = (syllables, weight)

    result = defaultdict(dict)

    def record(text, syllables, support, full=False):
        if not 3 <= len(syllables) <= 8:
            return
        keys = ["!" + syllables[0] + "".join(s[0] for s in syllables[1:])]
        # The spelled syllable may be last (e.g. two initials before a full noun).
        # A distinct namespace avoids collisions with first-syllable spellings.
        keys.append(":" + "".join(s[0] for s in syllables[:-1]) + syllables[-1])
        if full:
            keys.append("=" + "".join(syllables))
        value = text + "|" + " ".join(syllables)
        score = round(math.log10(support / norm_z) * 512)
        for key in keys:
            result[key][value] = max(result[key].get(value, -15000), score)

    # Include canonical dictionary phrases on both sides. The trie can
    # expand trailing initials, but it cannot recover omitted leading vowels.
    for word, (syllables, weight) in readings.items():
        if 3 <= len(syllables) <= 8 and weight >= 450:
            record(word, syllables, weight)

    # Compound paths observed in the pinned corpus, using the most frequent
    # dictionary segmentation and canonical reading for each component.
    with (frost_dir / "others" / "zhihu_deal_sort_merge.txt").open(encoding="utf-8-sig") as f:
        for row in f:
            text, sep, count = row.rstrip().partition("\t")
            if not sep or not count.isdecimal() or not 3 <= len(text) <= 8:
                continue
            weight = int(count)
            if weight < 220:
                continue
            if text in readings:
                record(text, readings[text][0], weight)
                continue
            splits = [(readings[text[:i]], readings[text[i:]]) for i in range(1, len(text))
                      if text[:i] in readings and text[i:] in readings]
            if splits:
                left, right = max(splits, key=lambda pair: pair[0][1] * pair[1][1])
                record(text, left[0] + right[0], weight)

    # Short spoken clauses often have no stand-alone dictionary entry. Infer
    # their readings from at most three attested words, with a lexical cost for
    # each boundary. Never infer a pronunciation from a single-character fallback
    # when the same spelling already has a multi-character dictionary reading.
    counts_file = data_dir / "mandarin-counts.tsv"
    # Reuse predicate tails across interchangeable subjects and time adverbs.
    # Only a multi-character predicate attested after a complete frame can
    # generalize. Keep the strongest distinct tails per family and retain the
    # original corpus score whenever the exact phrase is also attested.
    frames = [
        ("我想", "你想", "还想", "不想", "想要"),
        ("我在", "你在", "还在", "正在"),
        ("我们先", "你先", "我先", "先去", "先"),
        ("记得", "忘了", "别忘了", "一定要"),
        ("我来", "你来", "我去", "你去"),
        ("我会", "可以", "能不能", "要不要"),
        ("请你", "麻烦你", "帮我", "麻烦", "请"),
        ("已经", "刚刚", "刚才", "马上", "快要"),
        ("今天", "明天", "明早", "晚上", "下午", "周末"),
        ("早点", "赶快", "快点", "赶紧"),
    ]
    tails = [defaultdict(int) for _ in frames]
    for row in counts_file.read_text(encoding="utf-8").splitlines():
        term, raw_count, raw_complete = row.split("\t")
        count, complete = int(raw_count), int(raw_complete)
        for group, prefixes in enumerate(frames):
            for prefix in prefixes:
                if term.startswith(prefix) and 2 <= len(term) - len(prefix) <= 4:
                    predicate = term[len(prefix):]
                    if predicate in readings and predicate[0] in "走动回发说问买卖看吃喝带拿找出上进来下过做听帮玩学习写读练准备等睡收关开集合休息打接去寄":
                        tails[group][predicate] += count + 5 * complete
                    break
        if 2 <= len(term) <= 3 and count >= 5:
            # Local conversational support, queried only around a changed
            # character in an otherwise identical complete sentence reading.
            result["#" + term]["_"] = round(64 * math.log2(1 + count))
        if len(term) < 3:
            continue
        if term in readings:
            syllables = readings[term][0]
        else:
            paths = {0: (0.0, (), 0)}
            for end in range(1, len(term) + 1):
                for start in range(end):
                    hit = readings.get(term[start:end])
                    if not hit or start not in paths:
                        continue
                    score, prior, pieces = paths[start]
                    if pieces >= 3:
                        continue
                    cost = score + math.log(hit[1] / norm_z)
                    if end not in paths or cost > paths[end][0]:
                        paths[end] = (cost, prior + hit[0], pieces + 1)
            if len(term) not in paths:
                continue
            syllables = paths[len(term)][1]
        support = min(15000, count * 12 + complete * 350)
        record(term, syllables, support, full=complete > 0 and len(term) >= 3)
        # Attested predicates can also be used with a conversational subject.
        # Only extend complete clauses with an identified verb at their head.
        if complete and 2 < len(term) <= 5 and term[0] in "想要需要来去在能会有到等带买拿看听吃喝说回给做帮":
            for subject in ("我", "你", "他", "我们", "你们"):
                if subject in readings:
                    record(subject + term, readings[subject][0] + syllables, min(1400, support), full=False)

    # Productive chat constructions. Each component has a real dictionary
    # pronunciation; these are priors for mixed initials only.
    templates = [
        (("你", "我", "我们", "你们", "大家"), ("先回去", "先回家", "先吃饭", "先上去", "先下去", "先走", "等等", "再联系", "慢慢来")),
        (("一会", "等会", "待会", "晚些", "过会"), ("再来", "再说", "再聊", "就来", "再看", "再去")),
        (("到了", "到家", "下车", "下班"), ("记得联系", "说一声", "告诉我", "给我电话", "给我消息")),
        (("回来", "下班", "吃完", "到家", "明早", "等会"), ("再问", "再来", "再看", "再走", "再说", "再联系", "再出门", "再讨论")),
        (("今天", "明天", "周末", "下午", "上午", "晚上"), ("休息", "放假", "上课", "加班", "上班", "见面", "聚餐")),
        (("发个", "发一下", "给个"), ("位置", "定位", "地址", "链接", "通知", "消息", "红包")),
        (("记得", "别忘了", "出门要"), ("带伞", "带钥匙", "带水", "带钱包", "关窗", "锁门")),
        (("到家", "到了", "下班", "出门"), ("说一声", "告诉我", "联系我", "给我电话")),
        (("晚点", "有空", "明天", "回头"), ("再说", "再聊", "再看", "联系", "再问")),
        (("明早", "下午", "晚上", "改天", "明天"), ("见", "聊", "说")),
        (("出门", "吃饭", "买票", "回家", "上车", "到家", "下楼", "取件", "开会"), ("了", "了吗", "了没")),
        (("路上", "骑车", "开车", "出行"), ("小心", "注意安全", "慢一点")),
        (("几点", "马上", "何时", "准备", "打算", "记得"), ("出发", "回来", "回家", "上班", "下班", "开门", "关门", "吃饭", "出门", "集合")),
        (("吃", "订", "买", "选", "找", "修", "写", "办", "弄"), ("好了吗", "好了没", "好了嘛")),
        (("方便", "可以", "现在能"), ("接电话吗", "说话吗", "接听吗", "通话吗")),
        (("周末", "假期", "节日"), ("愉快", "快乐")),
        (("请", "麻烦"), ("稍等", "稍候", "留步", "让一下")),
        (("怎么", "应该怎么"), ("走", "办", "用", "去", "找")),
        (("不用", "不必"), ("谢", "客气", "担心", "着急", "麻烦")),
    ]
    particles = {"好了吗": ("hao", "le", "ma"), "好了没": ("hao", "le", "mei"),
                 "好了嘛": ("hao", "le", "ma"), "现在能": ("xian", "zai", "neng"),
                 "接电话吗": ("jie", "dian", "hua", "ma"), "说话吗": ("shuo", "hua", "ma"),
                 "接听吗": ("jie", "ting", "ma"), "通话吗": ("tong", "hua", "ma")}
    def component(word):
        if word in particles:
            return particles[word]
        if word in readings:
            return readings[word][0]
        splits = [(readings[word[:i]], readings[word[i:]]) for i in range(1, len(word))
                  if word[:i] in readings and word[i:] in readings]
        if not splits:
            return ()
        a, b = max(splits, key=lambda pair: pair[0][1] * pair[1][1])
        return a[0] + b[0]

    # Exact spelling only. Inferred constructions must not compete for mixed
    # initials or teach the neural model synthetic transitions.
    for term, support in counted_object_phrases(frost_dir):
        verb, classifier, noun = term
        # A standalone polyphone can have the wrong reading for its object
        # (还书 is huan shu). Prefer the attested two-character reading.
        pair = readings.get(verb + noun)
        if pair:
            first, last = pair[0]
        else:
            if verb in "还种切挑" or noun in "曲假卷":
                continue
            first, last = component(verb), component(noun)
            if len(first) != 1 or len(last) != 1:
                continue
            first, last = first[0], last[0]
        middle = component(classifier)
        if len(middle) == 1:
            syllables = (first, middle[0], last)
            bucket = result["=" + "".join(syllables)]
            value = term + "|" + " ".join(syllables)
            score = round(math.log10(support / norm_z) * 512)
            bucket[value] = max(bucket.get(value, -15000), score)

    for prefixes, family in zip(frames, tails):
        for tail, evidence in sorted(family.items(), key=lambda item: (-item[1], item[0]))[:80]:
            if evidence < 4:
                break
            for prefix in prefixes:
                head = component(prefix)
                if head:
                    support = min(900, 60 * math.sqrt(evidence))
                    record(prefix + tail, head + readings[tail][0], support, full=True)

    for lefts, rights in templates:
        for l in lefts:
            for r in rights:
                a = component(l)
                b = component(r)
                if a and b:
                    record(l + r, a + b, 450 if r.endswith("嘛") else 1800, full=True)
    return result


def conversational_endings():
    """Precise contextual readings that can recover an exact suffix lost to beam pruning."""
    cues = {}
    for word, reading, lefts in [
        ("发我", ("fa", "wo"), ("地址", "照片", "定位", "链接", "文件", "单号")),
        ("发你", ("fa", "ni"), ("晚点", "稍后", "待会", "随后", "马上")),
        ("号码", ("hao", "ma"), ("找一下", "查一下", "核对", "手机", "车牌", "电话号码")),
        ("取票", ("qu", "piao"), ("去车站", "帮忙", "先去", "要去")),
    ]:
        for left in lefts:
            cues["@" + left + "".join(reading)] = {word + "|" + " ".join(reading): 600}
    return cues


def short_homophone_cues(entries, frost_dir):
    """Count attested left contexts of competing two-character dictionary readings."""
    by_reading = defaultdict(dict)
    for (word, syllables), weight in entries.items():
        if len(word) == len(syllables) == 2 and weight >= 30:
            by_reading["".join(syllables)][word] = weight
    readings = defaultdict(list)
    for reading, words in by_reading.items():
        if len(words) > 1:
            for word in words:
                readings[word].append(reading)

    counts = defaultdict(dict)
    for name in ("3字统计结果.txt", "zhihu_deal_sort_merge.txt"):
        with (frost_dir / "others" / name).open(encoding="utf-8-sig") as source:
            for row in source:
                term, sep, count = row.rstrip().partition("\t")
                if not sep or not count.isdecimal() or not 3 <= len(term) <= 6:
                    continue
                support = int(count)
                if support < 12:
                    continue
                word = term[-2:]
                for reading in readings.get(word, ()):
                    key = (term[:-2], reading)
                    # Both source tables can report the same n-gram.
                    counts[key][word] = max(support, counts[key].get(word, 0))

    cues = {}
    for (left, reading), alternatives in counts.items():
        ranked = sorted(alternatives, key=lambda w: (-alternatives[w], w))
        best = ranked[0]
        count = alternatives[best]
        runner = alternatives[ranked[1]] if len(ranked) > 1 else 0
        # Monosyllabic and rare/non-Han left contexts need strong evidence to avoid bloat.
        if not left or len(left) > 3 or not all(0x4E00 <= ord(ch) < 0xA000 for ch in left):
            continue
        if count < (320 if len(left) == 1 else 65) or count < 5 * (runner + 5):
            continue
        strength = min(640, round(135 * math.log2((count + 5) / (runner + 5))))
        cues["~" + left + reading] = {best: strength}
    # Everyday constructions underrepresented in the formal-text frequency lists.
    # A cue still needs the exact dictionary reading and a competitive base score.
    for reading, word, contexts in [
        ("lianxi", "联系", ("回头", "随时", "取得", "保持", "与我", "与您")),
        ("lianxi", "练习", ("反复", "加强", "坚持", "刻苦")),
        ("jieni", "接你", ("去", "来", "顺路", "开车")),
        ("jieni", "解腻", ("清爽", "清口", "清淡")),
        ("fawo", "发我", ("地址", "定位", "照片", "链接", "单号", "文件")),
        ("fani", "发你", ("晚点", "随后", "待会", "稍后", "马上")),
        ("haoma", "号码", ("查一下", "找一下", "电话号码", "手机", "车牌", "电话")),
    ]:
        if word in by_reading[reading]:
            for left in contexts:
                cues["~" + left + reading] = {word: 560}
    return cues


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    repo_dir = Path(__file__).resolve().parent.parent
    parser = argparse.ArgumentParser(
        description="Compile gaboolic/rime-frost + bundled TSVs into a standalone .lokeypack (LKLF-v2 + LNLM-v2)."
    )
    parser.add_argument(
        "--rime-frost-dir",
        type=Path,
        default=repo_dir / "vendor" / "rime-frost",
        help="Path to rime-frost checkout directory (default: ./vendor/rime-frost)",
    )
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=repo_dir / "data",
        help="Path to directory containing mandarin-counts.tsv, target-deltas.tsv, commit-deltas.tsv (default: ./data)",
    )
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=repo_dir / "dist" / "rime-frost.lokeypack",
        help="Output .lokeypack binary path (default: ./dist/rime-frost.lokeypack)",
    )
    parser.add_argument(
        "--sha256-output",
        type=Path,
        default=None,
        help="Output .sha256 checksum path (default: <output>.sha256)",
    )
    parser.add_argument(
        "--no-sha256",
        action="store_true",
        help="Skip writing the companion .sha256 checksum file",
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        default=None,
        help="Optional path to write JSON build manifest (omitted by default)",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    frost_dir = args.rime_frost_dir
    data_dir = args.data_dir
    output_path = args.output
    sha256_path = None if args.no_sha256 else (
        args.sha256_output if args.sha256_output is not None else Path(f"{output_path}.sha256")
    )

    if not (frost_dir / "rime_frost.dict.yaml").exists():
        print(
            f"Error: rime-frost dictionary not found at {frost_dir}. "
            "Run ./scripts/fetch_rime_frost.sh first or pass --rime-frost-dir.",
            file=sys.stderr,
        )
        return 1

    for req_file in (
        "mandarin-counts.tsv",
        "target-deltas.tsv",
        "commit-deltas.tsv",
        "conversational-bigrams.tsv",
        "lnlm_backbone_v2.bin.zlib",
        "lnlm_backbone_chars.txt",
    ):
        data_file_path = data_dir / req_file
        if not data_file_path.is_file():
            print(f"Error: Missing required data file: {data_file_path}", file=sys.stderr)
            return 1

    print("==> [1/5] Scanning rime-frost Chinese dictionaries...")
    # 1A. Pre-load single-character empirical frequencies from `8105.dict.yaml` for character-cohesion backoff,
    #     plus `剔除词.txt` (upstream list of unsegmented corpus fragments like `人会`, `时要`, `地去`).
    char_freq: dict[str, float] = {}
    chars_8105: set[str] = set()
    p_8105_pre = frost_dir / "cn_dicts" / "8105.dict.yaml"
    if p_8105_pre.exists():
        for c_txt, _, c_w in parse_rime_dict(p_8105_pre):
            if len(c_txt) == 1:
                chars_8105.add(c_txt)
                if c_w > char_freq.get(c_txt, 0.0):
                    char_freq[c_txt] = c_w

    target_delta_words: set[str] = set()
    td_path = data_dir / "target-deltas.tsv"
    if td_path.exists():
        for td_raw in td_path.read_text(encoding="utf-8").splitlines():
            if "\t" in td_raw:
                target_delta_words.add(td_raw.split("\t", 1)[0])

    protected_words: set[str] = set(target_delta_words)
    protected_words.update(CURATED_CONVERSATIONAL_ASSOC.keys())
    for conts in CURATED_CONVERSATIONAL_ASSOC.values():
        protected_words.update(conts)

    excluded_fragments: set[str] = set()
    excl_path = frost_dir / "others" / "剔除词.txt"
    if excl_path.exists():
        for raw in excl_path.read_text(encoding="utf-8", errors="ignore").splitlines():
            w_ex = raw.strip()
            if len(w_ex) >= 2:
                excluded_fragments.add(w_ex)

    # 1B. Pre-load multi-source empirical word frequencies (`zhihu_deal_sort_merge.txt`, `知频.txt`, `2字词频表.txt`, `3字统计结果.txt`)
    #     plus upstream `降频词.txt`, `增频词.txt`, and `错字词.txt` so unweighted (`weight == 0`) entries in
    #     `corrections.dict.yaml` / `others.dict.yaml` / `exthot.dict.yaml` / `computer.dict.yaml` receive true
    #     corpus weights and standard orthography systematically outranks common misspellings.
    empirical_word_weights: dict[str, float] = {}
    for emp_rel, emp_scale in [
        ("others/zhihu_deal_sort_merge.txt", 1.0),
        ("others/知频.txt", 1.0),
        ("others/3字统计结果.txt", 0.85),
    ]:
        emp_path = frost_dir / emp_rel
        if not emp_path.exists():
            continue
        with emp_path.open("r", encoding="utf-8", errors="ignore") as ef:
            for raw in ef:
                if "\t" not in raw:
                    continue
                ew_txt, ew_s = raw.lstrip("\ufeff").rstrip("\r\n").split("\t", 1)
                ew_num = ew_s.split()[0] if ew_s else ""
                if 2 <= len(ew_txt) <= 6 and ew_num.isdigit():
                    wv = float(ew_num) * emp_scale
                    if wv > empirical_word_weights.get(ew_txt, 0.0):
                        empirical_word_weights[ew_txt] = wv

    reduce_freq_entries: set[str] = set()
    reduce_path = frost_dir / "others" / "降频词.txt"
    if reduce_path.exists():
        for raw in reduce_path.read_text(encoding="utf-8", errors="ignore").splitlines():
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            reduce_freq_entries.add(line)
            parts = line.split()
            if len(parts) > 1:
                reduce_freq_entries.add(parts[0] + "\t" + " ".join(parts[1:]))

    add_freq_entries: dict[str, float] = {}
    add_path = frost_dir / "others" / "增频词.txt"
    if add_path.exists():
        for raw in add_path.read_text(encoding="utf-8", errors="ignore").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "\t" not in line:
                continue
            w_txt, f_str = line.split("\t", 1)
            if f_str.strip().isdigit():
                add_freq_entries[w_txt.strip()] = float(f_str.strip())
    for cw, boost_w in [
        ("爱心", 2600.0),
        ("比心", 2200.0),
        ("捂脸", 2200.0),
        ("摸鱼", 2200.0),
        ("吃瓜", 2200.0),
        ("早安", 2200.0),
        ("晚安", 2200.0),
    ]:
        add_freq_entries[cw] = max(add_freq_entries.get(cw, 0.0), boost_w)

    typo_to_correct: dict[str, str] = {}
    cuozi_path = frost_dir / "others" / "错字词.txt"
    if cuozi_path.exists():
        for raw in cuozi_path.read_text(encoding="utf-8", errors="ignore").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "\t" not in line:
                continue
            wrong_w, right_w = line.split("\t", 1)
            wrong_w, right_w = wrong_w.strip(), right_w.strip()
            if len(wrong_w) >= 2 and len(right_w) >= 2 and wrong_w != right_w:
                typo_to_correct[wrong_w] = right_w

    # Map: (text, tuple(syllable_strs)) -> accumulated_weight
    cn_entries: dict[tuple[str, tuple[str, ...]], float] = {}
    syllable_set: set[str] = set()

    tables_to_load: list[tuple[Path, float, bool]] = []
    for rel, default_zero_w in CORE_CN_TABLES:
        p = frost_dir / rel
        if p.exists():
            tables_to_load.append((p, default_zero_w, True))

    cell_dir = frost_dir / "cn_dicts_cell"
    if cell_dir.exists():
        for p in sorted(cell_dir.glob("*.dict.yaml")):
            if p.name in CELL_TABLES_ALLOW_ZERO:
                tables_to_load.append((p, 12.0, True))
            elif p.name in CELL_TABLES_POSITIVE_ONLY:
                tables_to_load.append((p, 0.0, False))

    for path, zero_fallback, allow_zero in tables_to_load:
        is_41448 = path.name == "41448.dict.yaml"
        is_composite = path.name == "composite.dict.yaml"
        is_ext = path.name == "ext.dict.yaml"
        is_priority_table = path.name in {
            "8105.dict.yaml",
            "corrections.dict.yaml",
            "others.dict.yaml",
            "computer.dict.yaml",
            "exthot.dict.yaml",
            "idiom.dict.yaml",
        }
        for text, code, weight in parse_rime_dict(path):
            if is_41448 and len(text) > 1:
                continue
            if len(text) >= 2 and text in excluded_fragments:
                continue
            if is_composite and len(text) > 5:
                continue
            if len(text) > 6 and not (is_priority_table and len(text) <= 8):
                continue

            syls = tuple(code.lower().replace("ü", "v").split())
            if not syls or len(syls) > 8:
                continue

            is_luna = path.name == "luna.dict.yaml"
            is_protected = (
                text in protected_words
                or text in typo_to_correct.values()
                or path.name in ("8105.dict.yaml", "corrections.dict.yaml", "others.dict.yaml")
            )

            if weight <= 0.0:
                if is_luna:
                    # Mildly recover clean 2-char modern colloquial words backed by strong corpus evidence.
                    emp_l = empirical_word_weights.get(text, 0.0)
                    if not (
                        len(text) == 2
                        and len(syls) == 2
                        and all(c in chars_8105 for c in text)
                        and not any(c in "的得地了着过" for c in text)
                        and emp_l >= 150.0
                    ):
                        continue
                    eff_w = min(600.0, emp_l * 0.35)
                elif not allow_zero:
                    continue
                elif path.name == "idiom.dict.yaml" and text not in empirical_word_weights and not is_protected:
                    continue
                elif path.name == "corrections.dict.yaml" and len(text) >= 2:
                    # Curated phonetic/orthographic tolerance entries (`yingai -> 应该`, `cengjin -> 曾经`, `annai -> 按捺`,
                    # `youhuijuan -> 优惠券`, `liage -> 两个`, `fazhi -> 阈值`): inherit strong empirical backing so they
                    # beat fragmented 1-char + 1-char splits while staying below higher-frequency exact words (`法治`).
                    emp_base = empirical_word_weights.get(text, 900.0)
                    eff_w = max(960.0, min(2600.0, emp_base * 0.42))
                elif len(text) >= 2 and len(syls) == len(text) and not is_41448:
                    if text in empirical_word_weights:
                        eff_w = max(zero_fallback, min(2400.0, empirical_word_weights[text] * 2.4))
                    elif is_priority_table and path.name != "8105.dict.yaml":
                        # General character-cohesion geometric mean backoff for unweighted priority-table words
                        gmean = math.exp(
                            sum(math.log(max(char_freq.get(c, 50.0), 10.0)) for c in text) / len(text)
                        )
                        eff_w = max(zero_fallback, min(260.0, max(65.0, gmean * 0.0035)))
                    else:
                        eff_w = zero_fallback
                else:
                    eff_w = zero_fallback
            else:
                eff_w = weight

            if is_41448 and text not in chars_8105:
                # Apply equivalent -1200 Q8 penalty (`0.0045` weight scale -> log10 * 512 ≈ -1202)
                # so obscure non-8105 characters do not hijack noisy syllable lattice paths.
                eff_w *= 0.0045

            if len(text) >= 2 and (text in reduce_freq_entries or f"{text}\t{' '.join(syls)}" in reduce_freq_entries):
                eff_w = max(1.0, eff_w * 0.12)
            if text in add_freq_entries and path.name in ("base.dict.yaml", "ext.dict.yaml", "others.dict.yaml"):
                eff_w += add_freq_entries[text]

            emp_boost = empirical_word_weights.get(text, 0.0)
            if not is_protected and not is_41448:
                if len(syls) >= 3 and eff_w < 2.0 and emp_boost < 35.0:
                    continue
                if is_composite and emp_boost < 35.0:
                    if len(syls) >= 5 and eff_w < 120.0:
                        continue
                    if len(syls) == 4 and eff_w < 45.0:
                        continue
                    if len(syls) == 3 and eff_w < 25.0:
                        continue
                    if len(syls) == 2 and eff_w < 15.0:
                        continue
                elif not is_priority_table and emp_boost < 35.0:
                    if len(syls) >= 5 and eff_w < 60.0:
                        continue
                    if len(syls) == 4 and eff_w < 5.0:
                        continue
                    if len(syls) == 3 and eff_w < 8.0:
                        continue
                    if len(syls) == 2 and eff_w < 5.0:
                        continue

            if not all(SYLLABLE_RE.match(s) and s not in INVALID_NON_MANDARIN_SYLLABLES for s in syls):
                continue

            # Filter unsegmented forum-scraped `去那*` / `在那*` typos where interrogative `哪` was mistyped as `那`
            # (`去那吃饭`, `去那干嘛`, `我去那`, `你们去那`, `在那吃饭`, `在那干嘛呢`), while keeping valid demonstratives
            # (`去那里`, `去那边`, `去那儿`, `去那个`, `过去那么多年`, `坐在那`, `就在那`, `在那个`, `在那之后`).
            if "去那" in text:
                idx_qn = text.find("去那")
                after_na = text[idx_qn + 2 :]
                valid_na_follows = (
                    "里", "边", "儿", "个", "些", "么", "样", "时", "年", "天", "日",
                    "刻", "场", "次", "段", "家", "块", "条", "套", "位", "种", "一",
                    "之", "方", "上", "瞬", "遥", "头",
                )
                if not after_na or not after_na.startswith(valid_na_follows):
                    continue
            if any(bad in text for bad in ("在那吃饭", "在那干嘛", "在那干啥", "在那干什么", "在那上呢", "做地铁", "做高铁", "做飞机")):
                continue

            key = (text, syls)
            if eff_w > cn_entries.get(key, 0.0):
                cn_entries[key] = eff_w
            for s in syls:
                syllable_set.add(s)

    # 1B-post. Apply `others/错字词.txt` orthographic transfer (`模版 -> 模板`, `记帐 -> 记账`, `转帐 -> 转账`,
    #          `手动档 -> 手动挡`, `优惠卷 -> 优惠券`, `按耐不住 -> 按捺不住`, `曾今 -> 曾经`, `魔蝎座 -> 摩羯座`):
    #          transfer typo weight to the standard orthographic form under the same Pinyin and demote the typo entry.
    for (w_txt, w_syls), w_val in list(cn_entries.items()):
        right_txt = typo_to_correct.get(w_txt)
        if right_txt is not None:
            right_key = (right_txt, w_syls)
            if right_key in cn_entries:
                cn_entries[right_key] = max(cn_entries[right_key], w_val * 1.15)
            elif len(right_txt) == len(w_syls):
                cn_entries[right_key] = max(960.0, w_val)
            cn_entries[(w_txt, w_syls)] = min(w_val * 0.12, 120.0)

    # 1C. General `粘 (zhan/nian) <-> 黏 (nian)` orthographic & polyphonic equivalence across all multi-character words:
    #     In `rime-frost`, `base.dict.yaml` annotates `粘*` words (`粘连`, `粘贴`, `粘附`, `粘接`, `粘滞`) only under `zhan`
    #     and `黏*` words (`黏膜`, `黏稠`, `黏液`, `黏性`, `黏度`) only under `nian`. Cross-registering both orthographic
    #     surfaces (`黏`/`粘`) and readings (`nian`/`zhan`) systematically covers all 180+ `粘/黏` compounds from the root.
    zhan_nian_snapshot = [
        (txt, syls, w)
        for (txt, syls), w in cn_entries.items()
        if len(txt) >= 2 and len(txt) == len(syls) and ("粘" in txt or "黏" in txt)
    ]
    for txt, syls, w in zhan_nian_snapshot:
        idxs = [i for i, ch in enumerate(txt) if ch in ("粘", "黏") and syls[i] in ("zhan", "nian")]
        if not idxs:
            continue
        nian_txt = txt.replace("粘", "黏")
        zhan_txt = txt.replace("黏", "粘")
        nian_syls = tuple("nian" if i in idxs else s for i, s in enumerate(syls))
        zhan_syls = tuple("zhan" if i in idxs else s for i, s in enumerate(syls))
        for cand_key, cand_w in [
            ((nian_txt, nian_syls), w),
            ((zhan_txt, nian_syls), w * 0.95),
            ((zhan_txt, zhan_syls), w),
            ((nian_txt, zhan_syls), w * 0.90),
        ]:
            if cand_w > cn_entries.get(cand_key, 0.0):
                cn_entries[cand_key] = cand_w

    # Demote news-corpus bound syntactic fragments (`...时的`, `可以把...`) so they remain #2 candidates
    # instead of hijacking standalone conversational replies (`是的`, `可以吧`).
    for fragment_key, cap_w in [
        (("时的", ("shi", "de")), 1200.0),
        (("可以把", ("ke", "yi", "ba")), 1200.0),
    ]:
        if fragment_key in cn_entries and cn_entries[fragment_key] > cap_w:
            cn_entries[fragment_key] = cap_w

    # Ensure primary municipality names & core spoken replies omitted from rime-frost's written corpus
    # rank naturally in mobile Chinese typing (matching native iOS Pinyin defaults).
    for boosted_key, min_w in [
        (("北京", ("bei", "jing")), 36000.0),
        (("上海", ("shang", "hai")), 36000.0),
        (("登录", ("deng", "lu")), 7200.0),
        (("是的", ("shi", "de")), 12000.0),
        (("是吗", ("shi", "ma")), 6500.0),
        (("嗯呢", ("en", "ne")), 2200.0),
        (("没事的", ("mei", "shi", "de")), 4800.0),
        (("可以吧", ("ke", "yi", "ba")), 5200.0),
        (("去哪", ("qu", "na")), 8500.0),
        (("在哪", ("zai", "na")), 9000.0),
        (("到哪", ("dao", "na")), 4200.0),
        (("从哪", ("cong", "na")), 3200.0),
        (("去哪啊", ("qu", "na", "a")), 1600.0),
        (("去哪呀", ("qu", "na", "ya")), 1200.0),
        (("在哪啊", ("zai", "na", "a")), 1600.0),
        (("在哪呢", ("zai", "na", "ne")), 2200.0),
        (("好的啊", ("hao", "de", "a")), 1800.0),
        (("好的呀", ("hao", "de", "ya")), 1800.0),
        (("一会儿见", ("yi", "hui", "er", "jian")), 1800.0),
        (("回头见", ("hui", "tou", "jian")), 1600.0),
        (("一会", ("yi", "hui")), 11000.0),
        (("买饭", ("mai", "fan")), 3800.0),
        (("带饭", ("dai", "fan")), 2600.0),
        (("热饭", ("re", "fan")), 1800.0),
        (("开饭", ("kai", "fan")), 2400.0),
        (("买菜", ("mai", "cai")), 4200.0),
        (("买水", ("mai", "shui")), 2200.0),
        (("买药", ("mai", "yao")), 2400.0),
        (("买东西", ("mai", "dong", "xi")), 3600.0),
        (("点外卖", ("dian", "wai", "mai")), 3200.0),
        (("拿外卖", ("na", "wai", "mai")), 2600.0),
        (("取外卖", ("qu", "wai", "mai")), 2400.0),
        (("拿快递", ("na", "kuai", "di")), 2800.0),
        (("取快递", ("qu", "kuai", "di")), 2800.0),
        (("喝什么", ("he", "shen", "me")), 3600.0),
        (("喝奶茶", ("he", "nai", "cha")), 2400.0),
        (("喝咖啡", ("he", "ka", "fei")), 3200.0),
        (("喝豆浆", ("he", "dou", "jiang")), 1800.0),
        (("喝牛奶", ("he", "niu", "nai")), 2200.0),
        (("喝可乐", ("he", "ke", "le")), 1800.0),
        (("喝果汁", ("he", "guo", "zhi")), 1600.0),
        (("喝热水", ("he", "re", "shui")), 2000.0),
        (("喝开水", ("he", "kai", "shui")), 1600.0),
        (("喝点水", ("he", "dian", "shui")), 2000.0),
        (("喝杯水", ("he", "bei", "shui")), 1800.0),
        (("坐地铁", ("zuo", "di", "tie")), 3600.0),
        (("坐高铁", ("zuo", "gao", "tie")), 3200.0),
        (("坐飞机", ("zuo", "fei", "ji")), 3200.0),
        (("坐公交", ("zuo", "gong", "jiao")), 2400.0),
        (("坐车", ("zuo", "che")), 3600.0),
        (("坐电梯", ("zuo", "dian", "ti")), 2200.0),
        (("再想想", ("zai", "xiang", "xiang")), 3200.0),
        (("再试试", ("zai", "shi", "shi")), 2800.0),
        (("再看看", ("zai", "kan", "kan")), 5200.0),
        (("再问问", ("zai", "wen", "wen")), 2400.0),
        (("再找找", ("zai", "zhao", "zhao")), 2200.0),
        (("再说吧", ("zai", "shuo", "ba")), 3200.0),
        (("到哪了", ("dao", "na", "le")), 2800.0),
        (("吃完了", ("chi", "wan", "le")), 2800.0),
        (("忙完了", ("mang", "wan", "le")), 2600.0),
        (("看完了", ("kan", "wan", "le")), 2600.0),
        (("写完了", ("xie", "wan", "le")), 2400.0),
        (("做完了", ("zuo", "wan", "le")), 2600.0),
        (("已收到", ("yi", "shou", "dao")), 2800.0),
        (("已完成", ("yi", "wan", "cheng")), 2800.0),
        (("已付款", ("yi", "fu", "kuan")), 2400.0),
        (("快速输入", ("kuai", "su", "shu", "ru")), 3600.0),
        (("输入法", ("shu", "ru", "fa")), 3600.0),
        (("二维码", ("er", "wei", "ma")), 3200.0),
        (("验证码", ("yan", "zheng", "ma")), 3400.0),
        (("表情包", ("biao", "qing", "bao")), 3200.0),
        (("朋友圈", ("peng", "you", "quan")), 3800.0),
        (("小程序", ("xiao", "cheng", "xu")), 3200.0),
        (("充电宝", ("chong", "dian", "bao")), 2800.0),
        (("数据线", ("shu", "ju", "xian")), 2600.0),
        (("自动补全", ("zi", "dong", "bu", "quan")), 3400.0),
        (("补全", ("bu", "quan")), 4800.0),
        (("根据语义", ("gen", "ju", "yu", "yi")), 2600.0),
        (("无延迟", ("wu", "yan", "chi")), 2800.0),
        (("零延迟", ("ling", "yan", "chi")), 2200.0),
        (("本地模型", ("ben", "di", "mo", "xing")), 2800.0),
        (("长句", ("chang", "ju")), 2600.0),
        (("漏敲", ("lou", "qiao")), 1800.0),
        (("错敲", ("cuo", "qiao")), 1800.0),
        (("不好意思", ("bu", "hao", "yi", "si")), 9600.0),
        (("今天晚上", ("jin", "tian", "wan", "shang")), 6800.0),
        (("昨天晚上", ("zuo", "tian", "wan", "shang")), 5200.0),
        (("明天早上", ("ming", "tian", "zao", "shang")), 4800.0),
        (("明天下午", ("ming", "tian", "xia", "wu")), 4800.0),
        (("今天下午", ("jin", "tian", "xia", "wu")), 4800.0),
        (("吃火锅", ("chi", "huo", "guo")), 4200.0),
        (("吃烧烤", ("chi", "shao", "kao")), 3200.0),
        (("很好用", ("hen", "hao", "yong")), 3600.0),
        (("刚睡醒", ("gang", "shui", "xing")), 2800.0),
        (("没看到", ("mei", "kan", "dao")), 5200.0),
        (("发消息", ("fa", "xiao", "xi")), 3800.0),
        (("回消息", ("hui", "xiao", "xi")), 3200.0),
        (("打字太快", ("da", "zi", "tai", "kuai")), 2000.0),
    ]:
        if boosted_key in cn_entries:
            cn_entries[boosted_key] = max(cn_entries[boosted_key], min_w)
        else:
            cn_entries[boosted_key] = min_w
            for s in boosted_key[1]:
                syllable_set.add(s)

    total_mass = sum(cn_entries.values())
    norm_z = 2.28e8
    print(f"    Loaded {len(cn_entries):,} unique (word, reading) entries across {len(syllable_set)} syllables (mass={total_mass:,.0f}, Z={norm_z:,.0f}).")

    # Assign 1-based syllable IDs in alphabetical order.
    sorted_syllables = sorted(syllable_set)
    syl_to_id = {s: i + 1 for i, s in enumerate(sorted_syllables)}

    print("==> [2/5] Scanning English & CN-EN mixed-input dictionaries...")
    # Map: lower_key -> (display_text, score_q8)
    en_map: dict[str, tuple[str, int]] = {}

    cn_en_path = frost_dir / "en_dicts" / "cn_en.txt"
    if cn_en_path.exists():
        for raw in cn_en_path.read_text(encoding="utf-8", errors="ignore").splitlines():
            if not raw or raw.startswith("#") or "\t" not in raw:
                continue
            disp, code = raw.split("\t", 1)
            disp, code = disp.strip(), code.strip().lower()
            if 2 <= len(code) <= 16 and code.isalpha():
                en_map[code] = (disp, -2050)

    for idx_file, en_rel in enumerate(["en_dicts/en.dict.yaml", "en_dicts/en_ext.dict.yaml"]):
        p = frost_dir / en_rel
        if not p.exists():
            continue
        rank = 0
        for disp, code, _ in parse_rime_dict(p):
            key = code.strip().lower()
            if not (2 <= len(key) <= 24 and key.isalpha()):
                continue
            is_single_token = bool(ASCII_WORD_RE.match(disp))
            is_exact_phrase = (
                not is_single_token
                and bool(ASCII_PHRASE_RE.match(disp))
                and NON_ALNUM_RE.sub("", disp.lower()) == key
            )
            if not (is_single_token or is_exact_phrase):
                continue
            # Avoid non-1:1 shorthand expansions (`AirPods Max -> AirPods`, `iPhone 15 -> iPhone`) overwriting exact root words
            if is_single_token and NON_ALNUM_RE.sub("", disp.lower()) != key and key in en_map:
                continue
            rank += 1
            # Preserve proper-case & spaced phrase forms (`Apple Store`, `MacBook Pro`, `Face ID`, `Google Chrome`)
            if is_exact_phrase:
                base_score = -2120 if idx_file == 1 else -2180
            else:
                base_score = -2250 if len(key) >= 4 else -2450
                if idx_file == 1:
                    base_score = -2180
            prev = en_map.get(key)
            if prev is None or base_score > prev[1]:
                en_map[key] = (disp, base_score)

    for k, val in CURATED_ENGLISH_BOOST.items():
        en_map[k] = val

    print(f"    Loaded {len(en_map):,} English / CN-EN mixed entries.")

    print("==> [3/5] Building deduplicated UTF-8 string pool, Syllable Trie & Jianpin index...")
    string_pool = bytearray()
    str_offsets: dict[str, tuple[int, int]] = {}

    def intern_str(s: str) -> tuple[int, int]:
        hit = str_offsets.get(s)
        if hit is not None:
            return hit
        b = s.encode("utf-8")
        off = len(string_pool)
        string_pool.extend(b)
        res = (off, len(b))
        str_offsets[s] = res
        return res

    root = TrieBuilderNode(0)
    jianpin_candidates: list[tuple[int, int, int, int]] = []  # (code_be, s_off, s_len, score_q8)

    for (text, syls), weight in cn_entries.items():
        log_p = math.log10(max(weight, 1e-4) / norm_z)
        # Scale by 512 (Q9-like precision in Int16): typical range [-4800, -700]
        score_q8 = max(-15000, min(-100, int(round(log_p * 512.0))))
        s_off, s_len = intern_str(text)

        node = root
        for s in syls:
            sid = syl_to_id[s]
            child = node.children.get(sid)
            if child is None:
                child = TrieBuilderNode(node.depth + 1)
                node.children[sid] = child
            node = child
        node.words.append((s_off, s_len, score_q8))

        # Index 2..8 syllable phrases with solid weight into Jianpin acronym index
        if (
            (2 <= len(syls) <= 5 and weight >= 120.0)
            or (6 <= len(syls) <= 8 and weight >= 300.0)
            or (2 <= len(syls) <= 8 and text in protected_words)
        ):
            acronym = "".join(s[0] for s in syls)
            code_be = pack_code_be(acronym)
            jianpin_candidates.append((code_be, s_off, s_len, score_q8))

    # Cap per-node word list (keep top 64 for single syllables, top 24 for multi-syllables) & compute subtree bounds.
    flat_nodes: list[TrieBuilderNode] = []

    def finalize_dfs(node: TrieBuilderNode) -> int:
        node.flat_index = len(flat_nodes)
        flat_nodes.append(node)
        if node.words:
            node.words.sort(key=lambda x: x[2], reverse=True)
            cap = 96 if node.depth == 1 else 28
            if len(node.words) > cap:
                del node.words[cap:]
            best = node.words[0][2]
        else:
            best = -32000

        for sid in sorted(node.children.keys()):
            child_best = finalize_dfs(node.children[sid])
            if child_best > best:
                best = child_best
        node.max_subtree_score = best
        return best

    finalize_dfs(root)

    # Prune Jianpin bucket collisions to top 8 per acronym so binary stays lean and instant.
    jianpin_by_key: dict[int, list[tuple[int, int, int, int]]] = defaultdict(list)
    for item in jianpin_candidates:
        jianpin_by_key[item[0]].append(item)

    final_jianpin: list[tuple[int, int, int, int]] = []
    for code_be in sorted(jianpin_by_key.keys()):
        bucket = jianpin_by_key[code_be]
        bucket.sort(key=lambda x: x[3], reverse=True)
        seen_off = set()
        kept = 0
        # Keep top 16 for high-collision 2-letter acronyms (e.g. `sb` -> 随便/设备/上班/识别), top 8 for 3+ letter acronyms
        is_two_letter = ((code_be >> 40) & 0xFF) == 0
        bucket_cap = 16 if is_two_letter else 8
        for rec in bucket:
            if rec[1] in seen_off:
                continue
            seen_off.add(rec[1])
            final_jianpin.append(rec)
            kept += 1
            if kept >= bucket_cap:
                break

    # Prepare sorted English table
    final_english: list[tuple[int, int, int, int, int]] = []
    for lower_key in sorted(en_map.keys()):
        disp, score_q8 = en_map[lower_key]
        l_off, l_len = intern_str(lower_key)
        d_off, d_len = intern_str(disp)
        final_english.append((l_off, d_off, l_len, d_len, score_q8))

    print("==> [3.5/5] Building Chinese next-word association & bigram index...")
    simp_chars: set[str] = set()
    p_8105 = frost_dir / "cn_dicts" / "8105.dict.yaml"
    if p_8105.exists():
        for txt, _, _ in parse_rime_dict(p_8105):
            if len(txt) == 1:
                simp_chars.add(txt)

    word_max_w: dict[str, float] = {}
    for (txt, _), w in cn_entries.items():
        if w > word_max_w.get(txt, 0.0):
            word_max_w[txt] = w

    ranked_words = sorted(
        ((txt, w) for txt, w in word_max_w.items() if 1 <= len(txt) <= 3 and all(c in simp_chars for c in txt)),
        key=lambda x: x[1],
        reverse=True,
    )
    top_prefixes: set[str] = {txt for txt, _ in ranked_words[:18000]}
    top_prefixes.update(CURATED_CONVERSATIONAL_ASSOC.keys())

    # assoc_map[prefix][continuation] = best_score_int16
    assoc_map: dict[str, dict[str, int]] = defaultdict(dict)

    def record_assoc(pref: str, cont: str, raw_weight: float) -> None:
        if not cont or len(cont) > 3 or cont == pref:
            return
        if len(pref) == 1 and len(cont) == 1 and raw_weight < 45.0:
            return
        # Filter noisy "monosyllabic verb + 的" 1+1 bigrams (`跑的`, `吃的`, `走的`, ...)
        # so `+bgBonus` does not defeat `跑得快` / `吃得好` (curated entries remain exempt).
        if pref in NOISY_DE_VERB_PREFIXES and cont == "的":
            return
        if not all(c in simp_chars for c in cont):
            return
        # Ensure multi-char continuation is a real dictionary word (avoids awkward half-word splits)
        if len(cont) >= 2 and word_max_w.get(cont, 0.0) < 5.0:
            return
        sc = max(10, min(2200, int(round(math.log10(max(raw_weight, 1.0) + 1.0) * 320.0))))
        cur = assoc_map[pref].get(cont, 0)
        if sc > cur:
            assoc_map[pref][cont] = sc

    for (txt, _), w in cn_entries.items():
        tlen = len(txt)
        if tlen < 2 or tlen > 6 or w < 15.0:
            continue
        if not all(c in simp_chars for c in txt):
            continue
        for k in (1, 2, 3):
            if k >= tlen:
                continue
            pref = txt[:k]
            if pref in top_prefixes:
                record_assoc(pref, txt[k:], w)

    trigram_path = frost_dir / "others" / "3字统计结果.txt"
    if trigram_path.exists():
        with trigram_path.open("r", encoding="utf-8", errors="ignore") as tf:
            for line_idx, raw in enumerate(tf):
                if line_idx >= 150000:
                    break
                if "\t" not in raw:
                    continue
                txt, w_s = raw.rstrip("\r\n").split("\t", 1)
                if len(txt) != 3 or not w_s.isdigit():
                    continue
                wv = float(w_s)
                if wv < 50.0:
                    break
                for k in (1, 2):
                    pref = txt[:k]
                    if pref in top_prefixes:
                        record_assoc(pref, txt[k:], wv * 0.8)

    zhihu_path = frost_dir / "others" / "zhihu_deal_sort_merge.txt"
    if zhihu_path.exists():
        with zhihu_path.open("r", encoding="utf-8", errors="ignore") as zf:
            for line_idx, raw in enumerate(zf):
                if line_idx >= 220000:
                    break
                if "\t" not in raw:
                    continue
                txt, w_s = raw.rstrip("\r\n").split("\t", 1)
                tlen = len(txt)
                if tlen < 2 or tlen > 6 or not w_s.isdigit():
                    continue
                wv = float(w_s)
                if wv < 40.0:
                    break
                for k in (1, 2, 3):
                    if k >= tlen:
                        continue
                    pref = txt[:k]
                    if pref in top_prefixes:
                        record_assoc(pref, txt[k:], wv * 1.4)

    for pref, cont_list in CURATED_CONVERSATIONAL_ASSOC.items():
        for rank_i, cont in enumerate(cont_list):
            assoc_map[pref][cont] = max(assoc_map[pref].get(cont, 0), 3000 - rank_i * 65)

    # Snapshot seed assoc_map BEFORE adding external conversational bigrams so Step 3 spectral
    # propagation sees the pre-bigram distribution cleanly.
    spectral_assoc_map: dict[str, dict[str, int]] = {p: dict(cs) for p, cs in assoc_map.items()}

    if os.environ.get("LOKEY_SKIP_CONV_BIGRAMS") != "1":
        conv_path = data_dir / "conversational-bigrams.tsv"
        if conv_path.exists():
            conv_added = 0
            for raw in conv_path.read_text(encoding="utf-8", errors="ignore").splitlines():
                if not raw or raw.startswith("#"):
                    continue
                parts = raw.split("\t")
                if len(parts) < 3:
                    continue
                w1, w2, w_str = parts[0], parts[1], parts[2]
                if not (1 <= len(w1) <= 3 and 1 <= len(w2) <= 3):
                    continue
                if w1 not in top_prefixes or not all(c in simp_chars for c in w2):
                    continue
                try:
                    w_val = int(w_str)
                except ValueError:
                    continue
                if w_val > 0:
                    record_assoc(w1, w2, float(w_val))
                    conv_added += 1
            print(f"    Merged {conv_added:,} distilled conversational bigrams into association table.")

    # Sort prefixes strictly by unsigned UTF-8 byte order to match MmapLexicon binary search!
    final_assoc: list[tuple[int, int, int, int, int, int]] = []
    # The reserved keys only take part in exact-reading ranking, never next-word
    # predictions or neural training. Reuse the existing sorted mmap record format.
    commit_index = commit_choice_index(data_dir)
    ranking_index = {**assoc_map, **short_homophone_cues(cn_entries, frost_dir),
                     **mixed_phrase_index(cn_entries, frost_dir, norm_z, data_dir), **conversational_endings(),
                     **commit_index}
    for pref in sorted(ranking_index, key=lambda s: s.encode("utf-8")):
        is_special = pref[:1] in ("!", ":", "=", "~", "@", "$", "#") or pref in CURATED_CONVERSATIONAL_ASSOC
        cap = 14 if is_special else 12
        items = ranking_index[pref].items()
        if not is_special:
            items = ((cont, sc) for cont, sc in items if sc >= 120)
        cont_items = sorted(items, key=lambda x: x[1], reverse=True)[:cap]
        if not cont_items:
            continue
        k_off, k_len = intern_str(pref)
        for rank_i, (cont, sc) in enumerate(cont_items):
            v_off, v_len = intern_str(cont)
            final_assoc.append((k_off, v_off, k_len, v_len, sc, rank_i))

    print(f"    Compiled {len(final_assoc):,} next-word association edges across {len(assoc_map):,} prefixes.")

    print("==> [3.8/5] Training & quantizing On-Device Neural Language Model (LNLM v2, 32-dim SIMD)...")
    # 32 syntactic-semantic latent dimensions (`SIMD8<Float> x 4`):
    # 0..15 Core Grammatical Backbone:
    #   0: SUBJ_PRON, 1: TIME_ADV, 2: LOC_DIR, 3: MODAL_AUX,
    #   4: COGN_VERB, 5: MOTION_VERB, 6: INGEST_COOK_VERB, 7: GENERAL_TRANS_VERB,
    #   8: INTERROG_PRON, 9: FOOD_BEV_OBJ, 10: ARTIFACT_ABSTRACT_OBJ, 11: INANIMATE_LING_CONCEPT,
    #   12: ADJ_STATE, 13: DEG_NEG_ADV, 14: STRUCT_PREP_CONJ, 15: SENT_FINAL_PART
    # 16..31 Fine-Grained Semantic & Noisy-Channel Disambiguation Frames:
    #   16: TENTATIVE_EXPER_VERB, 17: SPEED_AUTO_MANNER_ADV, 18: TEXT_IME_DIGITAL_VERB, 19: TECH_TEXT_COMM_NOUN,
    #   20: GREETING_APOLOGY_POLITE, 21: ARRIVAL_POSTURE_TRANSIT, 22: PERCEPT_ACQUIRE_RESULT, 23: SOCIAL_CAUSATIVE_BENEF,
    #   24: USABILITY_FLUENCY_ADJ, 25: HOW_WHY_OBLIGATION_WH, 26: POSSESSIVE_REL_MOD, 27: PREPOSITIONAL_BASIS,
    #   28: DISCOURSE_COND_CAUSE, 29: QUANT_DURATION_EXTENT, 30: ACCIDENTAL_TYPO_SINGLETON, 31: LEXICAL_MULTIWORD_FLOW
    LNLM_DIM = 32
    seed_classes: dict[int, list[str]] = {
        0: [
            "我", "你", "他", "她", "它", "我们", "你们", "他们", "她们", "咱们", "大家", "自己", "别人", "人家",
            "有人", "没人", "老板", "老师", "朋友", "同事", "同学", "爸", "妈", "爸爸", "妈妈", "老婆", "老公",
            "孩子", "宝宝", "哥", "姐", "弟", "妹", "客户", "领导", "医生",
            "代表", "来宾", "客人", "长辈", "队员", "嘉宾", "选民", "乘客",
        ],
        1: [
            "今天", "明天", "昨天", "后天", "前天", "现在", "刚才", "刚刚", "刚", "才", "一会", "一会儿", "马上", "立刻",
            "早上", "上午", "中午", "下午", "晚上", "今晚", "明早", "昨晚", "周末", "平时", "最近", "以后",
            "以前", "之前", "之后", "时候", "那时候", "这时候", "今年", "明年", "去年", "每天", "天天", "随时",
            "回头", "改天", "待会", "待会儿", "等会", "等一下", "早点", "晚点", "半天",
            "今天晚上", "昨天晚上", "明天早上", "明天下午",
        ],
        2: [
            "这里", "那里", "这儿", "那儿", "哪里", "哪儿", "家里", "家", "公司", "学校", "医院", "超市",
            "商场", "饭店", "餐厅", "食堂", "外边", "外面", "里面", "里边", "上面", "下面", "前面", "后面",
            "地下", "底下", "地面", "地库", "地下室", "地铁", "车站", "机场", "高铁", "电梯", "楼梯", "办公室",
            "宿舍", "教室", "酒店", "宾馆", "公园", "广场", "银行", "路口", "现场", "车里", "屋里", "房间",
            "旁边", "附近", "路上", "车上", "楼上", "楼下", "门口", "地方", "那边", "这边", "国内", "国外",
            "北京", "上海", "广州", "深圳", "杭州", "成都", "大理",
        ],
        3: [
            "想", "要", "能", "会", "可以", "应该", "应当", "必须", "需要", "得", "打算", "准备", "愿意",
            "敢", "肯", "想要", "要想", "能够", "正在", "已经", "曾经", "还没", "还没有", "不用", "不要",
            "别", "不必", "不妨", "只好", "先", "赶紧",
        ],
        4: [
            "想起来", "想起", "记得", "记住", "忘记", "忘了", "忘", "知道", "觉得", "认为", "以为", "发现",
            "发觉", "看到", "看见", "听到", "听见", "听说", "说", "讲", "问", "问问", "告诉", "通知",
            "商量", "讨论", "考虑", "决定", "希望", "期待", "担心", "害怕", "恐怕", "喜欢", "爱", "讨厌",
            "明白", "懂", "理解", "了解", "怀疑", "相信", "猜", "估计", "感觉", "感到", "想象", "思考", "想想",
        ],
        5: [
            "去", "来", "回", "到", "出", "进", "上", "下", "走", "跑", "出去", "进来", "回来", "回去",
            "出来", "进去", "过去", "过来", "上去", "下来", "出门", "回家", "上班", "下班", "上学", "放学",
            "出发", "到达", "离开", "路过", "经过", "逛", "逛街", "散步", "旅游", "出差", "搬家", "起床",
        ],
        6: [
            "吃", "喝", "买饭", "吃饭", "做饭", "点餐", "点菜", "点外卖", "吃点", "喝点", "煮", "炒",
            "炖", "烤", "蒸", "煎", "炸", "泡", "尝", "尝尝", "喂", "请客", "聚餐", "干饭", "宵夜",
            "带饭", "热饭", "订餐", "吃火锅", "吃烧烤",
        ],
        7: [
            "看", "看看", "用", "写", "打", "玩", "学", "学习", "找", "拿", "带", "买", "卖", "发", "收",
            "送", "给", "帮", "帮忙", "帮助", "教", "修", "修改", "改", "查", "检查", "办", "处理", "解决",
            "完成", "开始", "继续", "停止", "结束", "换", "选", "选择", "穿", "洗", "做", "干", "弄", "搞",
            "开", "关", "打开", "关闭", "下载", "安装", "更新", "测试", "修复", "提交", "发布", "收到", "找到",
        ],
        8: [
            "什么", "啥", "哪", "哪个", "哪些", "哪里", "哪儿", "谁", "怎么", "怎么样", "怎样", "为什么",
            "为啥", "干嘛", "干什么", "做什么", "多少", "几", "几点", "多久", "多远", "难道", "究竟", "到底",
        ],
        9: [
            "饭", "菜", "面", "面条", "米饭", "粥", "包子", "饺子", "水饺", "馄饨", "馒头", "大饼", "油条",
            "豆浆", "牛奶", "面包", "蛋糕", "饼干", "零食", "水果", "苹果", "香蕉", "西瓜", "草莓", "肉",
            "牛肉", "猪肉", "羊肉", "鸡肉", "鱼", "虾", "蛋", "鸡蛋", "汤", "火锅", "烧烤", "烤肉", "麻辣烫",
            "米线", "米粉", "螺蛳粉", "汉堡", "披萨", "炸鸡", "薯条", "寿司", "便当", "盒饭", "盖饭", "炒饭",
            "炒面", "拉面", "牛肉面", "早餐", "早饭", "午餐", "午饭", "晚餐", "晚饭", "夜宵", "水", "茶",
            "奶茶", "咖啡", "可乐", "果汁", "啤酒", "酒", "饮料", "开水", "热水",
        ],
        10: [
            "东西", "事情", "事", "事儿", "问题", "情况", "工作", "作业", "任务", "消息", "信息", "电话",
            "手机", "电脑", "衣服", "鞋子", "包", "钱", "红包", "车", "地铁", "公交", "票", "书", "电影",
            "电视", "视频", "音乐", "歌", "游戏", "办法", "方法", "原因", "理由", "结果", "时间", "机会",
            "主意", "意思", "意义", "关系", "印象", "经验", "计划", "方案", "报告", "文件", "资料", "合同",
            "快递", "礼物", "钥匙", "密码", "账号", "链接", "图片", "照片", "截图",
        ],
        11: [
            "词", "字", "句", "词语", "词汇", "词典", "字典", "成语", "语法", "声母", "韵母",
            "音节", "汉字", "字母", "标点", "符号", "公式", "定理",
            "概念", "定义", "参数", "变量", "函数", "数组", "指针", "字节", "民", "提",
        ],
        12: [
            "好", "大", "小", "多", "少", "快", "慢", "早", "晚", "远", "近", "高", "低", "长", "短",
            "贵", "便宜", "新", "旧", "对", "错", "行", "好吃", "好喝", "好看", "好玩", "好听", "高兴",
            "开心", "快乐", "难过", "伤心", "痛苦", "生气", "郁闷", "烦", "累", "忙", "闲", "饿", "渴",
            "困", "冷", "热", "凉快", "暖和", "舒服", "难受", "疼", "痛", "腼腆", "害羞", "尴尬", "奇怪",
            "正常", "自然", "重要", "严重", "简单", "容易", "难", "困难", "复杂", "方便", "麻烦", "清楚",
            "模糊", "认真", "仔细", "小心", "漂亮", "美", "帅", "酷", "棒", "厉害", "差", "糟糕", "安全",
            "危险", "干净", "安静", "黏连", "粘连", "不安", "甜", "咸", "酸", "苦", "辣", "淡",
            "合格", "合适", "合规", "合理", "合法", "标准", "划算", "靠谱", "优秀", "满意", "丰富", "完整", "稳定",
        ],
        13: [
            "很", "非常", "特别", "十分", "极其", "太", "真", "挺", "蛮", "比较", "稍微", "略微", "有点",
            "有一点", "有点儿", "最", "更", "越", "越来越", "都", "全", "全部", "统统", "也", "还", "又",
            "再", "就", "才", "只", "仅仅", "光", "总", "总是", "老", "老是", "一直", "一向", "一起",
            "一块", "一共", "总共", "果然", "居然", "竟然", "简直", "确实", "的确", "真的", "真是", "其实",
            "本来", "原来", "幸好", "差点", "几乎", "差不多", "肯定", "一定", "绝对", "恰好", "刚好",
            "不", "没", "没有", "未", "非",
        ],
        14: [
            "的", "地", "得", "了", "着", "过", "在", "从", "自", "向", "往", "朝", "对", "对于", "关于",
            "跟", "和", "与", "同", "及", "以及", "或", "或者", "还是", "把", "将", "被", "叫", "让",
            "替", "为", "为了", "按", "按照", "根据", "通过", "因为", "由于", "所以", "因此", "虽然",
            "尽管", "但是", "可是", "不过", "然而", "却", "如果", "要是", "假如", "只要", "只有", "除非",
            "无论", "不管", "既然", "哪怕", "即使", "而且", "并且", "不但", "不仅", "那", "这",
        ],
        15: [
            "吗", "呢", "吧", "啊", "呀", "哇", "啦", "呗", "嘛", "哦", "噢", "喔", "哈", "嘿", "呐",
            "哟", "咯", "喽", "罢了", "而已", "来着",
        ],
        16: [
            "试试", "看看", "想想", "问问", "找找", "尝尝", "体验", "感受", "测试", "尝试", "试一下", "看一下",
            "再试试", "再看看", "再想想",
        ],
        17: [
            "快速", "自动", "直接", "实时", "无延迟", "零延迟", "顺畅", "流畅", "智能", "迅速", "随手", "盲打",
            "快速输入", "自动补全",
        ],
        18: [
            "输入", "打字", "补全", "识别", "纠错", "联想", "预测", "上屏", "发送", "回复", "发消息", "回消息",
            "运行", "解码", "叠加", "快速输入", "自动补全",
        ],
        19: [
            "输入法", "语义", "上下文", "上文", "模型", "本地模型", "长句", "句子", "键盘", "词库", "候选词",
            "延迟", "本地", "系统", "漏敲", "错敲", "拼音",
        ],
        20: [
            "你好", "您好", "不好意思", "抱歉", "对不起", "谢谢", "麻烦", "打扰", "请问", "辛苦", "早安",
            "晚安", "再见", "拜拜",
        ],
        21: [
            "刚到", "到了", "到家", "下班", "上班", "出门", "起床", "睡醒", "刚睡醒", "坐地铁", "坐高铁",
            "坐飞机", "坐公交", "坐车", "开车", "打车", "排队",
        ],
        22: [
            "看到", "没看到", "收到", "已收到", "听到", "找到", "买到", "弄好", "搞定", "完成", "已完成",
            "写完了", "看完了", "吃完了", "忙完了", "做完了",
        ],
        23: [
            "帮我", "帮你", "给我", "给你", "让我", "让你", "叫我", "陪我", "跟你", "一起", "一起去", "顺便",
            "我来", "我去", "我们先",
        ],
        24: [
            "好用", "很好用", "丝滑", "流畅", "准确", "精准", "舒服", "方便", "卡顿", "很快", "太快", "打字太快",
            "不错", "给力",
        ],
        25: [
            "怎么办", "怎么样", "怎么弄", "怎么走", "为什么", "为啥", "干嘛", "多久", "几点", "能不能",
            "可不可以", "要不要", "好不好", "行不行",
        ],
        26: [
            "我的", "你的", "他的", "她的", "我们的", "自己的", "的时候", "的话", "之后", "之前",
        ],
        27: [
            "根据", "通过", "按照", "靠", "利用", "基于", "根据语义",
        ],
        28: [
            "因为", "所以", "但是", "不过", "而且", "同时", "如果", "要是", "虽然", "其实", "反正", "哪怕",
            "万一", "不然",
        ],
        29: [
            "一下", "一点", "一些", "好几次", "一次", "一个", "两个", "几个", "每个", "很多", "不少", "全部",
            "这个", "那个", "这种", "那种", "这些", "那些",
        ],
        30: [
            "亏", "素", "恩", "剋", "嗲", "奥", "欧", "厄", "吾", "尔", "乃", "乎", "哉", "兮", "甫",
            "仑", "萨", "姆", "兹", "夫", "帕",
        ],
    }

    # Explicit dual-role `(tgt_dict, ctx_dict)` overrides for multi-morpheme phrases whose left/incoming
    # syntactic head differs from their right/outgoing syntactic tail.
    composite_overrides: dict[str, tuple[dict[int, float], dict[int, float]]] = {
        "这个": ({29: 1.45, 31: 0.50}, {29: 1.50, 31: 0.50}),
        "那个": ({29: 1.45, 31: 0.50}, {29: 1.50, 31: 0.50}),
        "这种": ({29: 1.40, 31: 0.50}, {29: 1.45, 31: 0.50}),
        "那种": ({29: 1.40, 31: 0.50}, {29: 1.45, 31: 0.50}),
        "这些": ({29: 1.40, 31: 0.50}, {29: 1.45, 31: 0.50}),
        "那些": ({29: 1.40, 31: 0.50}, {29: 1.45, 31: 0.50}),
        "一个": ({29: 1.40, 31: 0.45}, {29: 1.45, 31: 0.45}),
        "一下": ({29: 1.35, 31: 0.45}, {15: 0.85, 31: 0.45}),
        "一次": ({29: 1.30, 31: 0.45}, {15: 0.75, 31: 0.45}),
        "好几次": ({29: 1.30, 31: 0.50}, {15: 0.75, 31: 0.50}),
        "看看": ({16: 1.45, 7: 0.75, 31: 0.50}, {16: 1.50, 7: 0.70, 31: 0.50}),
        "输入法": ({19: 1.50, 10: 0.75, 31: 0.60}, {19: 1.50, 10: 0.75, 31: 0.60}),
        "合格": ({12: 1.45, 31: 0.45}, {12: 1.45, 31: 0.45}),
        "合适": ({12: 1.45, 31: 0.45}, {12: 1.45, 31: 0.45}),
        "吃什么": ({6: 1.45, 8: 0.85, 31: 0.45}, {8: 1.25, 6: 0.70, 31: 0.45}),
        "喝什么": ({6: 1.45, 8: 0.85, 31: 0.45}, {8: 1.25, 6: 0.70, 31: 0.45}),
        "吃啥": ({6: 1.40, 8: 0.80, 31: 0.45}, {8: 1.20, 6: 0.65, 31: 0.45}),
        "买什么": ({7: 1.35, 8: 0.80, 31: 0.45}, {8: 1.20, 7: 0.60, 31: 0.45}),
        "干什么": ({7: 1.35, 8: 0.85, 25: 0.75, 31: 0.45}, {8: 1.20, 7: 0.60, 25: 0.65, 31: 0.45}),
        "做什么": ({7: 1.35, 8: 0.85, 25: 0.75, 31: 0.45}, {8: 1.20, 7: 0.60, 25: 0.65, 31: 0.45}),
        "说什么": ({4: 1.30, 8: 0.85, 31: 0.45}, {8: 1.20, 4: 0.60, 31: 0.45}),
        "看什么": ({7: 1.30, 8: 0.85, 31: 0.45}, {8: 1.20, 7: 0.60, 31: 0.45}),
        "出什么": ({5: 0.55, 7: 0.55, 8: 0.50}, {8: 0.90, 10: 0.40}),
        "去哪": ({5: 1.35, 2: 0.65, 8: 0.80, 31: 0.45}, {5: 1.05, 8: 1.15, 2: 0.70, 31: 0.45}),
        "去哪里": ({5: 1.35, 2: 0.70, 8: 0.80, 31: 0.45}, {5: 1.05, 8: 1.15, 2: 0.75, 31: 0.45}),
        "去哪儿": ({5: 1.35, 2: 0.70, 8: 0.80, 31: 0.45}, {5: 1.05, 8: 1.15, 2: 0.75, 31: 0.45}),
        "到哪": ({5: 1.25, 2: 0.65, 8: 0.75, 31: 0.45}, {5: 0.95, 8: 1.10, 2: 0.70, 31: 0.45}),
        "在哪": ({2: 1.10, 8: 0.80, 31: 0.45}, {2: 0.95, 8: 1.10, 31: 0.45}),
        "在哪里": ({2: 1.10, 8: 0.80, 31: 0.45}, {2: 0.95, 8: 1.10, 31: 0.45}),
        "去那": ({5: 0.85, 14: 0.60}, {14: 1.15, 2: 0.25}),
        "到那": ({5: 0.80, 14: 0.60}, {14: 1.15, 2: 0.25}),
        "在那": ({14: 0.90, 2: 0.40}, {14: 1.15, 2: 0.25}),
        "吃饭": ({6: 1.45, 9: 0.55, 31: 0.45}, {9: 1.15, 6: 0.70, 31: 0.45}),
        "买饭": ({6: 1.45, 7: 0.50, 9: 0.55, 31: 0.45}, {9: 1.15, 6: 0.70, 31: 0.45}),
        "做饭": ({6: 1.40, 9: 0.55, 31: 0.45}, {9: 1.15, 6: 0.65, 31: 0.45}),
        "点餐": ({6: 1.35, 9: 0.50, 31: 0.45}, {9: 1.05, 6: 0.65, 31: 0.45}),
        "喝水": ({6: 1.35, 9: 0.55, 31: 0.45}, {9: 1.10, 6: 0.65, 31: 0.45}),
        "吃火锅": ({6: 1.45, 9: 0.75, 31: 0.55}, {9: 1.25, 6: 0.70, 31: 0.55}),
        "想起来": ({4: 1.45, 3: 0.40, 31: 0.45}, {4: 1.50, 31: 0.45}),
        "想起": ({4: 1.40, 3: 0.35, 31: 0.45}, {4: 1.45, 31: 0.45}),
        "不知道": ({13: 0.80, 4: 1.15, 31: 0.45}, {4: 1.40, 31: 0.45}),
        "不记得": ({13: 0.80, 4: 1.15, 31: 0.45}, {4: 1.40, 31: 0.45}),
        "没想到": ({13: 0.80, 4: 1.15, 31: 0.45}, {4: 1.40, 31: 0.45}),
        "出去": ({5: 1.45, 31: 0.45}, {5: 1.45, 31: 0.45}),
        "回来": ({5: 1.40, 31: 0.45}, {5: 1.40, 31: 0.45}),
        "回去": ({5: 1.40, 31: 0.45}, {5: 1.40, 31: 0.45}),
        "出来": ({5: 1.35, 31: 0.45}, {5: 1.35, 31: 0.45}),
        "进去": ({5: 1.35, 31: 0.45}, {5: 1.35, 31: 0.45}),
        "进来": ({5: 1.35, 31: 0.45}, {5: 1.35, 31: 0.45}),
        "一会": ({1: 1.40, 31: 0.45}, {1: 1.40, 3: 0.35, 31: 0.45}),
        "一会儿": ({1: 1.40, 31: 0.45}, {1: 1.40, 3: 0.35, 31: 0.45}),
        "明天": ({1: 1.45, 31: 0.45}, {1: 1.50, 31: 0.45}),
        "今天": ({1: 1.45, 31: 0.45}, {1: 1.50, 31: 0.45}),
        "昨天": ({1: 1.40, 31: 0.45}, {1: 1.45, 31: 0.45}),
        "现在": ({1: 1.45, 31: 0.45}, {1: 1.45, 31: 0.45}),
        "今天晚上": ({1: 1.50, 31: 0.55}, {1: 1.50, 31: 0.55}),
        "面条": ({9: 1.45, 31: 0.45}, {9: 1.45, 31: 0.45}),
        "腼腆": ({12: 1.45, 31: 0.45}, {12: 1.45, 31: 0.45}),
        "词": ({11: 1.50}, {11: 1.50}),
        "情况": ({10: 1.35, 31: 0.45}, {10: 1.35, 31: 0.45}),
        "黏连感": ({10: 1.25, 12: 0.65, 31: 0.45}, {10: 1.35, 31: 0.45}),
        "地下": ({2: 1.45, 31: 0.45}, {2: 1.45, 31: 0.45}),
        "底下": ({2: 1.35, 31: 0.45}, {2: 1.35, 31: 0.45}),
        "楼下": ({2: 1.45, 31: 0.45}, {2: 1.45, 31: 0.45}),
        "楼上": ({2: 1.45, 31: 0.45}, {2: 1.45, 31: 0.45}),
        "门口": ({2: 1.45, 31: 0.45}, {2: 1.45, 31: 0.45}),
        "感到": ({4: 1.45, 31: 0.45}, {4: 1.45, 12: 0.45, 31: 0.45}),
        "刚到": ({1: 0.85, 5: 1.35, 21: 1.25, 31: 0.45}, {5: 1.45, 2: 0.35, 21: 1.25, 31: 0.45}),
        "再去": ({13: 0.85, 5: 1.35, 31: 0.45}, {5: 1.45, 7: 0.45, 16: 0.45, 31: 0.45}),
        "我来": ({0: 0.90, 5: 0.85, 23: 1.35, 31: 0.45}, {5: 0.95, 23: 1.40, 3: 0.45, 31: 0.45}),
        "试试": ({16: 1.45, 7: 0.70, 31: 0.50}, {16: 1.45, 7: 0.70, 31: 0.50}),
        "快速": ({17: 1.50, 12: 0.45, 31: 0.50}, {17: 1.50, 31: 0.50}),
        "自动": ({17: 1.50, 31: 0.50}, {17: 1.50, 31: 0.50}),
        "无延迟": ({17: 1.45, 24: 0.85, 31: 0.55}, {17: 1.45, 24: 0.75, 31: 0.55}),
        "输入": ({18: 1.45, 19: 0.65, 7: 0.55, 31: 0.50}, {18: 1.35, 19: 0.85, 31: 0.50}),
        "补全": ({18: 1.50, 7: 0.60, 31: 0.50}, {18: 1.40, 19: 0.65, 31: 0.50}),
        "快速输入": ({17: 1.25, 18: 1.45, 31: 0.65}, {18: 1.40, 19: 0.85, 31: 0.65}),
        "自动补全": ({17: 1.25, 18: 1.50, 31: 0.65}, {18: 1.45, 19: 0.75, 31: 0.65}),
        "根据": ({27: 1.45, 14: 0.75, 31: 0.45}, {27: 1.50, 31: 0.45}),
        "通过": ({27: 1.45, 14: 0.70, 31: 0.45}, {27: 1.50, 31: 0.45}),
        "语义": ({19: 1.45, 10: 0.65, 31: 0.50}, {19: 1.45, 27: 0.55, 31: 0.50}),
        "根据语义": ({27: 1.35, 19: 1.25, 31: 0.65}, {19: 1.45, 17: 0.65, 31: 0.65}),
        "本地": ({19: 1.25, 2: 0.45, 31: 0.45}, {19: 1.35, 26: 0.45, 31: 0.45}),
        "模型": ({19: 1.45, 10: 0.65, 31: 0.50}, {19: 1.45, 17: 0.45, 31: 0.50}),
        "本地模型": ({19: 1.50, 10: 0.65, 31: 0.60}, {19: 1.50, 17: 0.55, 31: 0.60}),
        "不好意思": ({20: 1.50, 31: 0.60}, {20: 1.50, 0: 0.45, 31: 0.60}),
        "刚睡醒": ({21: 1.45, 1: 0.75, 31: 0.55}, {21: 1.45, 13: 0.55, 31: 0.55}),
        "没看到": ({13: 0.75, 22: 1.45, 4: 0.65, 31: 0.55}, {22: 1.45, 10: 0.65, 31: 0.55}),
        "怎么办": ({25: 1.50, 8: 0.85, 31: 0.55}, {25: 1.45, 15: 0.65, 31: 0.55}),
        "怎么样": ({25: 1.45, 8: 0.85, 31: 0.55}, {25: 1.40, 15: 0.65, 31: 0.55}),
        "喝": ({6: 1.45}, {6: 1.50}),
        "坐": ({5: 1.40, 7: 0.45, 21: 0.75}, {5: 1.40, 2: 0.55, 21: 0.85}),
        "地": ({14: 1.25, 2: 0.35}, {14: 1.25, 2: 0.35}),
    }

    # Build character-level syntactic priors (`char_ctx`, `char_tgt`) for all simplified characters in 0x4E00..<0xA000
    char_ctx_vecs: dict[str, list[float]] = {}
    char_tgt_vecs: dict[str, list[float]] = {}

    def ensure_char_vec(ch: str) -> tuple[list[float], list[float]]:
        c_v = char_ctx_vecs.get(ch)
        t_v = char_tgt_vecs.get(ch)
        if c_v is None or t_v is None:
            c_v = [0.0] * LNLM_DIM
            t_v = [0.0] * LNLM_DIM
            char_ctx_vecs[ch] = c_v
            char_tgt_vecs[ch] = t_v
        return c_v, t_v

    for dim_i, w_list in seed_classes.items():
        if dim_i == 30:
            # Dim 30 (`ACCIDENTAL_TYPO_SINGLETON`) applies strictly to standalone 1-char tokens,
            # never propagating into multi-character lexical words (`吃亏`, `朴素`, `欧洲`)!
            for w in w_list:
                if len(w) == 1:
                    cv, tv = ensure_char_vec(w)
                    cv[30] = max(cv[30], 1.35)
                    tv[30] = max(tv[30], 1.35)
            continue
        for w in w_list:
            if len(w) == 1:
                cv, tv = ensure_char_vec(w)
                cv[dim_i] = max(cv[dim_i], 1.25)
                tv[dim_i] = max(tv[dim_i], 1.25)
            else:
                # Propagate head/tail character priors from multi-char seed words
                f_cv, f_tv = ensure_char_vec(w[0])
                l_cv, l_tv = ensure_char_vec(w[-1])
                f_tv[dim_i] = max(f_tv[dim_i], 0.75)
                f_cv[dim_i] = max(f_cv[dim_i], 0.45)
                l_cv[dim_i] = max(l_cv[dim_i], 0.75)
                l_tv[dim_i] = max(l_tv[dim_i], 0.45)

    # Morphological suffix/prefix character rules for broad coverage across all 8,105 characters
    morph_char_priors: dict[int, str] = {
        0: "我你他她它咱谁爸妈哥姐弟妹爷奶叔阿姨儿女师友客员官警医民",
        1: "今明昨后前早中下午晚夜晨日年岁时分秒刻期周季春秋冬夏久暂刚",
        2: "地楼门库梯铁里外上下前后内中旁近远东中西北海京沪广深室厅店家校院店馆场站路街城国省市县村区园港湾岛岸桥层座台处所方边侧角顶底",
        3: "想要能会可应该须得敢肯愿准备打算别莫勿",
        4: "想记忘知觉认以发看听讲问告通商讨考决希期担怕恐喜怒哀乐爱恨懂明理信猜估感思念",
        5: "去来回出进上下走跑飞跳游逛退逃追赶送达离过起落入登乘坐骑驾",
        6: "吃喝咬吞嚼尝喂煮炒炖烤蒸煎炸泡烹调饮餐饭菜",
        7: "看用写打玩学找拿带买卖发收送给帮教修改查办处解完开停换选穿洗做干弄搞拉推抱提抓握拍按切割",
        8: "什啥哪谁怎何几多",
        9: "饭菜面米粥包饺饼油豆奶糕糖果茶酒水肉牛猪羊鸡鱼虾蛋汤锅粉堡茶咖肴膳饮",
        10: "事物题况工信话机衣钱车票书影歌戏法因果时机意系感验计案报件资礼钥密账图照品",
        11: "词字句语典音符码数函变参算逻民提",
        12: "好大小多少快慢早晚远近高低长短贵新旧对错行美帅酷棒差累忙闲饿渴困冷热舒服疼腼腆羞尬奇正重简难清真安危净静",
        13: "很非特十太真挺蛮较稍略最更越都全也还又再就才只光总老一果居竟简确真其本幸差几肯必绝偏恰刚不没未",
        14: "的地得了着过在从自向往朝对跟和与同及或把将被叫让替为按据通因由所虽但可然却如要只除无不既哪那这",
        15: "吗呢吧啊呀哇啦呗嘛哦噢喔哈嘿呐哟咯喽",
        16: "试尝探验测",
        17: "快迅疾速自直立秒顺畅智盲",
        18: "输敲键补识纠联预屏译发回解叠",
        19: "模库句键屏端网码延讯微",
        20: "谢歉扰劳烦请安拜",
        21: "醒班铁机车队达",
        22: "收完妥定毕获",
        23: "帮陪让给顺共",
        24: "丝滑准稳利便卡爽",
        25: "怎何啥哪几",
    }
    for dim_i, chars_str in morph_char_priors.items():
        for ch in chars_str:
            cv, tv = ensure_char_vec(ch)
            if cv[dim_i] < 0.85:
                cv[dim_i] = 0.85
            if tv[dim_i] < 0.85:
                tv[dim_i] = 0.85

    # Explicit overrides for single characters that must not confuse syntactic roles
    for ch, (t_map, c_map) in composite_overrides.items():
        if len(ch) == 1:
            cv, tv = ensure_char_vec(ch)
            for k in range(LNLM_DIM):
                cv[k] = c_map.get(k, 0.0)
                tv[k] = t_map.get(k, 0.0)

    # Load QAT end-to-end LNLM v2 backbone (`LNB2`) before word/char vocab selection so every
    # backbone character & overridden word is guaranteed a slot in `sorted_chars` / `lnlm_word_set`.
    backbone_path = data_dir / "lnlm_backbone_v2.bin.zlib"
    backbone_chars_path = data_dir / "lnlm_backbone_chars.txt"
    bb_chars = ""
    bb_char_emb = b""
    bb_mlp = b""
    bb_word_overrides: dict[str, bytes] = {}
    bb_loaded = False
    if os.environ.get("LOKEY_SKIP_LNLM_BACKBONE") != "1" and backbone_path.exists():
        raw_bb = zlib.decompress(backbone_path.read_bytes())
        if len(raw_bb) < 48:
            raise ValueError(f"LNLM backbone image too small: {backbone_path}")
        bb_magic, bb_ver, bb_c_count, bb_w_count, bb_chars_sha = struct.unpack_from("<4sIII32s", raw_bb, 0)
        if bb_magic != b"LNB2" or bb_ver != 1:
            raise ValueError(f"Unsupported LNLM backbone header: magic={bb_magic!r} ver={bb_ver}")
        if not backbone_chars_path.is_file():
            raise ValueError(f"Missing LNLM backbone char index: {backbone_chars_path}")
        bb_chars = backbone_chars_path.read_text(encoding="utf-8")
        if len(bb_chars) != bb_c_count:
            raise ValueError(f"LNLM backbone char count mismatch: {bb_c_count} vs {len(bb_chars)}")
        expected_sha = hashlib.sha256(bb_chars.encode("utf-8")).digest()
        if bb_chars_sha != expected_sha:
            raise ValueError("LNLM backbone char table SHA-256 mismatch")

        cursor = 48
        c_bytes_len = (bb_c_count + 1) * 64
        if len(raw_bb) < cursor + c_bytes_len + 25344:
            raise ValueError("LNLM backbone truncated before embeddings/MLP")
        bb_char_emb = raw_bb[cursor : cursor + c_bytes_len]
        cursor += c_bytes_len
        if bb_char_emb[:64] != b"\x00" * 64:
            raise ValueError("LNLM backbone cid=0 char embedding must remain zero")

        bb_mlp = raw_bb[cursor : cursor + 25344]
        cursor += 25344

        for _ in range(bb_w_count):
            if cursor + 2 > len(raw_bb):
                raise ValueError("LNLM backbone truncated inside word override header")
            (w_len,) = struct.unpack_from("<H", raw_bb, cursor)
            cursor += 2
            if cursor + w_len + 64 > len(raw_bb):
                raise ValueError("LNLM backbone truncated inside word override body")
            w_str = raw_bb[cursor : cursor + w_len].decode("utf-8")
            cursor += w_len
            vec64 = raw_bb[cursor : cursor + 64]
            cursor += 64
            bb_word_overrides[w_str] = vec64
        if cursor != len(raw_bb):
            raise ValueError(f"LNLM backbone trailing bytes: {len(raw_bb) - cursor}")
        for ch in bb_chars:
            ensure_char_vec(ch)
        bb_loaded = True

    # Select top 32,768 words for the explicit LNLM v2 neural word embedding table
    lnlm_vocab_cap = 32768
    lnlm_word_set: set[str] = set()
    for w_list in seed_classes.values():
        lnlm_word_set.update(w_list)
    lnlm_word_set.update(target_delta_words)
    if bb_loaded:
        for w in bb_word_overrides.keys():
            if 1 <= len(w) <= 5 and all(0x4E00 <= ord(c) < 0xA000 for c in w):
                lnlm_word_set.add(w)
    lnlm_word_set.update(composite_overrides.keys())
    lnlm_word_set.update(CURATED_CONVERSATIONAL_ASSOC.keys())
    for cont_list in CURATED_CONVERSATIONAL_ASSOC.values():
        lnlm_word_set.update(cont_list)

    all_ranked_words = sorted(
        ((txt, w) for txt, w in word_max_w.items() if 1 <= len(txt) <= 5 and all(0x4E00 <= ord(c) < 0xA000 for c in txt)),
        key=lambda x: x[1],
        reverse=True,
    )
    for txt, _ in all_ranked_words:
        if len(lnlm_word_set) >= lnlm_vocab_cap:
            break
        lnlm_word_set.add(txt)

    word_ctx_vecs: dict[str, list[float]] = {}
    word_tgt_vecs: dict[str, list[float]] = {}

    # Step 1: Initialize word embeddings from seed classes, composite overrides, and compositional character priors
    seed_word_dims: dict[str, list[int]] = defaultdict(list)
    for dim_i, w_list in seed_classes.items():
        for w in w_list:
            seed_word_dims[w].append(dim_i)

    sorted_lnlm_base = sorted(lnlm_word_set)
    for w in sorted_lnlm_base:
        if w in composite_overrides:
            t_map, c_map = composite_overrides[w]
            tv = [t_map.get(k, 0.0) for k in range(LNLM_DIM)]
            cv = [c_map.get(k, 0.0) for k in range(LNLM_DIM)]
            word_tgt_vecs[w] = tv
            word_ctx_vecs[w] = cv
            continue

        f_cv, f_tv = ensure_char_vec(w[0])
        l_cv, l_tv = ensure_char_vec(w[-1])
        if len(w) == 1:
            tv = list(f_tv)
            cv = list(f_cv)
        else:
            tv = [0.0 if k == 30 else (0.65 * f_tv[k] + 0.35 * l_tv[k]) for k in range(LNLM_DIM)]
            cv = [0.0 if k == 30 else (0.35 * f_cv[k] + 0.65 * l_cv[k]) for k in range(LNLM_DIM)]
            tv[31] = 0.45
            cv[31] = 0.45

        if w in seed_word_dims:
            for d in seed_word_dims[w]:
                if d == 30 and len(w) > 1:
                    continue
                tv[d] = max(tv[d], 1.35)
                cv[d] = max(cv[d], 1.35)

        word_tgt_vecs[w] = tv
        word_ctx_vecs[w] = cv

    # Step 2: Define the 32x32 syntactic-semantic bilinear transition matrix `B_direct[tgt_dim][ctx_dim]`
    # Row `j` = incoming target dimension of `nextWord` (`v_tgt[j]`)
    # Col `i` = outgoing context dimension of `prevWord` (`v_ctx[i]`)
    b_direct = [[0.0] * LNLM_DIM for _ in range(LNLM_DIM)]

    def set_trans(ctx_dim: int, tgt_dim: int, val: float) -> None:
        b_direct[tgt_dim][ctx_dim] = val

    # 0..15 Core syntactic transitions (preserving 100% of verified LNLM v1 grammatical laws)
    # 0: SUBJ_PRON -> Time, Modal, Cogn, Motion, Ingest, TransVerb, Adj, Adv, Tentative, Arrival, Percept, Social, HowWh
    for td, v in [
        (1, 0.75), (3, 0.90), (4, 0.85), (5, 0.75), (6, 0.75), (7, 0.70), (12, 0.45), (13, 0.80),
        (16, 0.75), (21, 0.85), (22, 0.75), (23, 0.80), (25, 0.65), (11, -1.10), (30, -1.25),
    ]:
        set_trans(0, td, v)
    # 1: TIME_ADV -> Subj, Modal, Cogn, Motion, Ingest (strong!), TransVerb, Adj, Adv; penalize FoodSubj & LingNoun
    for td, v in [
        (0, 0.70), (3, 0.85), (4, 0.60), (5, 0.95), (6, 1.25), (7, 0.75), (8, 0.45), (12, 0.45), (13, 0.65),
        (16, 0.70), (18, 0.65), (21, 0.80), (22, 0.70), (23, 0.85), (25, 0.75), (9, -0.55), (11, -1.50), (30, -1.30),
    ]:
        set_trans(1, td, v)
    # 2: LOC_DIR -> Motion, Ingest, TransVerb, Adj, Struct, FinalPart; penalize LingNoun
    for td, v in [(5, 0.60), (6, 0.85), (7, 0.70), (12, 0.55), (14, 0.50), (15, 0.80), (21, 0.65), (11, -1.10), (30, -1.10)]:
        set_trans(2, td, v)
    # 3: MODAL_AUX -> Cogn, Motion, Ingest, TransVerb, Adv, Tentative, SpeedAdv, ImeVerb, PrepBasis
    for td, v in [
        (2, 0.40), (4, 0.65), (5, 1.05), (6, 1.05), (7, 0.95), (8, 0.45), (13, 0.45),
        (16, 0.95), (17, 0.85), (18, 0.95), (21, 0.75), (22, 0.75), (27, 0.85), (9, -0.75), (11, -1.35), (30, -1.35),
    ]:
        set_trans(3, td, v)
    # 4: COGN_VERB (`想起来`, `知道`, `觉得`) -> Subj, Time (`想起来 明天`), Modal, Motion, Ingest, TransVerb, Interrog, Obj, DetQuant
    for td, v in [
        (0, 0.80), (1, 1.15), (2, 0.55), (3, 0.75), (4, 0.45), (5, 0.75), (6, 0.85), (7, 0.75), (8, 0.85), (10, 0.80),
        (13, 0.65), (14, 0.55), (24, 0.85), (25, 0.95), (29, 0.85), (9, -0.35), (11, -1.15), (12, -0.45), (30, -1.30),
    ]:
        set_trans(4, td, v)
    # 5: MOTION_VERB (`去`, `来`, `出去`, `回来`) -> Loc, Motion, Ingest (`出去 买饭`, `去 吃饭`), TransVerb, Interrog (`去 哪`), Tentative (`来 试试`, `去 看看`), SpeedAdv (`来 快速`)
    for td, v in [
        (2, 1.05), (5, 0.65), (6, 1.15), (7, 0.90), (8, 1.00), (14, 0.55), (15, 0.75),
        (16, 1.15), (17, 0.85), (18, 0.95), (29, 0.65), (9, -0.55), (11, -1.30), (30, -1.35),
    ]:
        set_trans(5, td, v)
    # 6: INGEST_COOK_VERB (`吃`, `喝`, `买饭`) -> Interrog (`吃 什么`), FoodObj (`吃 面条`, `买 饭`), Struct (`吃 了`), FinalPart (`吃饭 吧`)
    for td, v in [(8, 1.35), (9, 1.35), (14, 0.75), (15, 0.85), (29, 0.65), (1, -0.70), (11, -1.60), (12, -0.60), (30, -1.40)]:
        set_trans(6, td, v)
    # 7: GENERAL_TRANS_VERB -> Subj, Interrog, FoodObj, ArtifactObj, Struct, FinalPart, TechNoun
    for td, v in [(0, 0.65), (8, 1.05), (9, 0.75), (10, 1.05), (14, 0.75), (15, 0.65), (19, 0.80), (29, 0.95), (11, -0.70), (30, -1.25)]:
        set_trans(7, td, v)
    # 8: INTERROG_PRON (`什么`, `去哪`) -> Ingest (`去哪 吃饭`), TransVerb, FoodObj, ArtifactObj (`什么 时候`), FinalPart (`什么 呢`, `去哪 啊`)
    for td, v in [(1, 0.85), (5, 0.55), (6, 0.85), (7, 0.70), (9, 0.60), (10, 0.95), (15, 0.95), (11, -0.90), (30, -1.25)]:
        set_trans(8, td, v)
    # 9: FOOD_BEV_OBJ (`面条`, `米饭`) -> Adj (`好吃`), Struct (`的`, `了`), FinalPart (`吧`, `呢`);
    #    STRONGLY PENALIZE `FOOD_BEV_OBJ -> INGEST_COOK_VERB` (`*面条 吃什么`!)
    for td, v in [(12, 0.60), (13, 0.40), (14, 0.60), (15, 0.75), (6, -1.55), (8, -0.95), (11, -1.20), (30, -1.15)]:
        set_trans(9, td, v)
    # 10: ARTIFACT_ABSTRACT_OBJ (`情况`, `问题`, `产品`) -> Adj (`产品 合格`), Struct, FinalPart (`情况 呢`), UsabilityAdj, HowWh; penalize dangling Modal (`*情况 能`), Ingest & bare Det (`*产品 这个`)
    for td, v in [(12, 0.65), (13, 0.45), (14, 0.65), (15, 1.05), (24, 0.65), (25, 0.75), (3, -0.75), (6, -1.10), (11, -0.95), (29, -0.75), (30, -1.20)]:
        set_trans(10, td, v)
    # 11: INANIMATE_LING_CONCEPT (`词`, `民`, `提`) -> strongly penalize Interrog (`*词 什么`), Ingest (`*提 啊 吃`), Food, FinalPart confetti (`*民 提 啊`)
    for td, v in [(1, -0.90), (5, -0.90), (6, -1.45), (8, -1.60), (9, -1.20), (11, -1.25), (15, -1.25), (30, -1.30)]:
        set_trans(11, td, v)
    # 12: ADJ_STATE (`腼腆`, `好吃`, `合格`) -> Struct (`的`, `了`), FinalPart (`啊`, `吧`);
    #     STRONGLY PENALIZE `ADJ_STATE -> INGEST_COOK_VERB` (`*腼腆 吃什么`) and bare 2-char `ADJ_STATE -> NOUN` without `的` (`*合格 输入法`)!
    for td, v in [(14, 0.80), (15, 0.80), (6, -1.55), (8, -0.95), (9, -0.80), (10, -0.75), (11, -1.20), (19, -0.85), (30, -1.20)]:
        set_trans(12, td, v)
    # 13: DEG_NEG_ADV (`很`, `不`, `没`, `也`) -> Modal, Cogn, Motion, Ingest, TransVerb, Adj (`很 好`, `不 合格`), Percept (`没 看到`), Usability (`很 好用`)
    for td, v in [
        (3, 0.90), (4, 0.85), (5, 0.80), (6, 0.85), (7, 0.80), (12, 1.15),
        (16, 0.70), (17, 0.70), (18, 0.70), (22, 0.95), (24, 1.15), (9, -0.75), (11, -1.25), (29, -0.95), (30, -1.30),
    ]:
        set_trans(13, td, v)
    # 14: STRUCT_PREP_CONJ (`的`, `了`, `在`, `那`) -> Loc, FoodObj, ArtifactObj, Adj, TechNoun; penalize bare Ingest after demonstrative `那`
    for td, v in [(0, 0.45), (2, 0.75), (9, 0.65), (10, 0.85), (12, 0.55), (18, 0.65), (19, 0.85), (6, -0.45), (11, -0.60), (30, -1.10)]:
        set_trans(14, td, v)
    # 15: SENT_FINAL_PART (`呢`, `吗`, `啊`, `吧`) -> usually EOS; penalize mid-sentence continuation into verbs/nouns
    for td, v in [(0, 0.25), (6, -0.45), (8, -0.55), (11, -1.00), (30, -1.25)]:
        set_trans(15, td, v)

    # 16..31 Semantic Frame Transitions:
    # 16: TENTATIVE_EXPER_VERB (`试试`, `看看`) -> DetQuant (`看看 这个`), SpeedAdv (`试试 快速`), ImeVerb (`试试 输入`), TechNoun (`试试 输入法`), ArtifactObj, HowWh, FinalPart; penalize bare AdjState (`*看看 合格`) & Singleton (`*试试 亏`)
    for td, v in [(8, 0.75), (10, 0.80), (12, -0.55), (15, 0.85), (17, 1.30), (18, 1.25), (19, 1.05), (24, 0.70), (25, 0.85), (29, 1.15), (30, -1.55)]:
        set_trans(16, td, v)
    # 17: SPEED_AUTO_MANNER_ADV (`快速`, `自动`, `无延迟`) -> ImeVerb (`快速 输入`, `自动 补全`), TransVerb, Struct (`无延迟 的`), TechNoun
    for td, v in [(5, 0.55), (7, 0.95), (14, 0.75), (18, 1.45), (19, 0.75), (22, 0.80), (30, -1.55)]:
        set_trans(17, td, v)
    # 18: TEXT_IME_DIGITAL_VERB (`输入`, `补全`, `识别`, `打字`) -> ArtifactObj, TechNoun (`补全 句子`, `输入 内容`), UsabilityAdj (`打字 太快`), Struct, FinalPart, Quant
    for td, v in [(10, 0.95), (14, 0.75), (15, 0.75), (19, 1.20), (22, 0.75), (24, 0.85), (26, 0.65), (29, 0.80), (30, -1.45)]:
        set_trans(18, td, v)
    # 19: TECH_TEXT_COMM_NOUN (`语义`, `本地模型`, `输入法`, `消息`) -> Motion (`语义 来`), Modal, SpeedAdv (`模型 自动`), ImeVerb (`模型 识别`), Usability (`输入法 很好用`), HowWh (`输入法 怎么样`), Struct, FinalPart
    for td, v in [(3, 0.75), (5, 0.75), (13, 0.70), (14, 0.75), (15, 0.75), (17, 0.95), (18, 1.05), (19, 0.80), (24, 1.05), (25, 1.15), (29, -0.65), (30, -1.40)]:
        set_trans(19, td, v)
    # 20: GREETING_APOLOGY_POLITE (`你好`, `不好意思`) -> Subj (`不好意思 我`), Time (`不好意思 刚刚`), Arrival (`不好意思 刚睡醒`), Percept (`不好意思 没看到`), FinalPart (`你好 吗`), Polite
    for td, v in [(0, 0.95), (1, 0.90), (13, 0.75), (15, 0.95), (20, 0.75), (21, 1.05), (22, 0.95), (23, 0.80), (30, -1.45)]:
        set_trans(20, td, v)
    # 21: ARRIVAL_POSTURE_TRANSIT (`刚到`, `刚睡醒`, `坐地铁`) -> Loc (`刚到 地下`, `刚到 公司`), Motion (`坐地铁 去`), Adv (`刚睡醒 没`), Percept (`刚睡醒 没看到`), FinalPart
    for td, v in [(2, 1.15), (5, 0.95), (6, 0.70), (13, 0.85), (14, 0.65), (15, 0.80), (22, 1.10), (30, -1.35)]:
        set_trans(21, td, v)
    # 22: PERCEPT_ACQUIRE_RESULT (`没看到`, `收到`, `忙完了`) -> Subj (`没看到 你`), ArtifactObj (`收到 消息`), TechNoun (`没看到 消息`), Possessive (`没看到 你的`), FinalPart
    for td, v in [(0, 0.85), (10, 1.10), (14, 0.75), (15, 0.90), (19, 1.05), (26, 0.95), (29, 0.75), (30, -1.35)]:
        set_trans(22, td, v)
    # 23: SOCIAL_CAUSATIVE_BENEF (`我来`, `帮我`, `一起`, `一起去`) -> Motion (`一起 去`), Ingest (`一起 吃火锅`), TransVerb, Tentative (`我来 试试`, `帮我 看看`), SpeedAdv, ImeVerb, DetQuant
    for td, v in [(5, 1.05), (6, 1.15), (7, 1.00), (16, 1.35), (17, 0.85), (18, 0.95), (29, 0.85), (30, -1.45)]:
        set_trans(23, td, v)
    # 24: USABILITY_FLUENCY_ADJ (`很好用`, `流畅`, `太快`) -> Struct (`的`, `了`), FinalPart (`啊`, `吧`), Discourse
    for td, v in [(14, 0.85), (15, 0.90), (28, 0.65), (30, -1.30)]:
        set_trans(24, td, v)
    # 25: HOW_WHY_OBLIGATION_WH (`怎么办`, `怎么样`) -> Modal, Motion, TransVerb, FinalPart (`怎么办 呢`, `怎么办 啊`)
    for td, v in [(3, 0.65), (5, 0.60), (7, 0.65), (15, 1.05), (30, -1.35)]:
        set_trans(25, td, v)
    # 26: POSSESSIVE_REL_MOD (`我的`, `你的`, `的时候`) -> Subj, ArtifactObj (`你的 消息`), TechNoun, Modal, Adv
    for td, v in [(0, 0.65), (3, 0.65), (10, 1.10), (13, 0.65), (19, 1.05), (28, 0.70), (30, -1.30)]:
        set_trans(26, td, v)
    # 27: PREPOSITIONAL_BASIS (`根据`, `通过`, `按照`) -> ArtifactObj, TechNoun (`根据 语义`, `通过 本地模型`), Possessive, DetQuant (`通过 这个`)
    for td, v in [(10, 1.05), (19, 1.40), (26, 0.80), (29, 0.95), (30, -1.45)]:
        set_trans(27, td, v)
    # 28: DISCOURSE_COND_CAUSE (`而且`, `同时`, `因为`, `所以`) -> Subj, Time, Modal, Adv, SpeedAdv (`而且 无延迟`), ImeVerb (`同时 叠加`), Usability
    for td, v in [(0, 0.85), (1, 0.75), (3, 0.85), (13, 0.90), (14, 0.55), (17, 1.05), (18, 0.95), (24, 0.85), (30, -1.35)]:
        set_trans(28, td, v)
    # 29: DET_QUANT_CL (`这个`, `那个`, `这种`, `一个`, `一下`) -> Time (`这个 时候`), FoodObj, ArtifactObj (`这个 问题`), FinalPart, TechNoun (`这个 输入法`), UsabilityAdj, HowWh (`这个 怎么样`); penalize bare Struct (`*这个 了`)
    for td, v in [(1, 0.65), (9, 0.85), (10, 1.25), (15, 0.80), (19, 1.30), (24, 0.95), (25, 1.05), (14, -0.65), (30, -1.35)]:
        set_trans(29, td, v)
    # 30: ACCIDENTAL_TYPO_SINGLETON (`亏`, `素`, `恩`, `奥`, `欧`) -> penalize chaining into another singleton (`*亏 素`) or IME/action predicates (`*素 输入`)
    for td, v in [(5, -0.85), (6, -0.95), (7, -0.85), (16, -1.10), (17, -1.20), (18, -1.35), (19, -1.10), (30, -1.55)]:
        set_trans(30, td, v)
    # 31: LEXICAL_MULTIWORD_FLOW -> mild positive multi-word phrase continuity
    set_trans(31, 31, 0.24)

    # Step 3: Corpus Co-occurrence Spectral Propagation over `assoc_map`
    # Smooth word embeddings so words that co-occur in real Chinese phrases align in our 32-D neural space
    ctx_deltas: dict[str, list[float]] = {w: [0.0] * LNLM_DIM for w in sorted_lnlm_base}
    tgt_deltas: dict[str, list[float]] = {w: [0.0] * LNLM_DIM for w in sorted_lnlm_base}
    ctx_counts: dict[str, float] = defaultdict(float)
    tgt_counts: dict[str, float] = defaultdict(float)

    for pref, conts in spectral_assoc_map.items():
        if pref not in lnlm_word_set:
            continue
        p_ctx = word_ctx_vecs[pref]
        for cont, sc in conts.items():
            if cont not in lnlm_word_set:
                continue
            w_norm = min(1.0, sc / 1800.0)
            c_tgt = word_tgt_vecs[cont]
            # Project `p_ctx` forward through `b_direct` to nudge `c_tgt`, and `c_tgt` backward through `b_direct^T` to nudge `p_ctx`
            for j in range(LNLM_DIM):
                if j == 30:
                    continue
                fwd_j = sum(b_direct[j][i] * p_ctx[i] for i in range(LNLM_DIM))
                tgt_deltas[cont][j] += w_norm * fwd_j
            for i in range(LNLM_DIM):
                if i == 30:
                    continue
                bwd_i = sum(b_direct[j][i] * c_tgt[j] for j in range(LNLM_DIM))
                ctx_deltas[pref][i] += w_norm * bwd_i
            ctx_counts[pref] += w_norm
            tgt_counts[cont] += w_norm

    sorted_lnlm_base = sorted(lnlm_word_set)
    for w in sorted_lnlm_base:
        if w in composite_overrides:
            continue
        cc = ctx_counts.get(w, 0.0)
        if cc > 0.0:
            cv = word_ctx_vecs[w]
            dl = ctx_deltas[w]
            for k in range(LNLM_DIM):
                if k == 30:
                    continue
                cv[k] = 0.82 * cv[k] + 0.18 * (dl[k] / cc)
        tc = tgt_counts.get(w, 0.0)
        if tc > 0.0:
            tv = word_tgt_vecs[w]
            dl = tgt_deltas[w]
            for k in range(LNLM_DIM):
                if k == 30:
                    continue
                tv[k] = 0.82 * tv[k] + 0.18 * (dl[k] / tc)

    # Step 3b: Reverse-project trained multi-char word vectors (`word_ctx_vecs`/`word_tgt_vecs`)
    # back onto unseeded 8,105 canonical characters + frequency-backed semantic priors so `char_emb`
    # covers > 95% of 8,105 BMP characters without all-zero dead embeddings.
    proj_char_ctx: dict[str, list[float]] = {}
    proj_char_tgt: dict[str, list[float]] = {}
    proj_char_w: dict[str, float] = defaultdict(float)

    sorted_lnlm_base = sorted(lnlm_word_set)
    for w in sorted_lnlm_base:
        if len(w) < 2 or w in composite_overrides:
            continue
        w_log = math.log10(max(word_max_w.get(w, 10.0), 1.0) + 1.0)
        w_cv = word_ctx_vecs[w]
        w_tv = word_tgt_vecs[w]
        if all(abs(x) < 1e-6 for x in w_cv) and all(abs(x) < 1e-6 for x in w_tv):
            continue
        w_len = len(w)
        for pos, ch in enumerate(w):
            if not (0x4E00 <= ord(ch) < 0xA000):
                continue
            tgt_wt = w_log * (1.0 if pos == 0 else 0.55)
            ctx_wt = w_log * (1.0 if pos == w_len - 1 else 0.55)
            pc = proj_char_ctx.get(ch)
            if pc is None:
                pc = [0.0] * LNLM_DIM
                proj_char_ctx[ch] = pc
            pt = proj_char_tgt.get(ch)
            if pt is None:
                pt = [0.0] * LNLM_DIM
                proj_char_tgt[ch] = pt
            for k in range(LNLM_DIM):
                if k == 30:
                    continue
                pc[k] += ctx_wt * w_cv[k]
                pt[k] += tgt_wt * w_tv[k]
            proj_char_w[ch] += w_log

    # Secondary propagation for remaining 8,105 BMP characters via co-occurring characters in multi-char entries.
    for txt, rw in word_max_w.items():
        if len(txt) < 2 or not all(0x4E00 <= ord(c) < 0xA000 for c in txt):
            continue
        missing = [c for c in txt if c in chars_8105 and c not in proj_char_w]
        if not missing:
            continue
        donors = [c for c in txt if c in char_ctx_vecs and c not in missing]
        if not donors:
            continue
        w_log = math.log10(max(rw, 1.0) + 1.0)
        for mc in missing:
            pc = proj_char_ctx.setdefault(mc, [0.0] * LNLM_DIM)
            pt = proj_char_tgt.setdefault(mc, [0.0] * LNLM_DIM)
            for dc in donors:
                d_cv = char_ctx_vecs[dc]
                d_tv = char_tgt_vecs[dc]
                for k in range(LNLM_DIM):
                    if k == 30:
                        continue
                    pc[k] += w_log * d_cv[k]
                    pt[k] += w_log * d_tv[k]
                proj_char_w[mc] += w_log

    def _is_quantized_zero(vec: list[float]) -> bool:
        return not any(int(round(v * 32.0)) != 0 for v in vec)

    chars_8105_bmp = sorted(ch for ch in chars_8105 if len(ch) == 1 and 0x4E00 <= ord(ch) < 0xA000)
    for ch in chars_8105_bmp:
        if ch in composite_overrides:
            continue
        cv, tv = ensure_char_vec(ch)
        pw = proj_char_w.get(ch, 0.0)
        freq_norm = min(1.0, math.log10(max(char_freq.get(ch, 0.5), 0.5) + 1.0) / 6.0)
        if _is_quantized_zero(cv):
            if pw > 0.0:
                pc = proj_char_ctx[ch]
                for k in range(LNLM_DIM):
                    if k != 30:
                        cv[k] = 0.15 * (pc[k] / pw)
            if _is_quantized_zero(cv):
                cv[10] = 0.12 + 0.14 * freq_norm
                cv[31] = 0.08 + 0.08 * freq_norm
        if _is_quantized_zero(tv):
            if pw > 0.0:
                pt = proj_char_tgt[ch]
                for k in range(LNLM_DIM):
                    if k != 30:
                        tv[k] = 0.15 * (pt[k] / pw)
            if _is_quantized_zero(tv):
                tv[10] = 0.12 + 0.14 * freq_norm
                tv[31] = 0.08 + 0.08 * freq_norm

    nonzero_8105_bmp = sum(
        1 for ch in chars_8105_bmp
        if not _is_quantized_zero(char_ctx_vecs[ch]) and not _is_quantized_zero(char_tgt_vecs[ch])
    )
    print(
        f"    8,105 BMP non-zero char_emb coverage: {nonzero_8105_bmp:,}/{len(chars_8105_bmp):,} "
        f"({nonzero_8105_bmp * 100.0 / max(1, len(chars_8105_bmp)):.2f}%)"
    )

    # Step 4: Configure the 2-layer Recurrent SiLU MLP (`W_ctx`, `W_rec`, `b_1`, `W_proj`, `B_skip`, `b_2`, `W_char`)
    # Hidden units `z[0..31]` detect multi-word sentence frames combining `h_{m-1}` (recurrent history) and `v_ctx(w_{m-1})`:
    w_ctx = [[0.0] * LNLM_DIM for _ in range(LNLM_DIM)]
    w_rec = [[0.0] * LNLM_DIM for _ in range(LNLM_DIM)]
    b_1 = [-0.20] * LNLM_DIM
    w_proj = [[0.0] * LNLM_DIM for _ in range(LNLM_DIM)]
    b_skip = [[0.0] * LNLM_DIM for _ in range(LNLM_DIM)]
    b_2 = [0.0] * LNLM_DIM

    for k in range(LNLM_DIM):
        w_ctx[k][k] = 0.55
        w_rec[k][k] = 0.45

    # Unit 0: `想起来 (h:4) + 明天 (ctx:1) -> 吃什么 (tgt:6,8)`
    w_rec[0][4] = 1.15
    w_ctx[0][1] = 1.15
    b_1[0] = -0.35
    w_proj[6][0] = 1.08
    w_proj[8][0] = 0.85
    w_proj[9][0] = -0.85
    w_proj[11][0] = -1.15
    w_proj[12][0] = -0.85

    # Unit 1: `我/一会/要 (h:0,1,3) + 出去 (ctx:5) -> 买饭/吃饭 (tgt:6,7)`
    w_rec[1][0] = 0.65
    w_rec[1][1] = 0.65
    w_rec[1][3] = 0.85
    w_ctx[1][5] = 1.10
    b_1[1] = -0.35
    w_proj[6][1] = 0.95
    w_proj[7][1] = 0.65
    w_proj[9][1] = 0.45
    w_proj[11][1] = -0.95

    # Unit 2: `今天/我们 (h:0,1) + 去哪 (ctx:5,8) -> 吃饭 (tgt:6)`
    w_rec[2][0] = 0.75
    w_rec[2][1] = 0.75
    w_ctx[2][5] = 0.85
    w_ctx[2][8] = 0.95
    w_ctx[2][14] = -0.85  # Penalize demonstrative `去那` (`ctx:14`) when predicting `吃饭`
    b_1[2] = -0.30
    w_proj[6][2] = 0.95
    w_proj[15][2] = 0.65

    # Unit 3: `想起来 (ctx:4)` clause-opening frame -> strongly prefers `明天/今天 (tgt:1)` or `Subj (tgt:0)` over bare `面条 (tgt:9)` / `腼腆 (tgt:12)`
    w_ctx[3][4] = 1.20
    w_rec[3][0] = 0.50
    b_1[3] = -0.25
    w_proj[1][3] = 0.85
    w_proj[0][3] = 0.55
    w_proj[9][3] = -0.55
    w_proj[12][3] = -0.75
    w_proj[11][3] = -0.95

    # Unit 16: `我来/我去 (h:0,5,23) + 试试/看看 (ctx:16) -> 快速/快速输入/自动补全/输入法 (tgt:17,18,19)` and reject `*亏 素 (tgt:30)`
    w_rec[16][0] = 0.65
    w_rec[16][23] = 0.95
    w_ctx[16][16] = 1.25
    b_1[16] = -0.30
    w_proj[17][16] = 1.05
    w_proj[18][16] = 0.95
    w_proj[19][16] = 0.75
    w_proj[30][16] = -1.25

    # Unit 17: `[试试/根据语义/本地模型 (h:16,19,27)] + [快速/自动/无延迟 (ctx:17)] -> 输入/补全/识别 (tgt:18)`
    w_rec[17][16] = 0.85
    w_rec[17][19] = 0.85
    w_rec[17][27] = 0.85
    w_ctx[17][17] = 1.25
    b_1[17] = -0.30
    w_proj[18][17] = 1.15
    w_proj[19][17] = 0.65
    w_proj[30][17] = -1.25

    # Unit 18: `[根据/通过 (h:27)] + [语义/本地模型 (ctx:19)] -> 来/快速/自动/补全 (tgt:5,17,18)`
    w_rec[18][27] = 1.10
    w_ctx[18][19] = 1.20
    b_1[18] = -0.30
    w_proj[17][18] = 0.95
    w_proj[18][18] = 1.05
    w_proj[5][18] = 0.70
    w_proj[30][18] = -1.15

    # Unit 19: `[看看/试试/觉得/知道 (h:4,16) + 这个/那个 (h:29)] + [输入法/模型/问题/方案 (ctx:10,19,29)] -> 怎么样/好用/不错 (tgt:24,25)`
    w_rec[19][16] = 0.85
    w_rec[19][4] = 0.75
    w_rec[19][29] = 0.85
    w_ctx[19][19] = 1.15
    w_ctx[19][10] = 1.05
    w_ctx[19][29] = 0.85
    b_1[19] = -0.30
    w_proj[25][19] = 1.10
    w_proj[24][19] = 1.05
    w_proj[18][19] = 0.75
    w_proj[15][19] = 1.25
    w_proj[3][19] = -0.85
    w_proj[30][19] = -1.20

    # Unit 20: `[不好意思 (h:20)] + [刚睡醒/刚刚 (ctx:1,21)] -> 没看到/消息 (tgt:13,22,19)`
    w_rec[20][20] = 1.15
    w_ctx[20][21] = 1.10
    w_ctx[20][1] = 0.75
    b_1[20] = -0.30
    w_proj[22][20] = 1.05
    w_proj[13][20] = 0.75
    w_proj[19][20] = 0.75

    # Unit 21: `[今天晚上/明天 (h:1) + 我们/一起去 (ctx:0,5,23)] -> 吃饭/吃火锅/吃什么 (tgt:6,9)`
    w_rec[21][1] = 0.95
    w_ctx[21][23] = 1.05
    w_ctx[21][5] = 0.85
    b_1[21] = -0.30
    w_proj[6][21] = 1.05
    w_proj[9][21] = 0.75

    # Unit 22: `[我/你/帮我 (h:0,23)] + [看看/试试/觉得 (ctx:4,16)] -> [这个/那个/输入法/问题 (tgt:10,19,29)]`, rejecting bare `ADJ_STATE (tgt:12)`
    w_rec[22][0] = 0.70
    w_rec[22][23] = 0.80
    w_ctx[22][16] = 1.20
    w_ctx[22][4] = 0.85
    b_1[22] = -0.25
    w_proj[29][22] = 1.05
    w_proj[19][22] = 0.85
    w_proj[10][22] = 0.80
    w_proj[12][22] = -0.85
    w_proj[30][22] = -1.20

    # Unit 23: `[你/我们 (h:0) + 什么 (h:8)] + [时候/时间/几点 (ctx:1,10,25)] -> [过来/回去/吃饭/下班 (tgt:5,6,21)]`
    w_rec[23][0] = 0.85
    w_rec[23][8] = 0.85
    w_ctx[23][1] = 1.05
    w_ctx[23][10] = 0.85
    w_ctx[23][25] = 0.85
    b_1[23] = -0.30
    w_proj[5][23] = 0.95
    w_proj[6][23] = 0.85
    w_proj[21][23] = 0.85
    w_proj[11][23] = -1.05
    w_proj[30][23] = -1.20

    # Unit 24: `[我/我们/现在/今天 (h:0,1)] + [出去/出来/过去/去 (ctx:5)] -> [吃饭/买饭/看看/一下 (tgt:6,7,16,29)]`
    w_rec[24][0] = 0.75
    w_rec[24][1] = 0.90
    w_ctx[24][5] = 1.15
    b_1[24] = -0.30
    w_proj[6][24] = 0.95
    w_proj[16][24] = 0.95
    w_proj[7][24] = 0.75
    w_proj[30][24] = -1.20

    # Long-range recurrent skip connections `B_skip[tgt_dim][hidden_dim]`
    b_skip[6][4] = 0.45    # Cognitive verb in history (`想起来`) -> boosts ingestion predicate (`吃什么`)
    b_skip[8][4] = 0.45    # Cognitive verb in history (`想起来`) -> boosts embedded wh-question (`什么`)
    b_skip[6][1] = 0.45    # Time adverbial in history (`今天`, `明天`, `一会`) -> boosts ingestion verb (`吃`, `吃饭`, `买饭`)
    b_skip[6][0] = 0.35    # Subject pronoun in history (`我`, `我们`) -> boosts action/ingestion predicate
    b_skip[5][1] = 0.35    # Time adverbial in history -> boosts motion verb (`去`, `出去`)
    b_skip[11][4] = -0.65  # Penalize stray single-char linguistic noun (`词`) inside cognitive clause
    b_skip[11][1] = -0.65  # Penalize stray single-char linguistic noun (`词`) after time adverbial
    b_skip[18][16] = 0.45  # Tentative verb in history (`试试`) -> boosts IME/digital action (`输入`, `补全`)
    b_skip[25][16] = 0.45  # Tentative verb in history (`看看`, `试试`) -> boosts evaluative wh-predicate (`怎么样`)
    b_skip[19][29] = 0.45  # Determiner in history (`这个`) -> boosts tech/communication noun (`输入法`, `模型`)
    b_skip[25][29] = 0.40  # Determiner in history (`这个`) -> boosts evaluative wh-predicate (`怎么样`)
    b_skip[18][27] = 0.45  # Prepositional basis in history (`根据`, `通过`) -> boosts completion/action (`补全`)
    b_skip[18][19] = 0.40  # Tech/semantic noun in history (`语义`, `模型`) -> boosts completion/action (`补全`, `输入`)
    b_skip[22][20] = 0.45  # Apology/polite frame in history (`不好意思`) -> boosts perception/result (`没看到`, `来晚了`)
    b_skip[30][0] = -0.55  # Penalize accidental singleton characters (`亏`, `素`) across pronoun-led sentences
    b_skip[30][16] = -0.65 # Penalize accidental singleton characters after tentative verbs (`试试`)

    # Character boundary transition matrix `W_char[tgt_dim][ctx_dim]` (`0.65 * B_direct`)
    w_char = [[0.65 * b_direct[r][c] for c in range(LNLM_DIM)] for r in range(LNLM_DIM)]

    alpha_vec = [0.55] * 16 + [0.58] * 16
    h_bos_vec = [0.25, 0.15] + [0.0] * 30
    w_eos_vec = [
        0.10, 0.10, 0.15, -0.25, 0.15, 0.15, 0.45, 0.35,
        0.55, 0.45, 0.40, -0.60, 0.35, -0.35, -0.25, 0.65,
        0.35, -0.20, 0.45, 0.35, 0.35, 0.25, 0.45, -0.15,
        0.45, 0.55, -0.25, -0.35, -0.25, 0.35, -0.65, 0.15,
    ]
    u_eos_vec = [
        0.05, -0.15, 0.25, -0.95, 0.10, 0.20, 0.75, 0.45,
        0.95, 0.85, 0.75, -0.95, 0.65, -1.05, -0.65, 1.25,
        0.55, -0.55, 0.75, 0.55, 0.65, 0.35, 0.75, -0.45,
        0.80, 0.95, -0.55, -0.85, -0.65, 0.55, -1.05, 0.20,
    ]

    def quantize_vec32(vec: list[float]) -> bytes:
        # Int8 quantization with scale = 32.0 (`[-127, 127]` -> `[-3.97, +3.97]`)
        q = [max(-127, min(127, int(round(v * 32.0)))) for v in vec]
        return struct.pack("<32b", *q)

    # Sort characters in 0x4E00..<0xA000 and build `char_map` (`20,992 * UInt16`) + `char_emb` (`(cCount + 1) * 64` bytes)
    sorted_chars = sorted(ch for ch in char_ctx_vecs.keys() if len(ch) == 1 and 0x4E00 <= ord(ch) < 0xA000)
    char_map_arr = [0] * 20992
    char_emb_buf = bytearray(64)  # cid 0 = zero 32-dim (ctx, tgt) vector pair
    for idx, ch in enumerate(sorted_chars, start=1):
        code = ord(ch) - 0x4E00
        char_map_arr[code] = idx
        char_emb_buf.extend(quantize_vec32(char_ctx_vecs[ch]))
        char_emb_buf.extend(quantize_vec32(char_tgt_vecs[ch]))
    char_map_bytes = struct.pack(f"<{len(char_map_arr)}H", *char_map_arr)

    # Sort `lnlm_word_set` strictly by unsigned UTF-8 byte order and intern into `string_pool` BEFORE `string_pool` is written
    # Only the output embedding changes. The recurrent state, 32-dimension SIMD
    # representation and lexical frequency prior remain compatible with LNLM v2.
    learned_targets = {}
    if os.environ.get("LOKEY_SKIP_TARGET_DELTAS") != "1":
        for line in (data_dir / "target-deltas.tsv").read_text(encoding="utf-8").splitlines():
            if "\t" not in line:
                continue
            word, encoded = line.split("\t")
            delta = struct.unpack("<32b", bytes.fromhex(encoded))
            if word in learned_targets or delta[30:] != (0, 0):
                raise ValueError(f"Invalid LNLM residual for {word}")
            learned_targets[word] = delta
    sorted_lnlm_words = sorted(lnlm_word_set, key=lambda s: s.encode("utf-8"))
    if not learned_targets.keys() <= lnlm_word_set:
        raise ValueError("LNLM residuals do not match the seed vocabulary")
    word_table_buf = bytearray()
    for w in sorted_lnlm_words:
        s_off, s_len = intern_str(w)
        word_table_buf.extend(struct.pack("<IHH", s_off, s_len, 0))
        word_table_buf.extend(quantize_vec32(word_ctx_vecs[w]))
        target = quantize_vec32(word_tgt_vecs[w])
        if w in learned_targets:
            old = struct.unpack("<32b", target)
            target = struct.pack("<32b", *(max(-127, min(127, a + b)) for a, b in zip(old, learned_targets[w])))
        word_table_buf.extend(target)

    # Pack 25,344 bytes of 32x32 Float32 MLP & bilinear weights
    mlp_buf = bytearray()
    for mat in (w_ctx, w_rec):
        for row in mat:
            mlp_buf.extend(struct.pack("<32f", *row))
    mlp_buf.extend(struct.pack("<32f", *b_1))
    for mat in (w_proj, b_direct, b_skip):
        for row in mat:
            mlp_buf.extend(struct.pack("<32f", *row))
    mlp_buf.extend(struct.pack("<32f", *b_2))
    for row in w_char:
        mlp_buf.extend(struct.pack("<32f", *row))
    for vec in (alpha_vec, h_bos_vec, w_eos_vec, u_eos_vec):
        mlp_buf.extend(struct.pack("<32f", *vec))
    assert len(mlp_buf) == 25344, f"Expected 25344 MLP bytes, got {len(mlp_buf)}"

    contrastive_word_count = len(learned_targets)
    if bb_loaded:
        frost_cid_by_char = {ch: idx for idx, ch in enumerate(sorted_chars, start=1)}
        for bb_cid, ch in enumerate(bb_chars, start=1):
            frost_cid = frost_cid_by_char[ch]
            bb_off = bb_cid * 64
            frost_off = frost_cid * 64
            if bb_char_emb[bb_off + 30] != char_emb_buf[frost_off + 30]:
                raise ValueError(f"LNLM backbone mutated char_ctx[30] for '{ch}' (bb_cid={bb_cid}, frost_cid={frost_cid})")
            if bb_char_emb[bb_off + 62] != char_emb_buf[frost_off + 62]:
                raise ValueError(f"LNLM backbone mutated char_tgt[30] for '{ch}' (bb_cid={bb_cid}, frost_cid={frost_cid})")
            char_emb_buf[frost_off : frost_off + 64] = bb_char_emb[bb_off : bb_off + 64]

        mlp_floats = struct.unpack("<6336f", bb_mlp)
        for idx, fv in enumerate(mlp_floats):
            if not math.isfinite(fv) or abs(fv) > 1.0e5:
                raise ValueError(f"LNLM backbone non-finite/huge float at index {idx}: {fv}")
        if bb_mlp[-512:] != bytes(mlp_buf[-512:]):
            raise ValueError("LNLM backbone mutated frozen (alpha, h_bos, w_eos, u_eos) vectors")
        mlp_buf = bytearray(bb_mlp)

        applied_word_overrides = {w: vec for w, vec in bb_word_overrides.items() if w in lnlm_word_set}
        rebuilt_word_buf = bytearray()
        for w in sorted_lnlm_words:
            s_off, s_len = intern_str(w)
            rebuilt_word_buf.extend(struct.pack("<IHH", s_off, s_len, 0))
            base_ctx = quantize_vec32(word_ctx_vecs[w])
            base_tgt = quantize_vec32(word_tgt_vecs[w])
            if w in applied_word_overrides:
                ov = applied_word_overrides[w]
                if ov[30] != base_ctx[30] or ov[62] != base_tgt[30]:
                    raise ValueError(f"LNLM backbone mutated dim[30] for word {w}")
                rebuilt_word_buf.extend(ov)
            else:
                if w in learned_targets:
                    old = struct.unpack("<32b", base_tgt)
                    base_tgt = struct.pack(
                        "<32b", *(max(-127, min(127, a + b)) for a, b in zip(old, learned_targets[w]))
                    )
                rebuilt_word_buf.extend(base_ctx)
                rebuilt_word_buf.extend(base_tgt)
        word_table_buf = rebuilt_word_buf
        contrastive_word_count = max(contrastive_word_count, len(applied_word_overrides))
        print(
            f"    Applied end-to-end distilled LNLM v2 backbone ({len(bb_chars):,} chars mapped, "
            f"{len(applied_word_overrides):,} word overrides, 25,344B MLP)."
        )

    print(
        f"    Trained LNLM v2 neural model: {len(sorted_chars):,} chars, "
        f"{len(sorted_lnlm_words):,} words, {len(mlp_buf):,} bytes 32-dim SIMD MLP weights."
    )

    print("==> [4/5] Serializing LKLF v2 binary image...")
    buf = bytearray(72)  # Reserve 72-byte header (18 * uint32, 8-byte aligned)

    # Section 1: Syllables (16 bytes * (N + 1))
    syllable_offset = len(buf)
    buf.extend(b"\x00" * 16)  # Index 0 reserved
    for s in sorted_syllables:
        sb = s.encode("ascii")
        padded = sb + b"\x00" * (8 - len(sb))
        init_ascii = sb[0]
        init_group = init_ascii - ord("a") + 1
        if s.startswith(("zh", "ch", "sh")):
            init_group |= 0x100
        buf.extend(struct.pack("<8sBBHI", padded, init_ascii, len(sb), init_group, 0))
    align8(buf)

    # Section 2: Trie Nodes (`<IHHIhH` = 16 bytes each)
    edge_records: list[tuple[int, int, int]] = []
    word_records: list[tuple[int, int, int]] = []
    node_offset = len(buf)
    for node in flat_nodes:
        first_edge = len(edge_records)
        sorted_sids = sorted(node.children.keys())
        for sid in sorted_sids:
            syl_str = sorted_syllables[sid - 1]
            edge_records.append((sid, ord(syl_str[0]), node.children[sid].flat_index))
        first_word = len(word_records)
        word_records.extend(node.words)
        buf.extend(
            struct.pack(
                "<IHHIhH",
                first_edge,
                len(sorted_sids),
                len(node.words),
                first_word,
                max(-32768, min(32767, node.max_subtree_score)),
                min(65535, node.depth),
            )
        )
    align8(buf)

    edge_offset = len(buf)
    for sid, init_b, target_idx in edge_records:
        buf.extend(struct.pack("<HBBI", sid, init_b, 0, target_idx))
    align8(buf)

    word_offset = len(buf)
    for s_off, s_len, score_q8 in word_records:
        buf.extend(struct.pack("<IHh", s_off, s_len, score_q8))
    align8(buf)

    jianpin_offset = len(buf)
    for code_be, s_off, s_len, score_q8 in final_jianpin:
        # Big-endian 8-byte key + LE offset/len/score = 16 bytes
        buf.extend(struct.pack(">Q", code_be))
        buf.extend(struct.pack("<IHh", s_off, s_len, score_q8))
    align8(buf)

    english_offset = len(buf)
    for l_off, d_off, l_len, d_len, score_q8 in final_english:
        buf.extend(struct.pack("<IIHHhH", l_off, d_off, l_len, d_len, score_q8, 0))
    align8(buf)

    assoc_offset = len(buf)
    for k_off, v_off, k_len, v_len, sc, rank_i in final_assoc:
        buf.extend(struct.pack("<IIHHhH", k_off, v_off, k_len, v_len, sc, rank_i))
    align8(buf)

    string_pool_offset = len(buf)
    string_pool_size = len(string_pool)
    buf.extend(string_pool)
    align8(buf)

    # Write 72-byte LKLF v2 header
    header = struct.pack(
        "<18I",
        0x464C4B4C,  # "LKLF"
        2,           # version 2 (adds zero-copy association/bigram table)
        len(sorted_syllables),
        syllable_offset,
        len(flat_nodes),
        node_offset,
        len(edge_records),
        edge_offset,
        len(word_records),
        word_offset,
        len(final_jianpin),
        jianpin_offset,
        len(final_english),
        english_offset,
        string_pool_size,
        string_pool_offset,
        len(final_assoc),
        assoc_offset,
    )
    buf[0:72] = header

    # Append On-Device Neural Language Model (`LNLM v2`) section + 16-byte footer
    lnlm_offset = len(buf)
    buf.extend(b"\x00" * 32)  # Reserve 32-byte LNLM header (`<8I`)
    c_map_off = len(buf)
    buf.extend(char_map_bytes)
    align8(buf)
    c_emb_off = len(buf)
    buf.extend(char_emb_buf)
    align8(buf)
    w_tab_off = len(buf)
    buf.extend(word_table_buf)
    align8(buf)
    mlp_off = len(buf)
    buf.extend(mlp_buf)
    align8(buf)
    lnlm_size = len(buf) - lnlm_offset

    lnlm_header = struct.pack(
        "<8I",
        0x4D4C4E4C,  # "LNLM"
        LNLM_DIM,    # 32-dim SIMD embedding dimension
        len(sorted_chars),
        c_map_off,
        c_emb_off,
        len(sorted_lnlm_words),
        w_tab_off,
        mlp_off,
    )
    buf[lnlm_offset : lnlm_offset + 32] = lnlm_header

    # 16-byte LNLM v2 trailer at `data.count - 16`
    buf.extend(struct.pack("<4I", 0x4D4C4E4C, 2, lnlm_offset, lnlm_size))

    output_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_bin = output_path.parent / f".{output_path.name}.{os.getpid()}.tmp"
    try:
        tmp_bin.write_bytes(buf)
        os.replace(tmp_bin, output_path)
    except Exception:
        tmp_bin.unlink(missing_ok=True)
        raise

    sha256_hex = hashlib.sha256(buf).hexdigest()
    if sha256_path is not None:
        sha256_path.parent.mkdir(parents=True, exist_ok=True)
        tmp_sha = sha256_path.parent / f".{sha256_path.name}.{os.getpid()}.tmp"
        try:
            tmp_sha.write_text(f"{sha256_hex}  {output_path.name}\n", encoding="utf-8")
            os.replace(tmp_sha, sha256_path)
        except Exception:
            tmp_sha.unlink(missing_ok=True)
            raise

    try:
        commit_sha = subprocess.check_output(
            ["git", "-C", str(frost_dir), "rev-parse", "HEAD"], text=True
        ).strip()
        commit_date = subprocess.check_output(
            ["git", "-C", str(frost_dir), "log", "-1", "--format=%cs"], text=True
        ).strip()
    except Exception:
        commit_sha = "unknown"
        commit_date = "unknown"

    manifest = {
        "format": "LKLF-v2+LNLM-v2",
        "upstream": "https://github.com/gaboolic/rime-frost",
        "license": "GPL-3.0",
        "upstream_commit": commit_sha,
        "upstream_date": commit_date,
        "syllables": len(sorted_syllables),
        "trie_nodes": len(flat_nodes),
        "trie_edges": len(edge_records),
        "chinese_words": len(word_records),
        "jianpin_entries": len(final_jianpin),
        "english_entries": len(final_english),
        "association_entries": len(final_assoc),
        "neural_lm_chars": len(sorted_chars),
        "neural_lm_words": len(sorted_lnlm_words),
        "neural_lm_contrastive_words": contrastive_word_count,
        "neural_lm_commit_pairs": sum(len(pairs) for pairs in commit_index.values()),
        "neural_lm_training_treebank": "UD_Chinese-GSDSimp r2.16",
        "neural_lm_attribution": "Target residuals adapted by Lokey from UD Chinese GSDSimp (Peng Qi, Koichi Yasuoka and GSD contributors).",
        "neural_lm_training_source": "https://github.com/UniversalDependencies/UD_Chinese-GSDSimp/tree/9b1fc1d388b8f4ac7cf12a704995618571454b80",
        "neural_lm_residual_license": "https://creativecommons.org/licenses/by-sa/4.0/",
        "neural_lm_bytes": lnlm_size + 16,
        "binary_bytes": len(buf),
        "binary_mb": round(len(buf) / (1024 * 1024), 2),
        "sha256": sha256_hex,
    }
    if args.manifest is not None:
        args.manifest.parent.mkdir(parents=True, exist_ok=True)
        tmp_manifest = args.manifest.parent / f".{args.manifest.name}.{os.getpid()}.tmp"
        try:
            tmp_manifest.write_text(
                json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
            )
            os.replace(tmp_manifest, args.manifest)
        except Exception:
            tmp_manifest.unlink(missing_ok=True)
            raise

    print(f"==> [5/5] Done! Wrote {output_path} ({len(buf):,} bytes, sha256={sha256_hex})")
    if sha256_path is not None:
        print(f"    Checksum: {sha256_path}")
    print(json.dumps(manifest, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
