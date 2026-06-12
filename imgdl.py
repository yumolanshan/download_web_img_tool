import argparse
import json
import logging
import re
import time
from dataclasses import dataclass, field
from datetime import datetime
from enum import IntEnum
from io import BytesIO
from pathlib import Path
from typing import Dict, List, Optional, Set, Callable, Any, Tuple
from urllib.parse import urljoin   # ← 补充遗漏导入

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from bs4 import BeautifulSoup
from PIL import Image

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


class ControlState(IntEnum):
    RUNNING = 0
    PAUSED = 1
    CANCELLED = 2


@dataclass
class CrawlConfig:
    """爬虫配置"""
    base_url: str
    img_dir: Path = field(default_factory=lambda: Path(__file__).parent / 'img')
    state_path: Path = field(default_factory=lambda: Path(__file__).parent / 'crawl_state.json')
    downloaded_urls_path: Path = field(default_factory=lambda: Path(__file__).parent / 'downloaded_urls.json')
    headers: Dict[str, str] = field(default_factory=lambda: {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
    })
    request_timeout: int = 10
    download_delay: float = 1.0
    max_retries: int = 3
    retry_backoff: float = 1.0
    convert_to_png: bool = True


@dataclass
class CrawlState:
    site_url: str
    next_page_url: Optional[str] = None
    last_page_url: Optional[str] = None


class StateManager:
    def __init__(self, config: CrawlConfig):
        self.config = config
        self.state: Optional[CrawlState] = None
        self.downloaded_urls: Set[str] = set()
        self._dirty_urls = False          # 标记是否需要保存
        self._load_state()
        self._load_downloaded_urls()

    def _load_json_file(self, path: Path) -> Optional[Any]:
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text(encoding='utf-8'))
        except Exception as e:
            logger.warning(f"加载文件失败 {path.name}: {e}")
            return None

    def _load_state(self) -> None:
        data = self._load_json_file(self.config.state_path)
        if data:
            self.state = CrawlState(
                site_url=data.get('site_url', ''),
                next_page_url=data.get('next_page_url'),
                last_page_url=data.get('last_page_url')
            )

    def _load_downloaded_urls(self) -> None:
        data = self._load_json_file(self.config.downloaded_urls_path)
        if data:
            self.downloaded_urls = set(data)
            logger.info(f"已加载 {len(self.downloaded_urls)} 条已下载记录")

    def save_state(self, state: CrawlState) -> None:
        self.config.state_path.write_text(
            json.dumps({
                'site_url': state.site_url,
                'next_page_url': state.next_page_url,
                'last_page_url': state.last_page_url,
            }, ensure_ascii=False, indent=2),
            encoding='utf-8'
        )
        self.state = state

    def save_downloaded_urls(self) -> None:
        if self._dirty_urls:
            self.config.downloaded_urls_path.write_text(
                json.dumps(list(self.downloaded_urls), ensure_ascii=False, indent=2),
                encoding='utf-8'
            )
            self._dirty_urls = False

    def is_url_downloaded(self, url: str) -> bool:
        return url in self.downloaded_urls

    def add_downloaded_url(self, url: str) -> None:
        if url not in self.downloaded_urls:
            self.downloaded_urls.add(url)
            self._dirty_urls = True

    def get_resume_url(self) -> Optional[str]:
        if self.state and self.state.site_url == self.config.base_url and self.state.next_page_url:
            return self.state.next_page_url
        return None


class ImageCrawler:
    IMAGE_EXT_RE = re.compile(r'\.(?:jpg|jpeg|png|webp)(?:\?.*)?$', re.I)
    THUMBNAIL_SUFFIX_RE = re.compile(
        r'(?i)(?:[-_](?:pcthumbs|thumbs?|arthumbs|bannerthumbs|small|mini|large))(?=(?:\?.*)?$)'
    )
    NEXT_PAGE_TEXT = ('下一页', 'next', '›', '»')

    def __init__(self, config: CrawlConfig,
                 progress_callback: Optional[Callable[[int, int], None]] = None,
                 image_result_callback: Optional[Callable[[int, int], None]] = None,
                 total_found_callback: Optional[Callable[[int], None]] = None,
                 control_callback: Optional[Callable[[], ControlState]] = None):
        self.config = config
        self.state_mgr = StateManager(config)
        self.progress_callback = progress_callback
        self.image_result_callback = image_result_callback
        self.total_found_callback = total_found_callback
        self.control_callback = control_callback
        self.session = self._create_session()
        self._last_used_timestamp: Optional[str] = None
        self._counter: int = 0
        self.total_downloaded = 0
        self.total_failed = 0
        self.total_found = 0

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.session.close()

    def _create_session(self) -> requests.Session:
        session = requests.Session()
        retries = Retry(
            total=self.config.max_retries,
            backoff_factor=self.config.retry_backoff,
            status_forcelist=[500, 502, 503, 504]
        )
        adapter = HTTPAdapter(max_retries=retries)
        session.mount('http://', adapter)
        session.mount('https://', adapter)
        session.headers.update(self.config.headers)
        return session

    def _check_control(self) -> None:
        """检查控制状态，暂停时循环等待，取消时抛出异常"""
        if not self.control_callback:
            return
        while True:
            state = self.control_callback()
            if state == ControlState.RUNNING:
                break
            elif state == ControlState.PAUSED:
                time.sleep(0.1)
            elif state == ControlState.CANCELLED:
                raise InterruptedError("用户取消下载")

    def _build_page_url(self, page_number: int) -> str:
        if page_number == 1:
            return self.config.base_url
        return f"{self.config.base_url}page/{page_number}/"

    def resolve_start_page(self, start_page: Optional[int] = None) -> str:
        if start_page is not None and start_page >= 1:
            return self._build_page_url(start_page)
        resume_url = self.state_mgr.get_resume_url()
        if resume_url:
            logger.info(f"断点续传，从 {resume_url} 继续")
            return resume_url
        return self.config.base_url

    def fetch_page_soup(self, url: str) -> BeautifulSoup:
        try:
            resp = self.session.get(url, timeout=self.config.request_timeout)
            resp.encoding = 'utf-8'
            resp.raise_for_status()
            try:
                return BeautifulSoup(resp.text, 'lxml')
            except Exception:
                return BeautifulSoup(resp.text, 'html.parser')
        except Exception as e:
            logger.error(f"获取页面失败 {url}: {e}")
            raise

    def _normalize_image_url(self, src: str) -> str:
        src = src.strip()
        src = self.THUMBNAIL_SUFFIX_RE.sub('', src)
        if src.endswith('?.'):
            src = src[:-2]
        return src

    def _is_image_url(self, url: str) -> bool:
        return bool(self.IMAGE_EXT_RE.search(url))

    def _find_direct_image_link(self, img_tag) -> Optional[str]:
        data_orig = img_tag.get('data-original') or img_tag.get('data-src')
        if data_orig and self._is_image_url(data_orig):
            return self._normalize_image_url(data_orig)
        parent_a = img_tag.find_parent('a', href=True)
        if parent_a and self._is_image_url(parent_a['href']):
            return self._normalize_image_url(parent_a['href'])
        sibling_a = img_tag.find_next_sibling('a', href=True)
        if sibling_a and self._is_image_url(sibling_a['href']):
            return self._normalize_image_url(sibling_a['href'])
        return None

    def extract_image_urls(self, soup: BeautifulSoup) -> List[str]:
        urls = []
        base = self.config.base_url
        for img in soup.find_all('img'):
            src = img.get('data-original') or img.get('data-src') or img.get('src')
            if not src:
                continue
            if src.startswith('//'):
                full_src = 'https:' + src
            else:
                full_src = urljoin(base, src)
            direct_url = self._find_direct_image_link(img)
            candidate = direct_url or self._normalize_image_url(full_src)
            if not self._is_image_url(candidate):
                continue
            if any(blocked in candidate.lower() for blocked in ('logo', 'avatar', 'icon')):
                continue
            urls.append(candidate)

        seen = set()
        unique = []
        for u in urls:
            if u not in seen:
                seen.add(u)
                unique.append(u)
        return unique

    def find_next_page_url(self, soup: BeautifulSoup, current_url: str) -> Optional[str]:
        for a in soup.find_all('a', href=True):
            text = a.get_text(strip=True).lower()
            if any(keyword in text for keyword in self.NEXT_PAGE_TEXT):
                return urljoin(current_url, a['href'])
        for a in soup.find_all('a', href=True):
            if re.search(r'/page/\d+/?(?:/|$)', a['href']):
                return urljoin(current_url, a['href'])
        return None

    def _generate_unique_filename(self) -> str:
        now = datetime.now()
        base = now.strftime("%Y%m%d_%H%M%S")
        if self._last_used_timestamp == base:
            self._counter += 1
            return f"{base}_{self._counter}.png"
        else:
            self._last_used_timestamp = base
            self._counter = 0
            return f"{base}.png"

    def _save_as_png(self, image_data: bytes) -> bytes:
        try:
            with Image.open(BytesIO(image_data)) as img:
                if img.mode in ('RGBA', 'LA', 'P'):
                    if img.mode == 'P':
                        img = img.convert('RGBA')
                    rgb_img = Image.new('RGB', img.size, (255, 255, 255))
                    if img.mode == 'RGBA':
                        alpha = img.split()[-1]
                        rgb_img.paste(img, mask=alpha)
                    else:
                        rgb_img.paste(img)
                    img = rgb_img
                elif img.mode != 'RGB':
                    img = img.convert('RGB')
                output = BytesIO()
                img.save(output, format='PNG')
                return output.getvalue()
        except Exception as e:
            logger.error(f"图片转换 PNG 失败: {e}")
            return image_data

    def download_images(self, img_urls: List[str]) -> Tuple[int, int]:
        downloaded_this = 0
        failed_this = 0
        for img_url in img_urls:
            self._check_control()   # 每张图片前检查
            if self.state_mgr.is_url_downloaded(img_url):
                logger.debug(f"已下载跳过: {img_url}")
                continue

            filename = self._generate_unique_filename()
            filepath = self.config.img_dir / filename

            try:
                resp = self.session.get(img_url, timeout=self.config.request_timeout, stream=True)
                resp.raise_for_status()
                image_bytes = resp.content
                if self.config.convert_to_png:
                    image_bytes = self._save_as_png(image_bytes)
                filepath.write_bytes(image_bytes)
                logger.info(f"已下载: {filename}")
                self.state_mgr.add_downloaded_url(img_url)
                downloaded_this += 1
                self.total_downloaded += 1
                time.sleep(self.config.download_delay)
            except Exception as e:
                logger.error(f"下载失败 {img_url}: {e}")
                failed_this += 1
                self.total_failed += 1

            if self.image_result_callback:
                self.image_result_callback(self.total_downloaded, self.total_failed)

        return downloaded_this, failed_this

    def _save_current_state(self, page_url: Optional[str], last_url: Optional[str]) -> None:
        self.state_mgr.save_state(CrawlState(
            site_url=self.config.base_url,
            next_page_url=page_url,
            last_page_url=last_url
        ))
        self.state_mgr.save_downloaded_urls()

    def crawl_pages(self, page_limit: int, start_page: Optional[int] = None) -> Dict[str, Any]:
        if page_limit < 1:
            raise ValueError(f"页数必须 >= 1，当前为 {page_limit}")

        pages_processed = 0
        total_images = 0
        failed_images = 0
        page_url = self.resolve_start_page(start_page)
        last_page_url = None

        try:
            while page_url and pages_processed < page_limit:
                self._check_control()

                logger.info(f"正在爬取第 {pages_processed+1}/{page_limit} 页: {page_url}")
                soup = self.fetch_page_soup(page_url)

                img_urls = self.extract_image_urls(soup)
                self.total_found += len(img_urls)
                if self.total_found_callback:
                    self.total_found_callback(self.total_found)

                logger.info(f"第 {pages_processed+1} 页发现 {len(img_urls)} 张图片，累计发现 {self.total_found} 张")
                d, f = self.download_images(img_urls)
                total_images += d
                failed_images += f
                pages_processed += 1

                if self.progress_callback:
                    self.progress_callback(pages_processed, page_limit)

                last_page_url = page_url
                next_page_url = self.find_next_page_url(soup, page_url)
                page_url = next_page_url if next_page_url and next_page_url != page_url else None
                self._save_current_state(page_url, last_page_url)

        except InterruptedError:
            # 取消时保存已下载记录
            self._save_current_state(page_url, last_page_url)
            raise
        except Exception:
            self._save_current_state(page_url, last_page_url)
            raise

        self._save_current_state(page_url, last_page_url)
        return {
            'pages_downloaded': pages_processed,
            'total_images': total_images,
            'failed_images': failed_images,
            'last_page_url': last_page_url,
            'next_page_url': page_url,
        }


def format_time(seconds: float) -> str:
    """将秒数格式化为 HH:MM:SS"""
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"


def clear_screen() -> None:
    import subprocess
    import os
    subprocess.run('cls' if os.name == 'nt' else 'clear', shell=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='图片爬虫（按页下载）')
    parser.add_argument('pages', nargs='?', type=int, default=1, help='要下载的页数')
    parser.add_argument('--start-page', type=int, default=None, help='起始页')
    parser.add_argument('--url', type=str, default='https://mikagogo.com/pc-wallpaper', help='目标 URL')
    parser.add_argument('--delay', type=float, default=1.0, help='下载间隔（秒）')
    parser.add_argument('--no-convert', action='store_true', help='不转换为 PNG')
    args = parser.parse_args()

    if args.start_page is not None and args.start_page < 1:
        parser.error('起始页必须 >= 1')

    clear_screen()
    config = CrawlConfig(
        base_url=args.url.rstrip('/') + '/',
        download_delay=args.delay,
        convert_to_png=not args.no_convert
    )
    with ImageCrawler(config) as crawler:
        result = crawler.crawl_pages(args.pages, start_page=args.start_page)
        print(f"下载完成：共处理 {result['pages_downloaded']} 页，成功 {result['total_images']} 张，失败 {result['failed_images']} 张。")