# Third-Party Notices and Attributions

`lokey-frost-pack` is licensed under the **GNU General Public License v3.0** (`LICENSE`). It compiles upstream `gaboolic/rime-frost` dictionaries together with pre-computed conversational and neural-reranker tables into a passive `.lokeypack` (`LKLF-v2` + `LNLM-v2`) binary lexicon file.

---

## 1. gaboolic/rime-frost (GPL-3.0)

- **Upstream Repository**: https://github.com/gaboolic/rime-frost
- **Pinned Baseline Commit**: `7c8a908a92fa67fe1be9279b523b3cf95366e27d` (`2026-11-09`)
- **License**: GNU General Public License v3.0 — see `LICENSE` and `LICENSES/rime-frost-GPL-3.0.txt`
- **Scope in `.lokeypack`**: `scripts/build_lokeypack.py` compiles Chinese dictionary tables (`cn_dicts/*.dict.yaml`, `cn_dicts_cell/*.dict.yaml`), corpus frequency/orthography lists (`others/*.txt`), and English/CN-EN mixed tables (`en_dicts/*`) into `LKLF-v2` + `LNLM-v2` (`rime-frost.lokeypack`).
- **Upstream Acknowledgements**: `gaboolic/rime-frost` acknowledges and builds upon projects including:
  - [`iDvel/rime-ice`](https://github.com/iDvel/rime-ice) (`GPL-3.0`)
  - [`fxsjy/jieba`](https://github.com/fxsjy/jieba) (`MIT`)
  - [`mozillazg/python-pinyin`](https://github.com/mozillazg/python-pinyin) (`MIT`) and [`mozillazg/pinyin-data`](https://github.com/mozillazg/pinyin-data) (`MIT`)
  - [`esbatmop/MNBVC`](https://github.com/esbatmop/MNBVC) and [`kpu/kenlm`](https://github.com/kpu/kenlm)
  - Unicode Unihan, [`thunlp/THUOCL`](https://github.com/thunlp/THUOCL), `rime/rime-essay-simp`, `rimeinn/rime-moran`, `first20hours/google-10000-english`, and `tumuyan/rime-melt`
- **Note on `rime/rime-emoji` (`LGPL-3.0`)**: Upstream `rime-frost` references [`rime/rime-emoji`](https://github.com/rime/rime-emoji) (`LGPL-3.0`) in `symbols_v.yaml` / `opencc/emoji.txt`. Note that `rime-frost.lokeypack` packages **only** `LKLF-v2` + `LNLM-v2` (Pinyin/English/association lexicon and 32-dim neural sentence scorer); it does **not** compile or bundle `lokey_emoji.bin` (`LEMJ-v1`) or `lokey_opencc.bin`.

---

## 2. Tatoeba Mandarin Sentence Corpus (CC-BY-2.0 FR)

- **Files**: `data/mandarin-counts.tsv`, `data/commit-deltas.tsv`
- **Upstream Source**: https://tatoeba.org/en/downloads (`cmn_sentences_detailed.tsv.bz2`, SHA-256 `df15b916580d97db21a4f28c4f49f47aad7755025bc969b81762bcde6a47ea6a`)
- **License**: Creative Commons Attribution 2.0 France (`CC-BY-2.0 FR`) — https://creativecommons.org/licenses/by/2.0/fr/
- **Full Attribution & Contributor Credits**: See `LICENSES/Tatoeba.txt` verbatim.
- **Modifications**: Simplified-Chinese normalization, deduplication, short-phrase frequency aggregation, and quantized contextual commit-choice parameters (`data/mandarin-counts.tsv` and `data/commit-deltas.tsv`) consumed offline by `scripts/build_lokeypack.py`.

---

## 3. Universal Dependencies Chinese GSDSimp v2.16 (CC-BY-SA-4.0)

- **File**: `data/target-deltas.tsv`
- **Upstream Source**: https://github.com/UniversalDependencies/UD_Chinese-GSDSimp/tree/9b1fc1d388b8f4ac7cf12a704995618571454b80 (`v2.16`, derived from UD Chinese GSD; https://universaldependencies.org/treebanks/zh_gsdsimp/index.html)
- **Maintainers & Contributors**: Peng Qi, Koichi Yasuoka, and original Chinese Google Universal Dependency Treebank contributors.
- **License**: Creative Commons Attribution-ShareAlike 4.0 International (`CC-BY-SA-4.0`) — https://creativecommons.org/licenses/by-sa/4.0/
- **Full Attribution Notice**: See `LICENSES/UD-Chinese-GSDSimp.txt` verbatim.
- **Modifications**: Extracted simplified Chinese word contexts, mined competing homophone pairs, and fitted quantized 32-dim `LNLM v2` target-embedding residuals (`data/target-deltas.tsv`, embedded into `rime-frost.lokeypack`). No raw treebank text is redistributed.

---

## 4. Conversational Associations & Pre-Compiled On-Device Neural Weights (`v0.9.5`)

- **Files**: `data/conversational-bigrams.tsv`, `data/conversational-assoc-v2.tsv`, `data/lnlm_backbone_v2.bin.zlib`, `data/lnlm_backbone_chars.txt`, `data/lokey_lnlm_bwd.bin`, `data/lokey_lntr.bin`, `data/lokey_lnlm_sem64.bin`
- **Sources & Licenses**:
  - Pre-compiled quantized on-device neural language model and reranker weights (`LNLM-v2`, `LNBR-v2`, `LNTR-v1`, `LNS6-v1`) fitted from `UD_Chinese-GSDSimp` `v2.16` (`CC-BY-SA-4.0`) and permissive `MIT`/`Apache-2.0` Chinese linguistic statistics (`Apache-2.0` upstream model attributions preserved; zero raw corpus text or upstream model weights redistributed).
  - Conversational bigram and multi-word association tables (`data/conversational-bigrams.tsv`, `data/conversational-assoc-v2.tsv`) derived from permissive Chinese frequency statistics; no raw corpus text is redistributed.
