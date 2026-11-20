# lokey-frost-pack

[中文](#中文说明) | [English](#english)

---

<a id="中文说明"></a>

## 中文说明

`lokey-frost-pack` 是为 **Lokey（`Kianuni/Lokey`）** iOS 26 键全拼输入法提供的**纯离线 `GPL-3.0` 外部词库包与独立编译器仓库**。

### 1. 词库包概览

- **二进制格式**：`LKLF-v2` + 内嵌 `LNLM-v2`（32 维 SIMD 神经整句打分器）+ `EOF-16` 尾部校验结构（仅含词库与神经语言模型，不含表情符号或 OpenCC 二进制）。
- **基准对齐**：基于 `gaboolic/rime-frost` 固定提交 `7c8a908a92fa67fe1be9279b523b3cf95366e27d`（`2026-11-09`）编译，与 Lokey `v0.7.15` 基线保持**逐字节一致**（`40,083,208` 字节，425 个音节、553,351 条中文词条、80,443 条简拼索引、21,313 条英文及中英混输词条、392,760 条联想与排序边、32,768 个神经词向量、7,863 个神经字向量）。
- **零延迟挂载**：导入后由 Lokey 通过 `NSData(contentsOf:options: [.mappedIfSafe])` 以只读 `mmap` 零拷贝方式直接热挂载，耗时 `0.00ms`，无堆内存拷贝开销。

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

> 说明：默认固定拉取 `gaboolic/rime-frost` 提交 `7c8a908a92fa67fe1be9279b523b3cf95366e27d`（`2026-11-09`），可 100% 复现 `v0.7.15` 字节级基线（SHA-256 `62ce08fa0c4a94d0e45d7d715016128b944685dd9cc3e4f8f2af18fecd221db9`）。如希望测试上游更新词条，可通过 `RIME_FROST_COMMIT=<commit> ./scripts/fetch_rime_frost.sh` 或 `--rime-frost-dir <path>` 指定自定义目录。

### 6. 开源许可与致谢

- 仓库整体及编译产物遵循 **GPL-3.0**（见 `LICENSE` 与 `LICENSES/rime-frost-GPL-3.0.txt`）。
- 第三方语料与残差权重声明见 `THIRD_PARTY_NOTICES.md`、`LICENSES/Tatoeba.txt`（`CC-BY-2.0 FR`）及 `LICENSES/UD-Chinese-GSDSimp.txt`（`CC-BY-SA-4.0`）。

---

<a id="english"></a>

## English

`lokey-frost-pack` is a standalone, offline **`GPL-3.0`** `.lokeypack` lexicon pack and compiler repository for the **Lokey (`Kianuni/Lokey`)** iOS 26-key Full-Pinyin keyboard.

### 1. Pack Overview

- **Binary Format**: `LKLF-v2` + embedded `LNLM-v2` (32-dim SIMD neural sentence scorer) + `EOF-16` trailer (`rime-frost.lokeypack` only; does not bundle `lokey_emoji.bin` or `lokey_opencc.bin`).
- **Baseline Parity**: Compiled from pinned `gaboolic/rime-frost` commit `7c8a908a92fa67fe1be9279b523b3cf95366e27d` (`2026-11-09`), matching the `v0.7.15` lexicon baseline **byte-for-byte** (`40,083,208` bytes; `425` syllables, `553,351` Chinese word entries, `80,443` Jianpin entries, `21,313` English/CN-EN entries, `392,760` association/ranking edges, `32,768` neural word vectors, and `7,863` neural character vectors).
- **`0.00ms` Zero-Copy `mmap` Mounting**: Mounted read-only in Lokey via `NSData(contentsOf:options: [.mappedIfSafe])` with `0.00ms` copy overhead.

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

> Pinning `gaboolic/rime-frost` at commit `7c8a908a92fa67fe1be9279b523b3cf95366e27d` (`2026-11-09`) deterministically reproduces the `v0.7.15` baseline (`62ce08fa0c4a94d0e45d7d715016128b944685dd9cc3e4f8f2af18fecd221db9`), independent of `PYTHONHASHSEED`. To compile a different snapshot or local checkout, override `RIME_FROST_COMMIT` or pass `--rime-frost-dir <path>`.

### 6. License & Attributions

- **License**: `GPL-3.0` (`LICENSE`, `LICENSES/rime-frost-GPL-3.0.txt`).
- **Third-Party Attributions**: See `THIRD_PARTY_NOTICES.md`, `LICENSES/Tatoeba.txt` (`CC-BY-2.0 FR`), and `LICENSES/UD-Chinese-GSDSimp.txt` (`CC-BY-SA-4.0`).
