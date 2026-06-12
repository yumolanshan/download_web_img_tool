# 图片下载工具 (idl_tool)

一个用于从网页批量下载图片的小工具，包含命令行爬虫（`imgdl.py`）和基于 Tkinter 的图形界面（`idl_tool.py`）。  
支持断点续传、暂停/取消下载、自动去重、图片格式转换（可选 PNG）等功能。

## 主要功能

- 自动解析网页中的图片链接，优先尝试获取原图
- 支持按 **页数** 批量下载，可指定起始页
- 自动记录已下载的图片 URL 及当前页码，支持断点续传（从上次中断的位置继续）
- 图形界面提供下载进度、成功/失败计数、耗时显示，并支持暂停/取消
- 可选将下载的图片统一转换为 PNG 格式（默认开启）
- 可调节下载请求间隔，避免对目标网站造成压力

## 依赖环境

- Python 3.8+（推荐 3.10 以上）
- 第三方库：`requests`, `beautifulsoup4`, `lxml`（推荐），`Pillow`

## 安装

1. 克隆或下载本仓库代码。
2. 建议创建虚拟环境：
   ```bash
   python -m venv venv
   source venv/bin/activate      # Linux/macOS
   venv\Scripts\activate         # Windows
   ```
3. 安装依赖：
   ```bash
   pip install requests beautifulsoup4 lxml Pillow
   ```

也可以使用提供的 `requirements.txt`（如果有）：
```bash
pip install -r requirements.txt
```

## 使用方式

### 1. 命令行模式（imgdl.py）

```bash
python imgdl.py [页数] [--start-page 起始页] [--url 目标网址] [--delay 秒数] [--no-convert]
```

**参数说明**

| 参数 | 类型 | 说明 |
|------|------|------|
| `pages` | 位置参数，整数 | 要下载的**页数**，必须 ≥1。例如 `10` 表示下载前 10 页。 |
| `--start-page` | 整数 | 起始页码（≥1）。不指定时会尝试断点续传（从上次进度继续），若无记录则从第 1 页开始。 |
| `--url` | 字符串 | 目标网站首页 URL。默认为 `https://mikagogo.com/pc-wallpaper`。 |
| `--delay` | 浮点数 | 每张图片下载后的等待秒数，默认 `1.0`。调大可降低对目标服务器的压力。 |
| `--no-convert` | 标志 | 不将图片转换为 PNG 格式，保留原始格式。 |

**示例**

- 下载前 5 页（从第 1 页开始）：
  ```bash
  python imgdl.py 5
  ```
- 从第 3 页开始下载 10 页：
  ```bash
  python imgdl.py 10 --start-page 3
  ```
- 指定其他网站，下载 2 页，间隔 0.5 秒：
  ```bash
  python imgdl.py 2 --url "https://example.com/gallery" --delay 0.5
  ```
- 下载但不转换为 PNG：
  ```bash
  python imgdl.py 5 --no-convert
  ```

### 2. 图形界面模式（idl_tool.py）

直接运行图形界面程序：

```bash
python idl_tool.py
```

界面包含以下控件：

- **网页网站 URL**：目标网站的首页地址。
- **下载页数**：希望下载的总页数。
- **起始页**：（可选）指定从第几页开始下载，留空则自动续传或从第 1 页开始。
- **发现总数**：当前已解析出的图片总张数。
- **下载成功 / 下载失败**：实时统计。
- **耗时**：从开始下载到当前经过的时间。
- **状态栏**：显示提示信息或错误信息。
- **控制按钮**：下载、暂停、继续、取消。

下载过程中可以**暂停**（再次点击变为“继续”）、**取消**。取消后会保存当前进度，下次启动时可从断点继续。

## 续传机制（断点续爬）

工具在运行时会自动保存以下文件到脚本所在目录：

- `crawl_state.json`：记录当前网站的 `site_url`、最后访问的页面 URL（`last_page_url`）和下一页 URL（`next_page_url`）。
- `downloaded_urls.json`：记录所有已成功下载的图片 URL。

**续传逻辑**：

- 如果未指定 `--start-page`（或在 GUI 中“起始页”留空），程序会尝试读取 `crawl_state.json`。
- 若记录中的 `site_url` 与当前目标 URL 一致且存在 `next_page_url`，则从该 URL 继续爬取下一页，避免重复下载同一页。
- 已下载的图片 URL 会被自动跳过，不会重复下载。

## 开发与扩展

### 在自己的代码中调用爬虫

```python
from imgdl import ImageCrawler, CrawlConfig, ControlState

config = CrawlConfig(base_url="https://example.com/gallery/", convert_to_png=True)
crawler = ImageCrawler(config)
result = crawler.crawl_pages(page_limit=5, start_page=2)   # 从第2页开始，下载5页
print(f"成功: {result['total_images']}, 失败: {result['failed_images']}")
```

支持自定义回调（进度、图片计数等），详见 `ImageCrawler` 的构造函数。

### 控制状态枚举

暂停/取消功能基于 `ControlState` 枚举：
- `ControlState.RUNNING`：正常运行
- `ControlState.PAUSED`：暂停
- `ControlState.CANCELLED`：取消

可在多线程环境中通过 `control_callback` 函数返回当前状态来控制爬虫。

## 常见问题

**Q: 下载的图片不是原图，而是缩略图怎么办？**  
A: 程序已内置常见缩略图 URL 特征过滤（如 `-thumb`, `-small` 等），并尝试从 `<a>` 标签中查找原图链接。若仍无法获取原图，可尝试修改 `ImageCrawler._find_direct_image_link` 方法。

**Q: 遇到反爬虫机制怎么办？**  
A: 可以增加 `--delay` 参数（例如 2~3 秒），或修改 `CrawlConfig` 中的 `headers` 模拟更真实的浏览器请求。若网站需要登录或 Cookie，请自行扩展相关逻辑。

**Q: 图片保存到哪里？**  
A: 默认保存在脚本所在目录下的 `img` 文件夹中。文件名格式为 `YYYYMMDD_HHMMSS.png`（或 `_序号.png` 以处理同一秒内多张图片）。可通过修改 `CrawlConfig.img_dir` 改变保存路径。

**Q: 如何停止正在进行的下载？**  
A: 在图形界面中点击“取消”按钮；在命令行模式下可按 `Ctrl+C` 中断程序，中断时会自动保存当前进度。

**Q: 为什么我指定的起始页无效？**  
A: 请确保起始页 ≥ 1。如果之前有断点续传记录且未清除，程序会优先续传，除非你明确指定了 `--start-page`。如需强制重置，请手动删除 `crawl_state.json` 文件。

## 注意事项

- 请遵守目标网站的 `robots.txt` 以及相关法律法规，不要过于频繁地请求，避免对服务器造成负担。
- 本工具仅供学习交流使用，下载的图片版权归原作者所有。

## 许可

本项目无特殊许可声明，仅供内部学习和使用。
