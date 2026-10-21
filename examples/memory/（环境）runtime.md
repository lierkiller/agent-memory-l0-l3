---
name: （环境）runtime
description: 示例：运行环境速查——解释器、依赖、路径约定。命中「环境 / 版本 / 路径」类问题时读这篇。
---

# 运行环境（示例）

> 这是 L2 主题记忆的示例：**一篇一个主题**，控制在 4k token 内。
> 真实项目里，这一篇会写清「装了什么版本、在哪、怎么调用」。

## 解释器

| 用途 | 路径 | 版本 |
|---|---|---|
| 主 Python | `~/.local/python/bin/python3` | 3.14.x |
| Node | `~/.local/node/bin/node` | 22.x |

调用一律写绝对路径——PATH 里可能没有它。

## 依赖

- 计算：`numpy` / `scipy` / `pandas` / `sympy`
- 出图：`matplotlib`（后端用 `Agg`，别指望弹窗）
- 缺的包：`cvxpy`、`polars` —— 需要时先报告再装

## 路径约定

| 用途 | 位置 |
|---|---|
| 工作区（可写） | `~/work` |
| 产物 | `~/work/out` |
| 临时文件 | `~/work/tmp`，收工必须清 |

## 红线

- 不要动系统级 site-packages。
- 长任务先估时间，超过 10 分钟改成后台跑并把任务号记下来。

## 详细台账

盘点与沿革在冷档：[（环境）runtime-inventory.md](（环境）runtime-inventory.md)。
