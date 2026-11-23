# lokey-frost-pack

[中文](#中文说明) | [English](#english)

---

<a id="中文说明"></a>

## 中文说明

`lokey-frost-pack` 是为 **Lokey（`Kianuni/Lokey`）** iOS 26 键全拼与小鹤/自然码双拼输入法提供的**纯离线 `GPL-3.0` 外部词库包与独立编译器仓库**。

### 1. 词库包概览

- **二进制格式**：`LKLF-v2` + 内嵌 `LNLM-v2`（32 维 SIMD 神经整句打分）+ 单文件零拷贝 `LKEX v1` 扩展段（内嵌 `LNBR-v2` 逆向句首重排、`LNTR-v1` 盲打纠错重排与 `LNS6-v1` 64 维语义话题记忆）+ `EOF-16` 尾部校验结构（仅含词库与语言模型，不含表情符号或 OpenCC 二进制，且向下兼容旧版客户端）。
- **`v0.9.5` 词库与模型内容**：基于 `gaboolic/rime-frost` 固定提交 `7c8a908a92fa67fe1be9279b523b3cf95366e27d`（`2026-11-09`）编译，总大小 `46,477,184` 字节（`44.32 MB`），包含 `425` 个音节、`553,352` 条中文词条、`80,443` 条简拼索引、`21,313` 条英文及中英混输词条、`396,980` 条联想与排序边（覆盖双字与多字上下文联想及 `1,600` 对高难同音词消歧）、`32,768` 个神经词向量、`7,863` 个神经字向量，以及单文件内嵌的 `LNBR-v2`（`200,566` 字节）、`LNTR-v1`（`46,768` 字节）与 `LNS6-v1`（`5,762,320` 字节）。
- **单文件零拷贝挂载**：导入单个 `rime-frost.lokeypack` 后由 Lokey 通过 `NSData(contentsOf:options: [.mappedIfSafe])` 以只读 `mmap` 方式直接热挂载，即刻启用完整的词库、整句重排、盲打纠错与上下文话题记忆能力，无堆内存拷贝开销。

### 2. 物理零联网与 GPL-3.0 商业隔离说明

- **主应用合规隔离**：商业版 `Kianuni/Lokey` 内置 100% 无 GPL 传染性数据的宽松许可基础词库，且二进制与源码中不包含任何网络框架或 Socket 符号（可通过 [`Kianuni/Lokey-Audit`](https://github.com/Kianuni/Lokey-Audit) 独立审计验证）。
- **被动静态数据包**：`Kianuni/lokey-frost-pack` 为独立的 `GPL-3.0` 开源仓库。`.lokeypack` 是纯粹的被动只读静态数据文件，**Lokey 主应用与键盘扩展永远不会联网下载或拉取任何词库**。用户可在本地自愿选择下载或离线编译 `.lokeypack` 后手动导入 Lokey；Lokey 在本地验证魔数、版本号、各段边界、`LNLM-v2` 尾部与 SHA-256 校验和后，原子安装至本地 `App Group` 沙盒中通过 `mmap` 挂载。

### 3. 下载与 SHA-256 校验

从 GitHub Releases 下载 `rime-frost.lokeypack` 与 `rime-frost.lokeypack.sha256` 至同一目录后，在终端执行校验：

```bash
# 在下载目录中直接校验（或本地构建后在 dist/ 目录中执行）
shasum -a 256 -c rime-frost.lokeypack.sha256
# 预期输出: rime-frost.lokeypack: OK
```

本地从源码编译后校验：

```bash
(cd dist && shasum -a 256 -c rime-frost.lokeypack.sha256)
```

### 4. iOS 导入与热挂载指南

1. **方式一：通过「文件」App 导入（Files Picker，`asCopy: true`）**
   - 将已校验的 `rime-frost.lokeypack` 保存至 iPhone 的「文件」App（iCloud 云盘或「我的 iPhone」）。
   - 打开 **Lokey** 主应用 → 进入 **基础词库管理（Base-Lexicon Manager）** → 点击导入按钮并在「文件」选择器中选中 `rime-frost.lokeypack`。
2. **方式二：隔空投送（AirDrop）或「用 Lokey 打开」（`"Open In Lokey"`）**
   - 从 Mac 通过 AirDrop 发送 `rime-frost.lokeypack` 至 iPhone，或在 iPhone「文件」App 中长按/点击分享该文件，选择 **「用 Lokey 打开」**。
3. **查看元数据与一键切回内置词库**
   - 导入后可在 Lokey 内查看当前挂载词库的词条数、音节数、来源说明与 SHA-256 摘要。
   - 如需恢复商业版内置宽松许可词库，可在词库管理页面**一键切换回内置词库**，或随时删除已导入的外部 `.lokeypack` 包。

### 5. 纯离线从源码构建

本仓库构建过程**完全独立**，不依赖 `Kianuni/Lokey` 仓库，仅需 `git` 与 Python 3 标准库（无需 `pip` 安装任何第三方依赖）：

```bash
# 1. 拉取固定基线提交的 gaboolic/rime-frost（默认 commit: 7c8a908a92fa67fe1be9279b523b3cf95366e27d）
./scripts/fetch_rime_frost.sh

# 2. 纯离线编译 dist/rime-frost.lokeypack 与 dist/rime-frost.lokeypack.sha256
python3 scripts/build_lokeypack.py

# 3. 验证 SHA-256 校验和
(cd dist && shasum -a 256 -c rime-frost.lokeypack.sha256)
```

> 说明：默认固定拉取 `gaboolic/rime-frost` 提交 `7c8a908a92fa67fe1be9279b523b3cf95366e27d`（`2026-11-09`），使用 `PYTHONHASHSEED=0 python3 scripts/build_lokeypack.py` 可 100% 确定性复现 `v0.9.5` 发布版（`46,477,184` 字节，SHA-256 `de32f3c0e561026752e56392c2cd5cdd912a73424da2ff9b9fae80d04d4ee348`；GitHub Release：`https://github.com/Kianuni/lokey-frost-pack/releases/tag/v0.9.5`）。如希望测试上游更新词条，可通过 `RIME_FROST_COMMIT=<commit> ./scripts/fetch_rime_frost.sh` 或 `--rime-frost-dir <path>` 指定自定义目录。
>
> **单文件 `LKEX v1` 扩展支持**：`scripts/build_lokeypack.py` 支持全词表 `32,768` 神经词向量、`1,600` 对高难同音词消歧（`data/commit-deltas.tsv`）与多字上下文联想（`data/conversational-assoc-v2.tsv`），并在 `data/` 包含 `lokey_lnlm_bwd.bin`（`LNBR-v2`）、`lokey_lntr.bin`（`LNTR-v1`）或 `lokey_lnlm_sem64.bin`（`LNS6-v1`）时自动将其以零拷贝 `LKEX v1` 扩展段内嵌进**单个** `rime-frost.lokeypack` 中，兼容 iOS「文件」App 与隔空投送单文件导入，且与旧版客户端双向兼容。

### 6. 开源许可声明

- 仓库整体及编译产物遵循 **GPL-3.0**（见 `LICENSE`）。
- 第三方数据与权重许可声明见 `THIRD_PARTY_NOTICES.md` 与 `LICENSES/`。

---

<a id="english"></a>

## English

`lokey-frost-pack` is a standalone, offline **`GPL-3.0`** `.lokeypack` lexicon pack and compiler repository for the **Lokey (`Kianuni/Lokey`)** iOS 26-key Full-Pinyin & Xiaohe/Ziranma Shuangpin keyboard.

### 1. Pack Overview

- **Binary Format**: `LKLF-v2` + embedded `LNLM-v2` (32-dim SIMD neural sentence scorer) + single-file zero-copy `LKEX v1` extension section (embedding `LNBR-v2` backward sentence-initial reranker, `LNTR-v1` blind-typing typo reranker, and `LNS6-v1` 64-dim semantic topic memory) + `EOF-16` trailer (`rime-frost.lokeypack` only; does not bundle `lokey_emoji.bin` or `lokey_opencc.bin`; backward-compatible with older clients).
- **`v0.9.5` Lexicon & Model Contents**: Compiled from pinned `gaboolic/rime-frost` commit `7c8a908a92fa67fe1be9279b523b3cf95366e27d` (`2026-11-09`), totaling `46,477,184` bytes (`44.32 MB`): `425` syllables, `553,352` Chinese word entries, `80,443` Jianpin entries, `21,313` English/CN-EN entries, `396,980` association and ranking edges (covering bigram/multi-word context associations and `1,600` homophone disambiguation pairs), `32,768` neural word vectors, `7,863` neural character vectors, plus single-file embedded `LNBR-v2` (`200,566 B`), `LNTR-v1` (`46,768 B`), and `LNS6-v1` (`5,762,320 B`).
- **Zero-Copy Single-File `mmap` Mounting**: Mounted read-only in Lokey via `NSData(contentsOf:options: [.mappedIfSafe])` with zero heap copy overhead, activating full lexicon lookup, sentence reranking, blind-typing typo correction, and semantic topic memory from a single `.lokeypack` file.

### 2. Zero-Network Guarantee & GPL-3.0 Separation

- **Commercial Separation**: `Kianuni/Lokey` ships with a 100% GPL-free permissive built-in base lexicon and contains zero networking frameworks or socket symbols (independently verifiable in `Kianuni/Lokey-Audit`).
- **Passive Static Data File**: `Kianuni/lokey-frost-pack` is a separate `GPL-3.0` repository. `.lokeypack` is a passive read-only binary data file; `Lokey` never fetches or downloads packs over the network. Users explicitly import a local `.lokeypack` file into `Lokey`, which validates magic bytes, version, section bounds, `LNLM-v2` trailer bounds, and SHA-256 before atomically installing it into the local `App Group` sandbox for `mmap` mounting.

### 3. Download & SHA-256 Verification

Download `rime-frost.lokeypack` and `rime-frost.lokeypack.sha256` from GitHub Releases into the same directory, then verify:

```bash
# Inside the download folder:
shasum -a 256 -c rime-frost.lokeypack.sha256
# Expected: rime-frost.lokeypack: OK
```

After a local build from source:

```bash
(cd dist && shasum -a 256 -c rime-frost.lokeypack.sha256)
```

### 4. iOS Import Guide

1. **Method A — Files Picker (`asCopy: true`)**
   - Save `rime-frost.lokeypack` to the iOS **Files** app.
   - Open **Lokey** → **Base-Lexicon Manager** → tap **Import** and select `rime-frost.lokeypack` from the Files picker.
2. **Method B — AirDrop / `"Open In Lokey"`**
   - AirDrop `rime-frost.lokeypack` from Mac to iPhone, or tap Share → **Open In Lokey** from the Files app.
3. **Metadata Inspection & One-Tap Rollback**
   - Inspect the mounted lexicon's word count, syllable count, source, and SHA-256 digest inside Lokey.
   - Switch back to the built-in GPL-free permissive lexicon with one tap, or delete the external `.lokeypack` at any time.

### 5. Offline Build from Source

Building requires **zero** dependency on `Kianuni/Lokey`, using only `git` and Python 3's standard library (no third-party `pip` packages):

```bash
# 1. Fetch pinned gaboolic/rime-frost (default commit: 7c8a908a92fa67fe1be9279b523b3cf95366e27d)
./scripts/fetch_rime_frost.sh

# 2. Compile dist/rime-frost.lokeypack and dist/rime-frost.lokeypack.sha256 offline
python3 scripts/build_lokeypack.py

# 3. Verify SHA-256 checksum
(cd dist && shasum -a 256 -c rime-frost.lokeypack.sha256)
```

> Pinning `gaboolic/rime-frost` at commit `7c8a908a92fa67fe1be9279b523b3cf95366e27d` (`2026-11-09`) with `PYTHONHASHSEED=0 python3 scripts/build_lokeypack.py` deterministically reproduces the `v0.9.5` release (`46,477,184` bytes, SHA-256 `de32f3c0e561026752e56392c2cd5cdd912a73424da2ff9b9fae80d04d4ee348`; `https://github.com/Kianuni/lokey-frost-pack/releases/tag/v0.9.5`). To compile a different snapshot or local checkout, override `RIME_FROST_COMMIT` or pass `--rime-frost-dir <path>`.

### 6. License

- **License**: `GPL-3.0` (`LICENSE`).
- **Third-Party Notices**: See `THIRD_PARTY_NOTICES.md` and `LICENSES/`.
