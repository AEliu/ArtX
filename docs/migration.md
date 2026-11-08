# ArtX 整合与迁移

本工作版本为 `0.4.2.dev0`，尚未发布。它以 ArtX `0.4.1` 为主，保留原本地 `google_art` 接口和 `google-art` 命令。

## 已核实的项目历史

核对日期：2026-11-08。

- 本地目录名称仍是 `google-art`，但 `origin` 已指向 [AEliu/ArtX](https://github.com/AEliu/ArtX)。目录名不会随 GitHub 仓库改名自动改变。
- 远端 [91966a7](https://github.com/AEliu/ArtX/commit/91966a7)（2026-03-18）将项目品牌及 CLI 改为 ArtX / `artx`。
- 远端 [a4d95b5](https://github.com/AEliu/ArtX/commit/a4d95b5)（2026-03-19）将 Python 包从 `googleart_download` 改为 `artx`，并提供旧包兼容层。
- 本次导入的远端基线为 [3f2fdf18c77255b27560b636751ce8f668104e36](https://github.com/AEliu/ArtX/commit/3f2fdf18c77255b27560b636751ce8f668104e36)。本地整合前基线为 `61fc7cf`。
- 两个基线的 `git merge-base` 没有共同祖先。这只能证明当前 Git 历史不相连，不能据此断定当时使用了什么复制或重新初始化命令。

此次采用远端源码快照整合，而非直接 `git pull` 或合并不相连的历史；本地旧实现和测试继续保留。今后对比上游时，可使用上述远端提交作为基线。

## 三个 Python 包的关系

| 包 / 命令 | 当前定位 | 参数与行为 |
| --- | --- | --- |
| `artx` / `uv run artx` | 主应用 | 瓦片缓存、批量恢复、元数据、尺寸预设、TIFF/BigTIFF |
| `googleart_download` | ArtX 历史导入兼容层 | 转发至 `artx`，导入时发出 `DeprecationWarning`；沿用上游的两个 minor 版本过渡约定 |
| `google_art` / `uv run google-art` | 原本地 API 与 CLI | 保留同步/异步 downloader、PNG/JPEG/WebP、精确缩小尺寸和原参数 |

`google_art` 不是 `googleart_download` 的别名。它保留独立实现，不能通过简单替换 import 名称迁移到 ArtX 的数据模型。

## 现在如何运行

在项目根目录打开终端：

```powershell
uv sync --locked
uv run artx --help
uv run artx "3QFHLJgXCmQm2Q" --size preview -o downloads
```

也可使用 `uv run python -m artx --help` 或 `uv run python main.py --help`；两者均进入 ArtX。

批量文件每行填写一个作品 URL 或 ID：

```powershell
uv run artx --url-file assets.txt --size medium -o downloads
uv run artx --url-file assets.txt --size medium --resume-batch -o downloads
uv run artx --rerun-failed --size medium -o downloads
```

恢复批次时应使用相同的输出目录，并保持所需下载选项一致。缓存与批次状态都保存在输出目录内。实际请求需要能访问 Google Arts & Culture；如需显式代理，可添加 `--proxy http://127.0.0.1:7890` 并替换为自己的代理地址。

可选大图依赖：

```powershell
uv sync --locked --extra large-images
uv run --extra large-images artx "3QFHLJgXCmQm2Q" --size max -o downloads
```

`large-images` 提供 BigTIFF 所需的 numpy/tifffile 以及 pyvips Python 包；显式选择 pyvips 时还需要系统 libvips。普通预览下载无需安装这组依赖。

旧版命令仍然可以运行：

```powershell
uv run google-art "3QFHLJgXCmQm2Q" --size 2048 --format png -o downloads/preview.png
```

## 参数对照

| 意图 | 原 `google-art` | 主 `artx` |
| --- | --- | --- |
| 从文件读取 | `--from-file assets.txt` | `--url-file assets.txt` |
| 指定输出目录 | `-o downloads` | `-o downloads` |
| 指定文件名 | `-o downloads/art.png` | `-o downloads --filename art.png` |
| 缩小图像 | `--size 2048`，拼接后按最长边缩小，不放大 | `--size preview/medium/large/max` 或 `--max-dimension 2048`，选择已有瓦片层级，不进行精确像素缩放 |
| 覆盖已有文件 | `--overwrite` | `--output-conflict overwrite` |
| 并发 | `--net-concurrency`、`--per-asset-concurrency`、`--jobs` | `--workers`；批次可用 `--pipeline-artworks` 重叠一个下载阶段与一个拼接阶段 |
| 拼接后端 | `--assembler auto/pillow/vips` | `--stitch-backend auto/pillow/bigtiff/pyvips` |

两个 CLI 的默认格式也不同：旧接口默认 PNG，ArtX 默认 JPEG，并会为不适合内存拼接的大图选择 TIFF。请分别查阅帮助，不要把旧选项直接传给新命令。

## 本次整合的可靠性改进

- 导入 ArtX 的完整运行时、缓存恢复、元数据与批次工作流及测试。
- 将 ArtX 的每瓦片 task 改为固定数量 worker；缓存写入也占用 worker 配额，防止慢磁盘造成响应体堆积。
- 失败或取消时等待所有 worker 和已开始的线程写入结束；完整瓦片保留用于恢复，失败写入的 `.part` 文件清理。
- Pillow / BigTIFF 图像资源显式关闭；pyvips 按输出格式选择编码参数。
- 覆盖图片时保留已有文件，直到新图片完整编码后再替换。tile-only 目录覆盖仍沿用上游语义，并非目录级事务。
- 保留原本地共享网络额度、有界队列、线程取消保护和原子输出等改进。

依赖清单包含两套入口需要的运行时。此前本地已有的 `artfetch`、`json5` 也保留在清单中，但它们不是 ArtX 主下载流程的实现依据。

更多信息：[中文使用说明](README.zh-CN.md)、[旧接口说明](legacy-google-art.md)、[架构](architecture.md)、[测试](testing.md)。
