# googleart-download

[![Python 3.13+](https://img.shields.io/badge/python-3.13%2B-3776AB.svg)](#安装)
[![Version 0.1.0](https://img.shields.io/badge/version-0.1.0-0f766e.svg)](pyproject.toml)

[English README](README.md)

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
uv run googleart-download --help
```

如果你需要大图相关的可选增强依赖：

```bash
uv sync --extra large-images
```

## 快速开始

下载一张作品：

```bash
uv run googleart-download "https://artsandculture.google.com/asset/girl-with-a-pearl-earring/3QFHLJgXCmQm2Q" -o downloads
```

直接使用较短的 asset id：

```bash
uv run googleart-download "3QFHLJgXCmQm2Q" --size preview
```

先查看可选尺寸：

```bash
uv run googleart-download "3QFHLJgXCmQm2Q" --list-sizes
```

只导出作品元数据：

```bash
uv run googleart-download "3QFHLJgXCmQm2Q" --metadata-only
```

![Terminal preview](docs/assets/tui-preview.svg)

_截图来自当前 TUI 的真实渲染输出。_

## 常见任务

使用更友好的尺寸预设：

```bash
uv run googleart-download "3QFHLJgXCmQm2Q" --size preview
uv run googleart-download "3QFHLJgXCmQm2Q" --size medium
uv run googleart-download "3QFHLJgXCmQm2Q" --size large
uv run googleart-download "3QFHLJgXCmQm2Q" --size max
```

恢复被中断的批量任务：

```bash
uv run googleart-download --url-file urls.txt --resume-batch
```

只重跑上一次失败的任务：

```bash
uv run googleart-download --rerun-failed
```

写 sidecar 或 EXIF 元数据：

```bash
uv run googleart-download "3QFHLJgXCmQm2Q" --write-sidecar
uv run googleart-download "3QFHLJgXCmQm2Q" --write-metadata
```

控制 JPEG 质量：

```bash
uv run googleart-download "3QFHLJgXCmQm2Q" --jpeg-quality 85
uv run googleart-download "3QFHLJgXCmQm2Q" --jpeg-preset balanced
```

## 输出格式说明

普通尺寸作品默认输出 JPEG。

对于非常大的作品，程序会自动切换到 TIFF/BigTIFF 输出。这是刻意的设计，不是异常回退。原因是超大图更适合使用流式拼接，而不是整张图进内存后再写 JPEG。

大图自动转 JPEG 不属于默认下载路径。如果你最终仍然需要 JPEG，建议把生成的 TIFF 作为后处理再转换。

![Large artwork TIFF path](docs/assets/large-image-tiff.svg)

_截图来自当前 TUI 的真实渲染输出。_

## 更多文档

- [用法说明](docs/usage.md)：CLI 用法、批量下载、恢复、重跑、冲突策略
- [大图说明](docs/large-images.md)：大图行为、TIFF/BigTIFF、安全拼接、缓存复用
- [元数据说明](docs/metadata.md)：`metadata-only`、sidecar、EXIF
- [架构说明](docs/architecture.md)：内部结构与实现说明
- [项目状态](docs/project-status.md)：当前状态与后续计划

## 当前范围

- 当前面向单张作品页，不处理合集页或故事页
- 已支持大图 TIFF 输出，但默认链路不自动做 TIFF 到 JPEG 的转换
- 更丰富的元数据导出仍在后续计划中，但当前功能保持克制和稳定
