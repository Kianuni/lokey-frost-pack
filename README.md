# lokey-frost-pack

[中文说明](#中文说明) | [English](#english)

---

<a id="中文说明"></a>

## 中文说明

`lokey-frost-pack` 是面向 **Lokey** iOS 26 键全拼与小鹤/自然码双拼输入法提供的**纯离线外部词库包与独立开源编译器仓库**。

### 1. 项目定位与上游关系

- **词典底座（致敬开源上游）**：本项目的中文词汇表、多音字注音与基础词频底座源自开源项目 [`gaboolic/rime-frost`](https://github.com/gaboolic/rime-frost)（白霜词库，承袭雾凇拼音体系），固定基线提交 `7c8a908a92fa67fe1be9279b523b3cf95366e27d`（`2026-11-09`）。白霜词库提供了扎实的现代汉语词表覆盖、字音校勘与基础词频，特此向上游作者与社区贡献者致谢。
- **移动端零拷贝与端侧神经层（本仓核心工作）**：针对**手机触屏无键程 26 键快打易误触**与 **iOS 键盘扩展严苛内存上限**两大移动端痛点，`lokey-frost-pack` 并非简单的词表格式转码，而是在白霜词表底座之上离线构建了单文件零拷贝二进制索引与四层端侧轻量神经模型：
  1. **44.32 MB 单文件零内存拷贝挂载（`LKLF-v2` + `mmap`）**：无需将词典解压或读入堆内存，直接以只读内存映射（`NSData(options: [.mappedIfSafe])`）热挂载 `553,352` 条中文词条、`80,443` 条简拼索引与 `21,313` 条英文/中英混输词条，兼顾大词量与键盘毫秒级冷启动。
  2. **前向 + 逆向双向整句消歧（`LNLM-v2` + `LNBR-v2`）**：内置 `32,768` 个 32 维神经词向量、`7,863` 个神经字向量、`396,980` 条上下文搭配与排序边（覆盖双字/多字语境衔接及 `1,600` 组高频易混同音词专项消歧），配合逆向句首重排模型，显著降低长句输入“句首同音词选错”导致的返工。
  3. **26 键触屏盲打纠错重排（`LNTR-v1`）**：针对手机小屏拇指快打常见的邻键误触（如 `g/h`、`i/o`、`n/m`），在多条近似拼音路径间结合整句语义通顺度重排，提升盲打容错率。
  4. **64 维跨句语义话题记忆（`LNS6-v1`）**：基于纯本机滑动窗口维护上下文语义向量，上文出现特定领域词汇后，后续简短同音拼音自动向当前话题语境倾斜。

### 2. 开源发布与客户端隔离边界

- **成品包与编译器 100% 免费公开**：预编译 `rime-frost.lokeypack` 在本仓库 GitHub Releases 直接免费提供下载；构建脚本仅依赖 `git` 与 Python 3 标准库（零第三方依赖），任何人均可离线完整复现同一 SHA-256 产物，或自行指定上游提交重新编译。
- **被动静态数据与主应用独立**：`.lokeypack` 是纯粹的被动只读静态数据文件，兼容单文件 `LKEX v1` 零拷贝扩展段与旧版客户端。**Lokey 主应用与键盘扩展内置独立的无 GPL 基础词库与完整神经引擎（不导入任何外部包即可正常使用全部输入方案），且物理级零联网（0 网络框架 / 0 Socket 符号，见 [`Kianuni/Lokey-Audit`](https://github.com/Kianuni/Lokey-Audit)），永远不会联网拉取词库**；有更大词量需求的用户可自愿下载 `.lokeypack` 文件后在本地手动导入。

### 3. 技术规格与 SHA-256 校验

- **二进制结构**：`LKLF-v2` 主词库段 + `LNLM-v2`（32 维 SIMD 前向神经打分段）+ `LKEX v1` 单文件扩展段（内嵌 `LNBR-v2` `200,566 B`、`LNTR-v1` `46,768 B`、`LNS6-v1` `5,762,320 B`）+ `EOF-16` 尾部校验（不含表情或简繁转换表）。
- **当前发布版本**：`v0.9.5`（兼容 Lokey `1.0` 及后续版本）
- **文件大小**：`46,477,184` 字节（`44.32 MB`）
- **SHA-256**：`de32f3c0e561026752e56392c2cd5cdd912a73424da2ff9b9fae80d04d4ee348`

从 [GitHub Releases](https://github.com/Kianuni/lokey-frost-pack/releases/latest) 下载 `rime-frost.lokeypack` 与 `rime-frost.lokeypack.sha256` 至同一目录后，可在终端核验完整性：

```bash
shasum -a 256 -c rime-frost.lokeypack.sha256
# 预期输出: rime-frost.lokeypack: OK
```

### 4. iOS 导入与热挂载指南

1. **方式一：通过「文件」App 选择导入**
   - 将 `rime-frost.lokeypack` 保存至 iPhone「文件」App（iCloud 云盘或「我的 iPhone」）。
   - 打开 **Lokey → 词库数据 → 导入外部 `.lokeypack` 词库包**（或进入「管理基础词库与已安装包」），选中该文件完成本机校验与安装。
2. **方式二：隔空投送（AirDrop）或「用 Lokey 打开」**
   - 从 Mac 通过 AirDrop 发送 `rime-frost.lokeypack` 至 iPhone，或在「文件」App 中长按该文件点击**分享 → 用 Lokey 打开**。
3. **状态核验与一键切回内置词库**
   - 挂载后可在「词库数据」页查看词条规模、音节数、来源与 SHA-256 摘要；随时可**一键切换回内置纯净基础词库**或左滑删除外部词库包。

### 5. 纯离线自行编译与定制 `.lokeypack`

本仓库构建过程完全独立，仅需 `git` 与 Python 3 标准库（无需安装任何第三方 `pip` 依赖），Lokey 客户端不绑定官方签名，任何按格式编译的 `.lokeypack` 均可直接导入并多包共存切换：

#### 场景 A：确定性复现发布版 `rime-frost.lokeypack`
```bash
# 1. 拉取固定基线提交的 gaboolic/rime-frost（默认 commit: 7c8a908a92fa67fe1be9279b523b3cf95366e27d）
./scripts/fetch_rime_frost.sh

# 2. 纯离线编译 dist/rime-frost.lokeypack 与 dist/rime-frost.lokeypack.sha256
PYTHONHASHSEED=0 python3 scripts/build_lokeypack.py

# 3. 核验 SHA-256 校验和
(cd dist && shasum -a 256 -c rime-frost.lokeypack.sha256)
```

#### 场景 B：同步上游最新词条重新打包
```bash
RIME_FROST_COMMIT=main ./scripts/fetch_rime_frost.sh
python3 scripts/build_lokeypack.py -o dist/frost-latest.lokeypack
```

#### 场景 C：混入个人或行业专属词表（`--extra-dict`）
支持传入一个或多个标准 Rime `.dict.yaml` 文件，或纯制表符分隔文本（每行 `词条<Tab>quan pin` 或 `词条<Tab>quan pin<Tab>权重`，支持 1–8 字词条，`ü` 可写为 `v`）：
```bash
python3 scripts/build_lokeypack.py \
  --extra-dict my_domain.dict.yaml \
  --extra-dict custom_terms.txt \
  -o dist/my-custom.lokeypack
```
生成后通过 AirDrop 或「文件」App 导入 iPhone，即可在「基础词库管理」中随时挂载切换。

### 6. 开源许可证与合规声明

- 本仓库源码与编译产物遵循 `LICENSE` 所载开源许可证条款。
- 上游词典、语料及模型组件的详细许可证与归属声明见 [`THIRD_PARTY_NOTICES.md`](./THIRD_PARTY_NOTICES.md) 与 [`LICENSES/`](./LICENSES/)。

---

<a id="english"></a>

## English

`lokey-frost-pack` is a standalone, offline `.lokeypack` external lexicon pack and open-source compiler repository for the **Lokey** iOS 26-key Full-Pinyin & Xiaohe/Ziranma Shuangpin keyboard.

### 1. Relationship with Upstream `rime-frost` & Mobile Enhancements

- **Dictionary Foundation (Upstream Credit)**: The Chinese vocabulary, polyphone readings, and baseline word frequencies originate from [`gaboolic/rime-frost`](https://github.com/gaboolic/rime-frost) (pinned at commit `7c8a908a92fa67fe1be9279b523b3cf95366e27d`, `2026-11-09`), building upon the Rime Ice ecosystem. We gratefully acknowledge the upstream maintainers and contributors for their meticulous dictionary curation.
- **Zero-Copy Indexing & On-Device Neural Reranking (What This Repo Adds)**: Rather than a plain YAML-to-binary format conversion, `lokey-frost-pack` addresses two mobile-specific constraints—**eyes-free 26-key touchscreen thumb typing** and **strict iOS keyboard extension memory limits**—by compiling four on-device capabilities into a single memory-mapped file:
  1. **44.32 MB Single-File Zero-Copy `mmap` (`LKLF-v2`)**: Mounts `553,352` Chinese words, `80,443` Jianpin entries, and `21,313` English/CN-EN mixed entries via read-only `NSData(options: [.mappedIfSafe])` with zero heap copy overhead.
  2. **Forward + Backward Neural Sentence Disambiguation (`LNLM-v2` + `LNBR-v2`)**: Combines `32,768` 32-dim word vectors, `7,863` character vectors, `396,980` contextual association/ranking edges (including `1,600` targeted homophone disambiguation pairs), and a backward sentence-initial reranker to prevent early homophone misselections in long sentences.
  3. **26-Key Blind-Typing Typo Reranker (`LNTR-v1`)**: Re-scores competing adjacent-key typo hypotheses by full-sentence fluency during fast mobile thumb typing.
  4. **64-Dim Cross-Sentence Semantic Topic Memory (`LNS6-v1`)**: Maintains an on-device sliding semantic vector so short ambiguous Pinyin inputs naturally adapt to the active conversation topic.

### 2. Free Open-Source Distribution & Client Separation

- **100% Free & Reproducible**: Prebuilt `rime-frost.lokeypack` binaries are freely available on GitHub Releases, and the compiler uses only `git` and Python 3's standard library (zero third-party `pip` dependencies) for bit-for-bit reproducible offline builds.
- **Passive Data & Independent Host App**: `.lokeypack` is a passive, read-only static binary file. **Lokey** ships with its own independent built-in base lexicon and neural engine (fully functional out of the box without any external pack) and is physically air-gapped with zero networking frameworks or socket symbols (auditable in [`Kianuni/Lokey-Audit`](https://github.com/Kianuni/Lokey-Audit)). Lokey never downloads dictionaries over the network; users optionally download and import `.lokeypack` files locally.

### 3. Specifications & SHA-256 Checksum

- **Binary Layout**: `LKLF-v2` base lexicon + `LNLM-v2` (32-dim SIMD forward scorer) + `LKEX v1` single-file extension (`LNBR-v2` `200,566 B`, `LNTR-v1` `46,768 B`, `LNS6-v1` `5,762,320 B`) + `EOF-16` trailer (backward-compatible with older clients; excludes Emoji/OpenCC assets).
- **Release**: `v0.9.5` (compatible with Lokey `1.0`+)
- **Size**: `46,477,184` bytes (`44.32 MB`)
- **SHA-256**: `de32f3c0e561026752e56392c2cd5cdd912a73424da2ff9b9fae80d04d4ee348`

```bash
shasum -a 256 -c rime-frost.lokeypack.sha256
# Expected: rime-frost.lokeypack: OK
```

### 4. iOS Import Guide

1. **Files App Picker**: Save `rime-frost.lokeypack` to the iOS **Files** app, then open **Lokey → Lexicon Data → Import External `.lokeypack`** (or **Manage Base Lexicon & Installed Packs**).
2. **AirDrop / Open In**: AirDrop `rime-frost.lokeypack` from Mac to iPhone, or tap **Share → Open in Lokey** inside the Files app.
3. **One-Tap Rollback**: View word count, syllable count, and SHA-256 digest in **Lexicon Data**, switch back to the built-in lexicon in one tap, or swipe to delete external packs at any time.

### 5. Offline Self-Compilation & Custom `.lokeypack` Builds

Building requires only `git` and Python 3's standard library (zero third-party `pip` packages). Lokey enforces structural bounds checking without locking packs to official signatures, so custom-built `.lokeypack` files can be imported and switched freely:

```bash
# Scenario A: Deterministically reproduce the release rime-frost.lokeypack
./scripts/fetch_rime_frost.sh
PYTHONHASHSEED=0 python3 scripts/build_lokeypack.py
(cd dist && shasum -a 256 -c rime-frost.lokeypack.sha256)

# Scenario B: Track the latest upstream rime-frost entries
RIME_FROST_COMMIT=main ./scripts/fetch_rime_frost.sh
python3 scripts/build_lokeypack.py -o dist/frost-latest.lokeypack

# Scenario C: Merge your own Rime .dict.yaml or TSV wordlists (`word<Tab>pin yin[<Tab>weight]`)
python3 scripts/build_lokeypack.py \
  --extra-dict my_domain.dict.yaml \
  -o dist/my-custom.lokeypack
```

> Pass `--rime-frost-dir <path>` to compile against any local Rime dictionary directory checkout.

### 6. License & Notices

- Repository source code and compiled artifacts are governed by [`LICENSE`](./LICENSE).
- Detailed upstream dictionary, corpus, and component attributions are documented in [`THIRD_PARTY_NOTICES.md`](./THIRD_PARTY_NOTICES.md) and [`LICENSES/`](./LICENSES/).
