# googleart-download

下载 Google Arts & Culture 作品页里的高清图片。程序会解析页面里的瓦片元数据，下载所有瓦片并自动拼接成一张完整图片。

现在支持：

- 下载时日志输出
- 瓦片和批次进度条
- `--tui` 实时终端面板
- 多个 URL 批量下载
- `--url-file` 从文件读取 URL
- 页面、元数据、瓦片请求自动重试
- 批量任务状态跟踪和失败汇总
- 用户友好的尺寸选择：`--size` / `--max-dimension`
- 先查看可选尺寸：`--list-sizes`
- 已存在文件默认跳过
- 单作品 tile 缓存和中断后自动复用
- 超大图拼接前的内存风险保护
- 可选 `pyvips` 大图转换后端
- 可选 `bigtiff` 流式大图拼接后端
- 可选将作品元数据写入 JPEG EXIF
- 可选输出同名 JSON sidecar 元数据文件
- 失败作品可按批次轮次重跑

## 安装

```bash
uv sync
```

如果你需要更稳地处理超大图，安装大图拼接增强依赖：

```bash
uv sync --extra large-images
```

`pyvips` 还需要系统里的 `libvips`：

- macOS: `brew install vips`
- Debian/Ubuntu: `sudo apt install libvips libvips-dev`
- Fedora: `sudo dnf install vips vips-devel`
- Windows: 安装 `libvips` 发行包并把其 `bin` 目录加入 `PATH`

推荐直接用项目脚本：

```bash
uv run googleart-download --help
```

## 用法

```bash
uv run googleart-download "https://artsandculture.google.com/asset/recto-the-fetus-in-the-womb-verso-notes-on-reproduction-with-sketches-of-a-fetus-in-utero-etc-leonardo-da-vinci/qgFUAw5Zc1wsbw" -o downloads
```

也可以指定输出文件名：

```bash
uv run googleart-download "https://artsandculture.google.com/asset/recto-the-fetus-in-the-womb-verso-notes-on-reproduction-with-sketches-of-a-fetus-in-utero-etc-leonardo-da-vinci/qgFUAw5Zc1wsbw" -o downloads -f fetus.jpg
```

提高 tile 下载并发：

```bash
uv run googleart-download "https://artsandculture.google.com/asset/..." --workers 32
```

批量下载：

```bash
uv run googleart-download \
  "https://artsandculture.google.com/asset/recto-the-fetus-in-the-womb-verso-notes-on-reproduction-with-sketches-of-a-fetus-in-utero-etc-leonardo-da-vinci/qgFUAw5Zc1wsbw" \
  "https://artsandculture.google.com/asset/taj-mahal/7QHkbH1IgneKLA" \
  --tui \
  --log-file logs/run.log
```

从文件读取：

```bash
uv run googleart-download --url-file urls.txt --tui
```

重试参数：

```bash
uv run googleart-download "https://artsandculture.google.com/asset/..." --retries 5 --retry-backoff 1.0
```

失败作品按批次再跑一轮：

```bash
uv run googleart-download --url-file urls.txt --rerun-failures 1
```

先查看这张作品有哪些可选尺寸：

```bash
uv run googleart-download "https://artsandculture.google.com/asset/..." --list-sizes
```

只抓作品元信息，不下载图片：

```bash
uv run googleart-download "https://artsandculture.google.com/asset/..." --metadata-only
```

把元信息写到 JSON 文件：

```bash
uv run googleart-download "https://artsandculture.google.com/asset/..." --metadata-only --metadata-output metadata.json
```

多个 URL 一次抓取元信息：

```bash
uv run googleart-download \
  "https://artsandculture.google.com/asset/..." \
  "https://artsandculture.google.com/asset/..." \
  --metadata-only
```

多个 URL 的元信息抓取如果要直接写文件：

```bash
uv run googleart-download \
  "https://artsandculture.google.com/asset/..." \
  "https://artsandculture.google.com/asset/..." \
  --metadata-only \
  --metadata-output metadata/batch.json
```

按用户友好的预设尺寸下载：

```bash
uv run googleart-download "https://artsandculture.google.com/asset/..." --size preview
uv run googleart-download "https://artsandculture.google.com/asset/..." --size medium
uv run googleart-download "https://artsandculture.google.com/asset/..." --size large
uv run googleart-download "https://artsandculture.google.com/asset/..." --size max
```

按最长边限制下载：

```bash
uv run googleart-download "https://artsandculture.google.com/asset/..." --max-dimension 8000
```

批量失败时继续处理后续任务：

```bash
uv run googleart-download --url-file urls.txt
```

批量失败时立刻停止：

```bash
uv run googleart-download --url-file urls.txt --fail-fast
```

默认会跳过已经存在的目标文件。如果你需要强制重新下载：

```bash
uv run googleart-download --url-file urls.txt --no-skip-existing
```

默认不会修改图片 EXIF。如果你需要把作品信息写入输出 JPEG：

```bash
uv run googleart-download "https://artsandculture.google.com/asset/..." --write-metadata
```

如果你需要结构化元数据文件：

```bash
uv run googleart-download "https://artsandculture.google.com/asset/..." --write-sidecar
```

如果你两者都要：

```bash
uv run googleart-download "https://artsandculture.google.com/asset/..." --write-metadata --write-sidecar
```

控制拼图后端：

```bash
uv run googleart-download "https://artsandculture.google.com/asset/..." --stitch-backend auto
uv run googleart-download "https://artsandculture.google.com/asset/..." --stitch-backend pillow
uv run googleart-download "https://artsandculture.google.com/asset/..." --stitch-backend bigtiff
uv run googleart-download "https://artsandculture.google.com/asset/..." --stitch-backend pyvips
```

日志和详细输出：

```bash
uv run googleart-download "https://artsandculture.google.com/asset/..." --log-file logs/run.log -v
```

## 说明

- 需要完整的作品页 URL。你给的示例链接少了最后的作品 ID，正确格式通常是 `/asset/<slug>/<assetId>`。
- 如果从终端或聊天窗口复制 URL 时混入了换行或空格，程序会先清理这些空白字符再继续解析。
- 程序当前面向单张作品页，不处理整个合集或故事页。
- `--workers` 控制单张作品内部的 tile 下载并发数。默认值是自动计算的，通常不需要手动改；网络好、机器资源足够时可以适当调高，但过高可能触发限速、重试增多，甚至整体更慢。
- 如果大图下载过程中出现单个 tile 的 SSL / EOF / timeout 之类网络错误，通常可以直接重跑；已下载 tile 会从缓存复用。此时优先尝试提高 `--retries`，必要时再适当降低 `--workers`。
- `--filename` 只适用于单个 URL 下载；批量下载时不能和多个 URL 一起使用。
- `--list-sizes` 只适用于单个 URL；它会读取页面和瓦片元数据后直接退出，不会开始图片下载。
- `--metadata-only` 只抓作品页元信息并输出 JSON，不会下载 tile 或生成图片文件。
- `--metadata-only` 不能和 `--list-sizes` 同时使用。
- `--metadata-output` 可以把 `--metadata-only` 的结果写入 JSON 文件。
- `--metadata-output` 必须和 `--metadata-only` 一起使用。
- 单个 URL 使用 `--metadata-only` 且未指定 `--metadata-output` 时，会默认写出同名的 `.metadata.json` 文件。
- 单个 URL 使用 `--metadata-only` 时，如果元信息里没有可用标题，会回退到 `google-art.metadata.json`。
- 多个 URL 使用 `--metadata-only` 且未指定 `--metadata-output` 时，默认打印到标准输出。
- 多个 URL 使用 `--metadata-only` 时，如果你希望落到文件而不是标准输出，请显式传 `--metadata-output path/to/file.json`。
- 多个 URL 使用 `--metadata-only` 时，`--filename` 不生效，会直接报错。
- `--log-file` 会把日志写入文件，`-v` 会开启更详细的日志输出。
- `--tui` 会启用 richer terminal dashboard；如果你更喜欢纯 CLI 输出，可以不加它。
- 下载时会把单张作品的 tile 临时缓存到输出目录下的 `.googleart-cache/`。如果下载过程中中断，下次运行会自动复用已经完成的 tile。
- 单张作品成功写出后，会默认清理对应的 tile 缓存；失败时缓存会保留，便于恢复。
- 最终图片会先写到保留原扩展名的临时文件，再原子替换成目标文件，避免半成品污染正式输出。
- `--size` 是用户友好的语义化尺寸预设；`--max-dimension` 则允许你直接控制最长边上限。
- 默认仍然是 `--size max`，也就是下载当前可用的最大尺寸。
- `--list-sizes` 不会开始下载图片，只会读取页面和瓦片元数据，列出当前作品可选的层级尺寸和 tile 数。
- 输出文件命名规则：
  - `--size max` 默认不加尺寸后缀
  - 非 `max` 尺寸会自动加 `.preview` / `.medium` / `.large`
  - `--max-dimension 8000` 会自动加 `.maxdim-8000`
  - 如果显式传了 `--filename`，则完全尊重用户文件名
- `--stitch-backend auto` 会优先使用 Pillow；当图像过大、不适合安全内存拼接时，会切到 `bigtiff` 流式拼图。
- `bigtiff` 路径会先把 tile 流式写成 BigTIFF 成品；默认不再自动帮你转成 JPEG，这样比直接在内存里拼超大图更稳。
- 当 `auto` 或 `bigtiff` 选中了流式大图路径时，默认输出文件扩展名会调整为 `.tif`。
- 当前 `bigtiff` 和 `pyvips` 路径都还不支持写 JPEG EXIF。超大图场景下如果需要元数据，优先使用 `--write-sidecar`。
- 有些页面可能会被地区、权限或站点改版影响，如果 Google 改了瓦片签名规则，代码也需要跟着调整。
- 目前的 TUI 是基于 `rich` 的 live dashboard，不是复杂的全屏交互应用。这是有意为之，因为当前任务流是单向下载任务，`rich` 方案更稳、更容易维护。
- 包代码现在采用 `src/` 目录布局。根目录的 `main.py` 只是兼容入口。
