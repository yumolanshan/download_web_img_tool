import argparse
import json
import os
import re
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Set
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup


@dataclass
class CrawlState:
    site_url: str
    last_page_url: Optional[str] = None
    next_page_url: Optional[str] = None


class ImageCrawler:
    DEFAULT_HEADERS = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
    }
    IMAGE_EXT_RE = re.compile(r'\.(?:jpg|jpeg|png|webp)(?:\?.*)?$', re.I)
    THUMBNAIL_SUFFIX_RE = re.compile(
        r'(?i)(?:[-_](?:pcthumbs|thumbs?|arthumbs|bannerthumbs|small|mini|large))(?=(?:\?.*)?$)'
    )
    NEXT_PAGE_TEXT = ('下一页', 'next', '›', '»')

    def __init__(
        self,
        base_url: str,
        img_dir: Optional[Path] = None,
        state_path: Optional[Path] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> None:
        self.base_url = base_url.rstrip('/') + '/'
        self.img_dir = Path(img_dir or Path(__file__).parent / 'img')
        self.img_dir.mkdir(parents=True, exist_ok=True)
        self.state_path = Path(state_path or Path(__file__).parent / 'crawl_state.json')
        self.headers = headers or self.DEFAULT_HEADERS.copy()
        self.session = requests.Session()
        self.downloaded_urls: Set[str] = set()
        self.state = self.load_state()

    def load_state(self) -> Optional[CrawlState]:
        if not self.state_path.exists():
            return None

        try:
            raw_data = json.loads(self.state_path.read_text(encoding='utf-8'))
        except (json.JSONDecodeError, OSError):
            return None

        return CrawlState(
            site_url=raw_data.get('site_url', ''),
            last_page_url=raw_data.get('last_page_url'),
            next_page_url=raw_data.get('next_page_url'),
        )

    def save_state(self, state: CrawlState) -> None:
        self.state_path.write_text(
            json.dumps(
                {
                    'site_url': state.site_url,
                    'last_page_url': state.last_page_url,
                    'next_page_url': state.next_page_url,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding='utf-8',
        )

    def build_page_url(self, page_number: int) -> str:
        return urljoin(self.base_url, f'page/{page_number}/')

    def resolve_start_page(self, start_page: Optional[int] = None) -> str:
        if start_page is not None:
            if start_page < 1:
                raise ValueError(f'start_page must be >= 1, got {start_page}')
            if start_page == 1:
                return self.base_url
            return self.build_page_url(start_page)
        if self.state and self.state.site_url == self.base_url and self.state.next_page_url:
            return self.state.next_page_url
        return self.base_url

    def fetch_page_soup(self, url: str) -> BeautifulSoup:
        response = self.session.get(url, headers=self.headers, timeout=10)
        response.encoding = 'utf-8'
        response.raise_for_status()
        try:
            return BeautifulSoup(response.text, 'lxml')
        except Exception:
            return BeautifulSoup(response.text, 'html.parser')

    def normalize_image_url(self, src: str) -> str:
        src = src.strip()
        src = self.THUMBNAIL_SUFFIX_RE.sub('', src)
        if src.endswith('?.'):
            src = src[:-2]
        return src

    def is_image_url(self, url: str) -> bool:
        return bool(self.IMAGE_EXT_RE.search(url))

    def find_direct_image_link(self, img: Any, base_url: str) -> Optional[str]:
        if img.has_attr('data-original') and self.is_image_url(img['data-original']):
            return self.normalize_image_url(urljoin(base_url, img['data-original']))

        anchor = img.find_parent('a', href=True)
        if anchor and self.is_image_url(anchor['href']):
            return self.normalize_image_url(urljoin(base_url, anchor['href']))

        for ancestor in img.parents:
            if ancestor.name == 'a' and ancestor.has_attr('href') and self.is_image_url(ancestor['href']):
                return self.normalize_image_url(urljoin(base_url, ancestor['href']))

        sibling = img.find_next_sibling('a', href=True)
        if sibling and self.is_image_url(sibling['href']):
            return self.normalize_image_url(urljoin(base_url, sibling['href']))

        return None

    def extract_image_urls(self, soup: BeautifulSoup, base_url: str) -> List[str]:
        urls: List[str] = []
        for img in soup.find_all('img'):
            src = img.get('data-original') or img.get('data-src') or img.get('src')
            if not src:
                continue

            full_src = 'https:' + src if src.startswith('//') else urljoin(base_url, src)
            direct_image_url = self.find_direct_image_link(img, base_url)
            candidate_url = direct_image_url or self.normalize_image_url(full_src)

            if not self.is_image_url(candidate_url):
                continue
            if any(blocked in candidate_url.lower() for blocked in ('logo', 'avatar')):
                continue

            urls.append(candidate_url)

        return list(dict.fromkeys(urls))

    def find_next_page_url(self, soup: BeautifulSoup, current_url: str) -> Optional[str]:
        for anchor in soup.find_all('a', href=True):
            href = anchor['href']
            label = anchor.get_text(strip=True).lower()
            if any(keyword in label for keyword in self.NEXT_PAGE_TEXT):
                return urljoin(current_url, href)

        for anchor in soup.find_all('a', href=True):
            href = anchor['href']
            if re.search(r'/page/\d+/?', href):
                return urljoin(current_url, href)

        return None

    def extract_filename(self, img_url: str, index: int) -> str:
        filename = img_url.split('/')[-1].split('?')[0]
        if not filename or not filename.lower().endswith(('.jpg', '.jpeg', '.png', '.webp')):
            filename = f'wallpaper_{index + 1}.jpg'
        return filename

    def download_images(self, img_urls: List[str], limit: int) -> int:
        downloaded_count = 0
        for img_url in img_urls:
            if downloaded_count >= limit:
                break
            if img_url in self.downloaded_urls:
                continue

            filename = self.extract_filename(img_url, downloaded_count)
            path = self.img_dir / filename
            if path.exists():
                suffix = path.suffix or '.jpg'
                path = self.img_dir / f'wallpaper_{downloaded_count + 1}{suffix}'

            try:
                response = self.session.get(img_url, headers=self.headers, timeout=10)
                response.raise_for_status()
                path.write_bytes(response.content)
                print(f'已下载：{path.name}')
                self.downloaded_urls.add(img_url)
                downloaded_count += 1
            except Exception as error:
                print(f'下载出错：{img_url} -> {error}')
            time.sleep(0.5)

        return downloaded_count

    def crawl_pages(self, target_count: int, start_page: Optional[int] = None) -> Dict[str, Optional[Any]]:
        if target_count < 1:
            raise ValueError(f'target_count must be >= 1, got {target_count}')
        if start_page is not None and start_page < 1:
            raise ValueError(f'start_page must be >= 1, got {start_page}')
        downloaded = 0
        page_url = self.resolve_start_page(start_page)
        last_page_url: Optional[str] = None

        while page_url and downloaded < target_count:
            print(f'正在爬取页面：{page_url}')
            soup = self.fetch_page_soup(page_url)
            img_urls = self.extract_image_urls(soup, page_url)
            downloaded += self.download_images(img_urls, target_count - downloaded)
            last_page_url = page_url
            next_page_url = self.find_next_page_url(soup, page_url)
            if not next_page_url or next_page_url == page_url:
                page_url = None
            else:
                page_url = next_page_url

        self.save_state(CrawlState(site_url=self.base_url, last_page_url=last_page_url, next_page_url=page_url))
        return {
            'downloaded': downloaded,
            'last_page_url': last_page_url,
            'next_page_url': page_url,
        }

    def parse_page_number(self, page_url: str) -> Optional[int]:
        match = re.search(r'/page/(\d+)/?', page_url)
        if match:
            return int(match.group(1))
        return None


def clear_screen() -> None:
    subprocess.run('cls' if os.name == 'nt' else 'clear', shell=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='图片爬虫，优先下载原图链接。')
    parser.add_argument('count', nargs='?', type=int, default=20, help='要下载的图片数量')
    parser.add_argument('--start-page', type=int, default=None, help='从第几页开始爬取，默认继续上次记录或第一页')
    args = parser.parse_args()

    if args.start_page is not None and args.start_page < 1:
        parser.error('start-page must be >= 1')

    clear_screen()
    crawler = ImageCrawler(base_url='https://www.bizhihui.com/')
    result = crawler.crawl_pages(args.count, start_page=args.start_page)
    print(f"本次下载完成，共下载 {result['downloaded']} 张图片。")
