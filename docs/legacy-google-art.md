# Google Art Downloader

A batteries-included CLI for downloading Google Arts & Culture images in custom sizes and formats.

本工具是一个命令行程序，支持从 Google Arts & Culture 下载作品原图（按需选择缩放层级），并本地拼接、裁剪与格式转换。提供异步高并发下载与批量模式，对超大幅面可选用 libvips（pyvips）进行高效拼接。

## Features / 特性

- Accept URL or asset slug/ID / 接受完整 URL 或作品短 ID
- Auto-select zoom level / 自动选择合适缩放层级
- Local tile reassembly / 本地瓦片拼接
- Save PNG, JPEG, or WebP / 输出 PNG、JPEG、WebP
- Async high-concurrency downloading / 异步高并发下载
- Optional libvips (pyvips) assembler for ultra-large mosaics / 可选 pyvips 以处理超大幅面
- Batch mode to download multiple assets in parallel / 批量下载
- Reproducible dependencies via uv / 使用 uv 管理依赖

## Requirements / 环境

- Python 3.12+
- uv (https://docs.astral.sh/uv/)
- Optional: libvips (pyvips) for very large outputs / 可选安装 pyvips 以处理超大图

## Setup / 安装

```sh
uv sync
# Optional (推荐用于超大图):
uv add pyvips
```

验证 pyvips 是否可用：
```sh
uv run python -c "import pyvips; print(pyvips.version(0), pyvips.version(1), pyvips.version(2))"
```

## CLI Usage / 命令用法

```text
Usage: google-art [OPTIONS] [ASSETS]...

Arguments:
  ASSETS...  Artwork URLs or asset slugs/IDs; optional when using --from-file.

Options:
  -o, --output PATH                 Output file or directory. If a directory
                                    (or path without known image suffix), files
                                    are named from artwork titles.
  -f, --format TEXT                 Image format (png, jpg, webp). [default: png]
  -s, --size INTEGER                Maximum image edge in pixels (optional).
      --overwrite                   Overwrite existing files.
      --no-progress                 Disable progress bar.
      --assembler TEXT              Image assembler: auto|pillow|vips [default: auto]
      --net-concurrency INTEGER     Global network concurrency (async). [default: 32]
      --per-asset-concurrency INTEGER
                                    Per-asset network concurrency. [default: 8]
      --queue-size INTEGER          Buffered tile results per asset. [default: 256]
      --jobs INTEGER                How many assets to download in parallel. [default: 3]
      --from-file PATH              Read assets from a newline-delimited file.
      --help                        Show this message and exit.
```

## Quick Start / 快速开始

Single asset / 单个作品：
```sh
uv run google-art -o art.png --size 2048 --format png \
  https://artsandculture.google.com/asset/reference-image/JwFSVlTCVoT_nA
```

Batch from file (one asset per line) / 从文件批量：
```sh
uv run google-art --from-file assets.txt -o downloads/ --jobs 3 --size 4096 --assembler auto
```

Force libvips for ultra-large outputs / 对超大图强制 vips：
```sh
uv run google-art --assembler vips --size 20000 -o giant.jpg reference-image/JwFSVlTCVoT_nA
```

## How It Works / 工作流程

1. Fetch artwork page and extract tile base URL and token / 解析作品页拿到瓦片基址与 token
2. Request tile manifest (=g) to get pyramid levels / 请求清单了解金字塔层级
3. Download required tiles asynchronously / 异步拉取所需瓦片
4. Stitch tiles on a large canvas (Pillow or pyvips) / 使用 Pillow 或 pyvips 拼接
5. Crop to real dimensions, optional resize, and save / 裁剪、按需缩放并保存

## Architecture / 架构

命令行与批量调度分离，同步和异步接口复用下载计划、网络响应处理、拼接后端和文件发布规则。

```text
cli → service.download_many → AsyncGoogleArtDownloader
Python callers             → GoogleArtDownloader / AsyncGoogleArtDownloader
                                ├─ parser + models → planning.DownloadPlan
                                ├─ transport + tiles → tile bytes
                                ├─ assemblers → crop / resize / encode
                                └─ output → staged file / atomic publication
```

| 模块 | 职责 |
| --- | --- |
| `models.py`、`parser.py`、`planning.py` | 参数和清单校验、元数据解析、层级与尺寸选择、输出路径计算 |
| `transport.py`、`tiles.py` | 请求头、响应校验、瓦片签名与解密、可重试错误策略 |
| `downloader.py`、`async_downloader.py` | 同步请求循环 / 异步有界 worker 与队列 |
| `service.py` | 批量 jobs 限制、结果顺序、共享网络额度、批次输出冲突检查 |
| `assemblers.py` | Pillow / pyvips 后端选择及图像资源管理 |
| `concurrency.py`、`output.py`、`progress.py` | 阻塞图像操作的线程桥接、原子文件发布、共享进度展示 |
| `cli.py` | 参数输入与结果展示 |

运行约束：

- `--net-concurrency` 限制整个批次的同时网络请求数，包含作品页和清单；`--per-asset-concurrency` 限制每个作品的瓦片 worker 数。
- 每个作品只创建固定数量的 worker，下载结果通过有界队列传递。缓冲瓦片数量与队列和 worker 数有关，不随作品总瓦片数创建同等数量的任务。拼接画布或 vips 图本身仍需要内存。
- `TaskGroup` 在下载或解码失败时取消并等待同组任务；批次已有成功文件会保留。返回路径按输入顺序排列。
- 图像解码和编码在线程中执行。取消时会等待正在执行的图像操作结束，再释放资源；尚未完成发布的临时文件会被清理。
- 只有完整编码的图片才会发布到最终路径。不开启覆盖时，即使其他进程在下载期间创建目标文件，也会拒绝覆盖。Windows 使用 rename；POSIX 的无覆盖发布要求输出文件系统支持硬链接。
- 批量命令的 `--output` 必须是目录。同一批次多个作品解析出同一文件名会报错，即使设置 `--overwrite`；可通过 Python API 给作品指定不同文件名。
- 显式 `--assembler vips` 在依赖缺失时直接报错，只有 `auto` 可回退到 Pillow。`size`、并发数、队列大小和 `jobs` 必须为正数。
- 瓦片请求仅对网络传输错误、HTTP 429 和 5xx 重试，最多三次；其他 HTTP 错误与非图像响应直接报告。

## Python API

同步调用：

```python
from google_art import DownloadOptions, GoogleArtDownloader

with GoogleArtDownloader(show_progress=False) as downloader:
    path = downloader.download(
        DownloadOptions(
            asset="reference-image/JwFSVlTCVoT_nA",
            out_path="downloads/",
            max_edge=2048,
        )
    )
```

异步批量调用（脚本中运行；已有事件循环时直接 `await download_many(...)`）：

```python
import asyncio
from google_art import AsyncOptions, download_many


async def main():
    return await download_many(
        [
            AsyncOptions(asset=asset, out_path="downloads/", max_edge=2048, net_concurrency=16, per_asset_concurrency=4)
            for asset in ["reference-image/JwFSVlTCVoT_nA"]
        ],
        jobs=3,
    )


paths = asyncio.run(main())
```

`GoogleArtDownloader` 和 `AsyncGoogleArtDownloader` 分别接受调用方提供的 `httpx.Client` 和 `httpx.AsyncClient`；注入的 client 由调用方关闭，自动创建的 client 由 downloader 关闭。异步 downloader 实例应在同一事件循环内使用；首次下载确定网络额度，同实例后续下载须使用相同的 `net_concurrency`。异步工作组错误通过 `ExceptionGroup` 传播，CLI 会展开并展示具体原因。

兼容说明：保留原有 downloader、options 的导入路径以及 `close()` / `aclose()`。同步接口的无图片扩展名输出路径现在与 CLI 一致，视为目录。已停用的 `browser_factory` 参数仅为兼容保留，并发出弃用提示。

## Troubleshooting / 故障排查

- Received non-image data while downloading tiles：可能触发了反滥用机制或网络拦截。
  - 尝试降低并发：`--net-concurrency 16 --per-asset-concurrency 4`
  - 使用代理：设置 `HTTP_PROXY` / `HTTPS_PROXY`
  - 开启调试：
    ```powershell
    $env:GOOGLE_ART_DEBUG = '1'
    uv run google-art -o art.png <ART_URL>
    ```
- 超大幅面（上万像素边长或数千瓦片）：建议 `--assembler vips` 或保持 `--assembler auto` 让程序自动切换。

## Testing / 测试

```sh
uv run pytest
```

## Development / 开发

```sh
uv sync
uv run pytest
uv run google-art --help
```

## Notes / 注意

- This tool does not bypass access controls / 本工具不绕过任何访问控制
- Respect Google Arts & Culture terms of service / 请遵守相关服务条款
- Some assets may be unavailable depending on region or anti-abuse systems / 作品可用性可能受地区或风控影响
