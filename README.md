# 图片下载工具 (idl_tool)

这是一个用于从网站批量下载图片的小工具，包含命令行爬虫 (`imgdl.py`) 和基于 Tkinter 的简单 GUI (`idl_tool.py` / `case_11.py`)。

主要功能
- 优先尝试获取图片的原图链接并下载
- 支持从指定起始页继续爬取或从上次保存的位置继续
- 命令行与图形界面两种使用方式

依赖
- Python 3.8+
- requests
- beautifulsoup4
- lxml（可选，作为 BeautifulSoup 的解析器，加速与提高兼容性）

安装依赖（推荐创建虚拟环境）

```bash
pip install -r requirements.txt
```

如果没有 `requirements.txt`，可单独安装：

```bash
pip install requests beautifulsoup4 lxml
```

命令行使用（示例）

```bash
python imgdl.py 20 --start-page 1
```

- 第一个位置参数 `count`：要下载的图片数量，必须为正整数（>=1）。
- `--start-page`：可选，指定从第几页开始爬取（>=1）。若不提供，则会尝试读取 `crawl_state.json` 中的 `next_page_url` 继续上次进度，若无记录则从首页开始。

图形界面使用

- 运行 `idl_tool.py`（或 `case_11.py`），会弹出一个窗口：可填写网站 URL、下载数量、起始页。
- 界面使用线程执行下载，避免界面无响应。

重要说明与错误处理
- `start_page` 必须为 >= 1，否则程序会抛出错误并提示。
- `target_count`（下载数量）必须为 >= 1，否则程序会抛出错误。
- 程序会把已下载的图片保存到 `img` 目录（脚本所在目录的 `img/`，可在构造 `ImageCrawler` 时传入 `img_dir` 覆盖）。
- 状态文件 `crawl_state.json` 会记录 `site_url`、`last_page_url`、`next_page_url`，用于断点续爬。

常见问题
- 无法下载图片：检查目标网站是否有反爬机制，或者图片链接不是标准后缀（jpg/png/webp）。
- 乱码或解析失败：尝试安装 `lxml` 并确认网络请求成功。

示例

```python
from imgdl import ImageCrawler

crawler = ImageCrawler(base_url='https://www.example.com/')
result = crawler.crawl_pages(target_count=30, start_page=1)
print('下载完成：', result['downloaded'])
```

许可
- 无特殊许可声明，内部学习与使用即可。请遵守目标网站的 robots.txt 与使用条款。
