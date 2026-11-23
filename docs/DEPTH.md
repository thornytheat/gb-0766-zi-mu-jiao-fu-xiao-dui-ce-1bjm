# 深度登记 字幕交付校对册

## 功能模块

| 模块 | 使用者动作 | 入口 | 核心文件 | 测试 |
|---|---|---|---|---|
| M1 字幕文件采信 | 核对逐行隔离与重复字幕 | `/sheet/source` `/api/check/source` | `app/modules/source/service.py` | `tests/test_source.py` |
| M2 帧率与丢帧约束 | 复查非法标签与精确换算 | `/sheet/clock` `/api/check/clock` | `app/modules/clock/timecode.py` | `tests/test_clock.py` |
| M3 切版段映射 | 按切版重建目标帧 | `/` `/api/check/edits` | `app/modules/edits/contract.py` `app/modules/edits/mapping.py` | `tests/test_edits.py` |
| M4 字幕冲突定位 | 定位同轨重叠帧与原行组 | `/sheet/overlaps` `/api/check/overlaps` | `app/modules/overlaps/service.py` | `tests/test_overlaps.py` |
| M5 时长与丢段对账 | 查看并集覆盖守恒 | `/sheet/balance` `/api/check/balance` | `app/modules/balance/service.py` | `tests/test_balance.py` |
| M6 批次留档复跑 | 保存原件并逐值复算 | `/sheet/runs` `POST /api/runs` | `app/modules/runs/files.py` `app/modules/runs/service.py` | `tests/test_runs.py` |
| M7 交付证据签发 | 下载经散列核验的交付证据 | `/sheet/delivery` `/api/delivery/<key>/export` | `app/modules/delivery/checks.py` | `tests/test_delivery.py` |
| M8 双语切轨对账 | 反查实际切轨帧并核漏播重播 | `/sheet/switching` `/api/switch/preview` | `app/modules/switching/locate.py` `app/modules/switching/ledger.py` | `tests/test_switching.py` |

## 陷阱登记

| TRAP | 现象 | 朴素实现 | 本项目处理 | 处理位置 | 测试 |
|---|---|---|---|---|---|
| TRAP-02 | 脏字幕首列 BOM | 首列无效 | 去首 BOM | `app/modules/source/reader.py` | `tests/test_source.py::test_bom_and_alias` |
| TRAP-04 | 脏字幕重复表头 | 当成字幕计算 | 单列分段 | `app/modules/source/reader.py` | `tests/test_source.py::test_repeated_header` |
| TRAP-05 | C112 多余列 | 文本错位 | 保留整行隔离 | `app/modules/source/reader.py` | `tests/test_source.py::test_width_and_missing` |
| TRAP-07 | C110 时码 N/A | 当成零帧 | 隔离必填空值 | `app/modules/source/service.py` | `tests/test_source.py::test_width_and_missing` |
| TRAP-09 | 9007199254740993 | 浏览器数值吞位 | 字符串保形 | `app/modules/source/service.py` | `tests/test_source.py::test_string_identity` |
| TRAP-10 | C104 使用分数帧率 | 假设 30 或先舍入 | 保留端点有理数至最后 | `app/modules/clock/timecode.py` | `tests/test_clock.py::test_exact_rate` |
| TRAP-14 | C111 内容相撞 | 后稿静默覆盖 | 同号矛盾整组隔离 | `app/modules/source/service.py` | `tests/test_source.py::test_conflicting_revision` |
| TRAP-17 | `legacy_id` 旧表头 | 硬读当前字段失败 | 按列别名迁移 | `app/modules/source/service.py` | `tests/test_source.py::test_bom_and_alias` |
| TRAP-23 | C115 与 C116 首尾相接 | 共同边界算重叠 | 半开区间扫线 | `app/modules/overlaps/sweep.py` | `tests/test_overlaps.py::test_touch_is_not_overlap` |
| TRAP-24 | 切轨帧落在原句中间 | 立即换轨截断原句 | 顺延至原句交付末帧，记录原行依据 | `app/modules/switching/locate.py` | `tests/test_switching.py::test_mid_sentence_request_defers_to_cue_end` |
| TRAP-25 | 顺延末帧落入下一条重叠原句 | 新原句仍被截断 | 定点循环到没有原句跨过切点 | `app/modules/switching/locate.py` | `tests/test_switching.py::test_overlapping_cues_force_fixed_point_deferral` |
| TRAP-26 | 请求帧落在目标待证区 | 反查不到切段而报错 | 顺延到下一 KEEP 锚帧并记录 GAP | `app/modules/switching/locate.py` | `tests/test_switching.py::test_gap_frame_advances_to_next_keep_anchor` |
| TRAP-27 | 切轨重试生成第二份档案 | 同一请求重复留档 | 原件散列+请求散列内容寻址，硬链接复用 | `app/modules/switching/files.py` | `tests/test_switching.py::test_retry_same_request_reuses_archive` |
| TRAP-28 | 译文跨过实际切点 | 整句判漏播或整句播放 | 半开帧切成漏播前段与保留后段（STRADDLED） | `app/modules/switching/ledger.py` | `tests/test_switching.py::test_target_cue_straddling_switch_is_split` |

## 守恒与范围

脏样例 1140 源帧 = 740 交付 + 200 移除 + 200 待证。65 个重叠目标帧独立记录，5 条隔离记录无法量化。原件为带格式列的供应商抽取 CSV，DF 参数固定为 29.97，目标固定 24 fps。

双语切轨样例（`sample_data/bilingual`）在帧 350 请求简中→英语：切点反查落入 Z2 句中，顺延到交付末帧 401。对账为漏播 160 帧、弃用 200 帧、重播 40 帧（E3/E4 重叠区 [562,602)）；两条轨道均满足 `KEEP 并集帧 = 切轨前 + 切轨后`，差额恒为 0。
