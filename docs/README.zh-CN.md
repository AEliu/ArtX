# ArtX

[![Python 3.12+](https://img.shields.io/badge/python-3.12%2B-3776AB.svg)](#安装)
[![Version 0.4.0](https://img.shields.io/badge/version-0.3.0-0f766e.svg)](../pyproject.toml)
[![License: MIT](https://img.shields.io/badge/license-MIT-0f766e.svg)](../LICENSE)

[English README](../README.md)

下载 Google Arts & Culture 作品页中的高清图像。

`googleart-download` 会解析 Google Arts & Culture 作品页，下载高清图像所需的瓦片，并在本地拼接成完整图片。这个项目优先关注下载可靠性和长期可用性：支持批量任务、请求重试、缓存复用、中断恢复，以及超大图的安全处理。

## 特性

- 支持单张作品、多个 URL、或从文件批量读取
- 支持同一作品的多种输入形式：
  - 完整作品页 URL
  - 带查看参数的作品页 URL
  - 官方 `g.co/arts/...` 短链接
  - 裸 `asset id`，例如 `3QFHLJgXCmQm2Q`
- 中断后可复用已下载 tile，不会从零开始
- 支持批量恢复和只重跑失败任务
- 支持先查看可选尺寸再决定下载
- 支持 `--tile-only`，只下载 tile 而不做拼接
- 支持 `--stitch-from-tiles`，可从已有 `.tiles` 目录稍后再拼接最终图片
- 对超大作品会自动切换到 TIFF/BigTIFF 安全输出路径
- 支持 `metadata-only`、sidecar 和可选 JPEG EXIF 元数据写入

## 为什么做这个项目

Google Arts & Culture 的作品页通常使用瓦片图像。普通的“右键另存为”并不能拿到完整高清原图。

真正开始下载这些作品时，会遇到一些实际问题：

- tile 请求失败或需要重试
- 下载过程中断
- 超大作品不能安全地整图进内存再写 JPEG
- 批量任务不该中断后全部重来

这个项目就是围绕这些实际问题来设计的。

## 安装

```bash
uv sync
```

查看 CLI 帮助：

```bash
uv run artx --help
```

如果你需要大图相关的可选增强依赖：

```bash
uv sync --extra large-images
```

## 快速开始

下载一张作品：

```bash
uv run artx "https://artsandculture.google.com/asset/girl-with-a-pearl-earring/3QFHLJgXCmQm2Q" -o downloads
```

直接使用较短的 asset id：

```bash
uv run artx "3QFHLJgXCmQm2Q" --size preview
```

先查看可选尺寸：

```bash
uv run artx "3QFHLJgXCmQm2Q" --list-sizes
```

只导出作品元数据：

```bash
uv run artx "3QFHLJgXCmQm2Q" --metadata-only
```

<a href="assets/tui-preview.svg">
  <img src="assets/tui-overview.svg" alt="Terminal preview" />
</a>

_截图来自当前 TUI 的真实渲染输出。_

## 常见任务

使用更友好的尺寸预设：

```bash
uv run artx "3QFHLJgXCmQm2Q" --size preview
uv run artx "3QFHLJgXCmQm2Q" --size medium
uv run artx "3QFHLJgXCmQm2Q" --size large
uv run artx "3QFHLJgXCmQm2Q" --size max
```

恢复被中断的批量任务：

```bash
uv run artx --url-file urls.txt --resume-batch
```

只重跑上一次失败的任务：

```bash
uv run artx --rerun-failed
```

`--resume-batch` 适合“上一次批量任务中途中断，现在想接着跑”；`--rerun-failed` 适合“重新开一个新批次，只重跑上一次失败项”。

写 sidecar 或 EXIF 元数据：

```bash
uv run artx "3QFHLJgXCmQm2Q" --write-sidecar
uv run artx "3QFHLJgXCmQm2Q" --write-metadata
```

只下载 tile，不做拼接：

```bash
uv run artx "3QFHLJgXCmQm2Q" --tile-only
```

从已有 tile 目录稍后再生成最终图片：

```bash
uv run artx --stitch-from-tiles "downloads/The Great Wave.tiles"
```

推荐的 tile 工作流：

```bash
uv run artx "3QFHLJgXCmQm2Q" --tile-only
uv run artx --stitch-from-tiles "downloads/The Great Wave.tiles"
```

控制 JPEG 质量：

```bash
uv run artx "3QFHLJgXCmQm2Q" --jpeg-quality 85
uv run artx "3QFHLJgXCmQm2Q" --jpeg-preset balanced
```

如果你的网络无法直接访问 Google Arts，也可以显式指定代理：

```bash
uv run artx "3QFHLJgXCmQm2Q" --proxy http://127.0.0.1:7890
```

如果你更习惯环境变量，也可以使用标准的 `HTTPS_PROXY`、`ALL_PROXY` 等变量。显式 `--proxy` 的优先级高于环境变量代理设置。

## 输出格式说明

普通尺寸作品默认输出 JPEG。

对于非常大的作品，程序可能会自动切换到 TIFF/BigTIFF 输出。这是刻意的设计，而且仍然属于正常成功路径，不是异常回退。原因是超大图更适合使用流式拼接，而不是整张图进内存后再写 JPEG。

大图自动转 JPEG 不属于默认下载路径。如果你最终仍然需要 JPEG，建议把生成的 TIFF 作为后处理再转换。

`--tile-only` 会跳过拼接，直接写出一个可见的 `.tiles/` 目录，例如 `The Great Wave.tiles/`。目录中包含：

- `tiles/*.tile`：下载得到的 tile 文件
- `state.json`：tile-only 下载状态描述

在内部实现上，tile-only 还会在 `.googleart-cache/` 下保留一个按作品稳定身份命名的隐藏 cache，而不是直接把可见 `.tiles/` 目录当作内部 cache 身份。这样做是刻意的：

- 可见 `.tiles/` 目录继续作为用户可见产物
- 隐藏 cache 负责正确的 cache identity，避免不同作品仅因输出名相同而误复用 tile
- tile-only 成功后，会把隐藏 cache 的内容同步到可见 `.tiles/` 目录，因此两处会有一份有意保留的重复 tile 数据

`--output-conflict` 作用于当前命令准备写出的产物：

- 普通下载：最终图片文件
- `--tile-only`：可见 `.tiles/` 目录
- `--stitch-from-tiles`：最终拼接后的图片

当 `--tile-only` 与 `--output-conflict` 组合时：

- `skip`：如果现有 `.tiles` 目录已经是同一作品的完整 tile 集，会直接记为 skipped
- `overwrite`：删除已有 `.tiles` 目录后重新下载
- `rename`：写入新的同级目录，例如 `The Great Wave.2.tiles`

如果现有 `.tiles` 目录属于别的作品，tile-only 会继续下载，而不是直接记为 skipped。

当使用 `--stitch-from-tiles` 时，CLI 会直接读取现有 `.tiles` 目录里的 `state.json` 和 `tiles/*.tile`，并按所选 stitch backend 生成最终图片。当前实现暂不从这条路径恢复 sidecar 或 EXIF 元数据。

<a href="assets/large-image-tiff.svg">
  <img src="assets/large-image-overview.svg" alt="Large artwork TIFF path" />
</a>

_截图来自当前 TUI 的真实渲染输出。_

## 更多文档

- [用法说明](usage.md)：CLI 用法、批量下载、恢复、重跑、冲突策略
- [大图说明](large-images.md)：大图行为、TIFF/BigTIFF、安全拼接、缓存复用
- [元数据说明](metadata.md)：`metadata-only`、sidecar、EXIF
- [测试说明](testing.md)：本地检查、测试分层、手动 smoke workflow
- [架构说明](architecture.md)：内部结构与实现说明
- [项目状态](project-status.md)：当前状态与后续计划

## 当前范围

- 当前面向单张作品页，不处理合集页或故事页
- 已支持大图 TIFF 输出，但默认链路不自动做 TIFF 到 JPEG 的转换
- 更丰富的元数据导出仍在后续计划中，但当前功能保持克制和稳定
- 项目采用 MIT 协议发布
