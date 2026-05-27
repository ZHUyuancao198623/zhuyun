#!/usr/bin/env python3
"""
艺图语 (yituyu.com) 图片爬虫脚本

用法示例:
    python yituyu_scraper.py --url https://www.yituyu.com/gallery/14290/
    python yituyu_scraper.py --daily --pages 5
    python yituyu_scraper.py --tag 12 --pages 3
    python yituyu_scraper.py --url https://www.yituyu.com/gallery/14290/ --cookie "your_cookie" --original
    python yituyu_scraper.py --daily --pages 3 --output ./images --threads 4
"""

import requests
from bs4 import BeautifulSoup
import re
import os
import time
import argparse
import sys
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urljoin

BASE_URL = "https://www.yituyu.com"
IMG_BASE = "https://img.yituyu.com"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
    "Referer": "https://www.yituyu.com/",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}


class YituyuScraper:
    def __init__(self, cookie=None, output_dir="./images", max_retries=3, delay=1.0):
        self.session = requests.Session()
        self.session.headers.update(HEADERS)
        if cookie:
            self.session.headers["Cookie"] = cookie
        self.output_dir = Path(output_dir)
        self.max_retries = max_retries
        self.delay = delay

    def _request(self, url, method="GET", **kwargs):
        """带重试的请求"""
        for attempt in range(self.max_retries):
            try:
                if method == "POST":
                    resp = self.session.post(url, **kwargs)
                else:
                    resp = self.session.get(url, timeout=30, **kwargs)
                resp.raise_for_status()
                return resp
            except requests.RequestException as e:
                if attempt < self.max_retries - 1:
                    time.sleep(self.delay * (attempt + 1))
                else:
                    raise e

    # ---------- 获取作品ID ----------

    def get_gallery_ids_from_page(self, url):
        """从列表页提取作品ID"""
        resp = self._request(url)
        soup = BeautifulSoup(resp.text, "html.parser")
        ids = set()
        for a in soup.select("a[href]"):
            m = re.search(r"/gallery/(\d+)/?", a["href"])
            if m:
                ids.add(int(m.group(1)))
        return sorted(ids)

    def get_gallery_ids_from_daily(self, pages=1):
        """从每日更新页获取作品ID"""
        all_ids = set()
        for p in range(1, pages + 1):
            if p == 1:
                url = f"{BASE_URL}/gallery/"
            else:
                url = f"{BASE_URL}/gallery/p{p}/"
            ids = self.get_gallery_ids_from_page(url)
            all_ids.update(ids)
            print(f"  每日更新 第{p}页: 获取到 {len(ids)} 个作品ID")
            time.sleep(self.delay)
        return sorted(all_ids)

    def get_gallery_ids_from_tag(self, tag_id, pages=1):
        """从标签页获取作品ID"""
        all_ids = set()
        for p in range(1, pages + 1):
            if p == 1:
                url = f"{BASE_URL}/tag/{tag_id}/"
            else:
                url = f"{BASE_URL}/tag/{tag_id}/p{p}/"
            ids = self.get_gallery_ids_from_page(url)
            all_ids.update(ids)
            print(f"  标签 {tag_id} 第{p}页: 获取到 {len(ids)} 个作品ID")
            time.sleep(self.delay)
        return sorted(all_ids)

    def get_gallery_ids_from_home(self):
        """从首页获取作品ID"""
        ids = self.get_gallery_ids_from_page(BASE_URL + "/")
        print(f"  首页: 获取到 {len(ids)} 个作品ID")
        return ids

    # ---------- 获取图片URL ----------

    def get_image_urls(self, gallery_id):
        """通过AJAX接口获取作品的所有图片URL（需要登录才能获取完整列表）"""
        url = f"{BASE_URL}/ajax_gallery/"
        resp = self._request(url, method="POST", data={"id": str(gallery_id)})
        data = resp.json()
        if data.get("status") != 200:
            print(f"  [错误] 作品 {gallery_id}: 接口返回异常")
            return [], None

        info = data.get("data", {})
        title = info.get("title", str(gallery_id))

        if "imgs" in info and info["imgs"]:
            return info["imgs"], title
        else:
            # 未登录，从HTML页面提取预览图
            return self._get_preview_urls_from_html(gallery_id), title

    def _get_preview_urls_from_html(self, gallery_id):
        """未登录时从HTML提取预览图片URL"""
        url = f"{BASE_URL}/gallery/{gallery_id}/"
        try:
            resp = self._request(url)
            # 从 data-img 属性提取
            urls = re.findall(r'data-img="([^"]+)"', resp.text)
            # 也尝试匹配 data-src
            if not urls:
                urls = re.findall(r'data-src="([^"]*img\.yituyu\.com[^"]*\.(?:jpg|jpeg|png))"', resp.text)
            return urls
        except Exception:
            return []

    # ---------- 下载 ----------

    def download_image(self, img_url, save_dir, filename=None):
        """下载单张图片"""
        save_dir = Path(save_dir)
        save_dir.mkdir(parents=True, exist_ok=True)

        if filename is None:
            filename = img_url.split("/")[-1].split("?")[0]
        filepath = save_dir / filename

        if filepath.exists():
            return True, f"已存在: {filename}"

        for attempt in range(self.max_retries):
            try:
                resp = self.session.get(img_url, timeout=60, stream=True)
                resp.raise_for_status()
                with open(filepath, "wb") as f:
                    for chunk in resp.iter_content(chunk_size=8192):
                        f.write(chunk)
                return True, filename
            except requests.RequestException as e:
                if attempt < self.max_retries - 1:
                    time.sleep(self.delay * (attempt + 1))
                else:
                    return False, f"下载失败 [{filename}]: {e}"

    def download_gallery(self, gallery_id, title=None, threads=4):
        """下载单个作品的所有图片"""
        print(f"\n[作品 {gallery_id}] 获取图片列表...")
        img_urls, fetched_title = self.get_image_urls(gallery_id)
        if title is None:
            title = fetched_title

        if not img_urls:
            print(f"  [作品 {gallery_id}] 未获取到图片（可能需要登录），跳过")
            return 0

        # 清理标题作为文件夹名
        safe_title = re.sub(r'[\\/:*?"<>|]', '_', title)
        save_dir = self.output_dir / f"{gallery_id}_{safe_title}"

        print(f"  [{title}] 共 {len(img_urls)} 张图片, 保存到: {save_dir}")

        success_count = 0
        with ThreadPoolExecutor(max_workers=threads) as executor:
            futures = {}
            for i, img_url in enumerate(img_urls):
                # 生成序号文件名
                ext = Path(img_url.split("?")[0]).suffix or ".jpg"
                filename = f"{i+1:03d}{ext}"
                future = executor.submit(self.download_image, img_url, save_dir, filename)
                futures[future] = (i + 1, filename)

            for future in as_completed(futures):
                idx, fname = futures[future]
                ok, msg = future.result()
                if ok:
                    success_count += 1
                print(f"    [{idx}/{len(img_urls)}] {msg}")

        print(f"  [完成] {title}: {success_count}/{len(img_urls)} 张")
        return success_count

    def download_original_zip(self, gallery_id, title=None):
        """尝试下载原图打包（需要VIP或特殊权限）"""
        url = f"{BASE_URL}/ajax_zip/"
        if title is None:
            _, title = self.get_image_urls(gallery_id)
        safe_title = re.sub(r'[\\/:*?"<>|]', '_', title)
        save_dir = self.output_dir / f"{gallery_id}_{safe_title}"
        save_dir.mkdir(parents=True, exist_ok=True)

        try:
            resp = self._request(url, method="POST", data={"id": str(gallery_id)})
            data = resp.json()
            if data.get("status") == 200 and "zip" in data.get("data", {}):
                zip_url = data["data"]["zip"]
                filepath = save_dir / f"{gallery_id}_{safe_title}.zip"
                print(f"  下载原图打包: {zip_url}")
                self.download_image(zip_url, save_dir, f"{gallery_id}_{safe_title}.zip")
                return True
            else:
                print(f"  [原图打包] 需要VIP权限或作品不支持打包下载")
                return False
        except Exception as e:
            print(f"  [原图打包] 请求失败: {e}")
            return False


def main():
    parser = argparse.ArgumentParser(
        description="艺图语 (yituyu.com) 图片爬虫",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  %(prog)s --url https://www.yituyu.com/gallery/14290/
  %(prog)s --daily --pages 5
  %(prog)s --tag 12 --pages 3
  %(prog)s --daily --pages 3 --cookie "PHPSESSID=xxx" --original
  %(prog)s --home --output ./yituyu_images --threads 8
        """,
    )
    parser.add_argument("--url", help="单个作品页面URL")
    parser.add_argument("--daily", action="store_true", help="爬取每日更新列表")
    parser.add_argument("--tag", type=int, help="爬取指定标签ID（如 12=古风, 13=小清新, 424=JK）")
    parser.add_argument("--home", action="store_true", help="爬取首页推荐作品")
    parser.add_argument("--pages", type=int, default=1, help="爬取页数（用于--daily和--tag，默认1）")
    parser.add_argument("--output", "-o", default="./images", help="图片保存目录（默认 ./images）")
    parser.add_argument("--cookie", help="登录后的Cookie字符串（从浏览器复制）")
    parser.add_argument("--cookie-file", help="从文件读取Cookie")
    parser.add_argument("--original", action="store_true", help="尝试下载原图打包（需VIP）")
    parser.add_argument("--threads", "-t", type=int, default=4, help="并发下载线程数（默认4）")
    parser.add_argument("--delay", type=float, default=1.0, help="请求间隔秒数（默认1.0）")
    args = parser.parse_args()

    if not any([args.url, args.daily, args.tag, args.home]):
        parser.print_help()
        sys.exit(1)

    cookie = args.cookie
    if args.cookie_file:
        try:
            with open(args.cookie_file, "r", encoding="utf-8") as f:
                cookie = f.read().strip()
        except FileNotFoundError:
            print(f"Cookie文件不存在: {args.cookie_file}")
            sys.exit(1)

    scraper = YituyuScraper(
        cookie=cookie,
        output_dir=args.output,
        delay=args.delay,
    )

    # --- 单作品模式 ---
    if args.url:
        m = re.search(r"/gallery/(\d+)", args.url)
        if not m:
            print(f"无法解析作品URL: {args.url}")
            sys.exit(1)
        gallery_id = int(m.group(1))
        scraper.download_gallery(gallery_id, threads=args.threads)
        if args.original:
            scraper.download_original_zip(gallery_id)
        return

    # --- 列表模式 ---
    all_ids = []
    if args.home:
        all_ids.extend(scraper.get_gallery_ids_from_home())
    if args.daily:
        all_ids.extend(scraper.get_gallery_ids_from_daily(pages=args.pages))
    if args.tag:
        all_ids.extend(scraper.get_gallery_ids_from_tag(args.tag, pages=args.pages))

    # 去重保持顺序
    seen = set()
    gallery_ids = []
    for gid in all_ids:
        if gid not in seen:
            seen.add(gid)
            gallery_ids.append(gid)

    if not gallery_ids:
        print("未获取到任何作品ID")
        return

    print(f"\n共获取到 {len(gallery_ids)} 个作品，开始下载...")
    total = 0
    for gid in gallery_ids:
        total += scraper.download_gallery(gid, threads=args.threads)
        time.sleep(args.delay)

    print(f"\n全部完成! 共下载 {total} 张图片，保存到: {args.output}")


if __name__ == "__main__":
    main()
