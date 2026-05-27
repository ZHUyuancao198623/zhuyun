#!/usr/bin/env python3
"""
网易云音乐爬虫脚本

依赖安装: pip install requests

用法示例:
    python netease_music_scraper.py --search "周杰伦" --top 10
    python netease_music_scraper.py --search "晴天" --download --top 3
    python netease_music_scraper.py --playlist 3778678
    python netease_music_scraper.py --playlist 3778678 --download
    python netease_music_scraper.py --song 186016 --lyrics
    python netease_music_scraper.py --song 186016 --comments --pages 3
    python netease_music_scraper.py --song 186016 --download
    python netease_music_scraper.py --artist 6452 --top 20 --download

注意: 部分歌曲因版权限制无法下载，仅供个人学习使用，请尊重版权。
"""

import requests
import json
import os
import re
import time
import argparse
import sys
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

BASE_URL = "https://music.163.com"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
    "Referer": "https://music.163.com/",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}


class NeteaseMusicScraper:
    def __init__(self, cookie=None, output_dir="./music", max_retries=3, delay=1.0):
        self.session = requests.Session()
        self.session.headers.update(HEADERS)
        if cookie:
            for item in cookie.split(";"):
                item = item.strip()
                if "=" in item:
                    k, v = item.split("=", 1)
                    self.session.cookies.set(k.strip(), v.strip())
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.max_retries = max_retries
        self.delay = delay

    @staticmethod
    def _normalize_song(raw: dict) -> dict:
        return {
            "id": raw["id"],
            "name": raw["name"],
            "artists": "/".join(a["name"] for a in (raw.get("ar") or raw.get("artists") or [])),
            "album": (raw.get("al") or raw.get("album") or {}).get("name", ""),
            "album_pic": (raw.get("al") or raw.get("album") or {}).get("picUrl", ""),
            "duration": (raw.get("dt") or raw.get("duration") or 0) // 1000,
            "fee": raw.get("fee", 0),
        }

    def _get(self, url, params=None):
        for attempt in range(self.max_retries):
            try:
                resp = self.session.get(url, params=params, timeout=30)
                resp.raise_for_status()
                return resp.json()
            except Exception as e:
                if attempt == self.max_retries - 1:
                    print(f"  请求失败: {e}")
                    return {}

    # ── 搜索 ────────────────────────────────────────────

    def search(self, keyword: str, limit: int = 30, stype: int = 1) -> list:
        print(f"\n[搜索] {keyword} (数量={limit})")
        result = self._get(f"{BASE_URL}/api/search/get",
                           {"s": keyword, "type": stype, "limit": limit, "offset": 0})
        if not result or result.get("code") != 200:
            print(f"  搜索失败: {result.get('message', '')}")
            return []

        items = []
        if stype == 1:
            for s in result.get("result", {}).get("songs", []):
                items.append(self._normalize_song(s))
        elif stype == 100:
            for s in result.get("result", {}).get("artists", []):
                items.append({"id": s["id"], "name": s["name"],
                              "pic_url": s.get("picUrl", ""), "album_size": s.get("albumSize", 0)})
        elif stype == 1000:
            for s in result.get("result", {}).get("playlists", []):
                items.append({"id": s["id"], "name": s["name"],
                              "creator": s.get("creator", {}).get("nickname", ""),
                              "track_count": s.get("trackCount", 0),
                              "play_count": s.get("playCount", 0)})
        print(f"  找到 {len(items)} 条结果")
        return items

    # ── 歌曲详情 ────────────────────────────────────────

    def get_song_detail(self, song_ids: list) -> list:
        if isinstance(song_ids, int):
            song_ids = [song_ids]
        result = self._get(f"{BASE_URL}/api/song/detail", {"ids": json.dumps(song_ids)})
        return [self._normalize_song(s) for s in result.get("songs", [])]

    # ── 歌词 ────────────────────────────────────────────

    def get_lyrics(self, song_id: int) -> dict:
        result = self._get(f"{BASE_URL}/api/song/lyric", {"id": str(song_id), "lv": 1, "tv": 1})
        lrc = (result.get("lrc") or {}).get("lyric", "")
        tlrc = (result.get("tlyric") or {}).get("lyric", "")
        return {"lrc": lrc, "tlrc": tlrc}

    # ── 评论 ────────────────────────────────────────────

    def get_comments(self, song_id: int, limit: int = 20, offset: int = 0) -> dict:
        result = self._get(f"{BASE_URL}/api/v1/resource/comments/R_SO_4_{song_id}",
                           {"limit": limit, "offset": offset})
        data = result.get("data", {}) or {}
        comments = []
        for c in data.get("comments", []):
            u = c.get("user", {})
            comments.append({"user": u.get("nickname", ""), "user_id": u.get("userId", 0),
                             "content": c.get("content", ""),
                             "liked": c.get("likedCount", 0), "time": c.get("time", 0)})
        hot = [{"user": c.get("user", {}).get("nickname", ""),
                "content": c.get("content", ""),
                "liked": c.get("likedCount", 0)} for c in data.get("hotComments", [])]
        return {"comments": comments, "total": data.get("totalCount", 0), "hot": hot}

    def get_all_comments(self, song_id: int, pages: int = 5, per_page: int = 50) -> list:
        all_comments = []
        for p in range(pages):
            result = self.get_comments(song_id, limit=per_page, offset=p * per_page)
            all_comments.extend(result.get("comments", []))
            print(f"  第{p+1}页: {len(result.get('comments', []))} 条")
            time.sleep(self.delay)
        return all_comments

    # ── 歌单 ────────────────────────────────────────────

    def get_playlist(self, playlist_id: int) -> dict:
        result = self._get(f"{BASE_URL}/api/v6/playlist/detail", {"id": str(playlist_id)})
        pl = result.get("playlist", {}) or {}
        songs = [self._normalize_song(t) for t in pl.get("tracks", [])]
        return {"id": pl.get("id", playlist_id), "name": pl.get("name", ""),
                "description": pl.get("description", ""),
                "creator": pl.get("creator", {}).get("nickname", ""),
                "play_count": pl.get("playCount", 0),
                "track_count": len(songs), "songs": songs}

    # ── 歌手热门 ────────────────────────────────────────

    def get_artist_top_songs(self, artist_id: int, limit: int = 50) -> list:
        result = self._get(f"{BASE_URL}/api/artist/top/song", {"id": str(artist_id)})
        return [self._normalize_song(s) for s in (result.get("songs", []) or [])[:limit]]

    # ── 排行榜 ──────────────────────────────────────────

    def get_toplist(self) -> list:
        result = self._get(f"{BASE_URL}/api/toplist")
        return [{"id": t["id"], "name": t["name"],
                 "description": t.get("description", ""),
                 "update_frequency": t.get("updateFrequency", "")}
                for t in (result.get("list", []) or [])]

    # ── 下载歌曲 ────────────────────────────────────────

    def download_song(self, song_id: int, title: str = None) -> bool:
        """使用网易云公开音频链接下载"""
        if title is None:
            details = self.get_song_detail([song_id])
            title = f"{details[0]['artists']} - {details[0]['name']}" if details else str(song_id)

        print(f"\n[下载] {title}")

        # 网易云公开重定向链接
        audio_url = f"https://music.163.com/song/media/outer/url?id={song_id}.mp3"
        safe_title = re.sub(r'[\\/:*?"<>|]', "_", title)
        # Windows 路径最长 260 字符，文件名截断
        if len(safe_title) > 80:
            safe_title = safe_title[:77] + "..."
        filepath = self.output_dir / f"{safe_title}.mp3"

        if filepath.exists():
            print(f"  [SKIP] 已存在")
            return True

        try:
            resp = self.session.get(audio_url, timeout=30, allow_redirects=True, stream=True)
            resp.raise_for_status()

            # 检查是否重定向到了 404 页面
            ct = resp.headers.get("Content-Type", "")
            if "html" in ct or "text" in ct:
                print(f"  [FAIL] 歌曲版权受限，无法下载")
                return False

            total_size = int(resp.headers.get("Content-Length", 0))
            size_mb = total_size / 1024 / 1024 if total_size else 0
            print(f"  下载中... ({size_mb:.1f}MB)" if size_mb else "  下载中...")

            with open(filepath, "wb") as f:
                downloaded = 0
                for chunk in resp.iter_content(chunk_size=8192):
                    f.write(chunk)
                    downloaded += len(chunk)

            if downloaded < 1024:  # 小于1KB肯定是无效文件
                filepath.unlink()
                print(f"  [FAIL] 无效文件")
                return False

            print(f"  [OK] {filepath.name} ({downloaded/1024/1024:.1f}MB)")
            return True
        except Exception as e:
            print(f"  [FAIL] {e}")
            if filepath.exists():
                filepath.unlink()
            return False


# ── 工具函数 ───────────────────────────────────────────────
def fmt_time(seconds: int) -> str:
    m, s = divmod(seconds, 60)
    return f"{m}:{s:02d}"


def print_songs_table(songs: list, start: int = 1):
    print(f"\n{'#':<5} {'ID':<10} {'歌曲':<25} {'歌手':<20} {'专辑':<20} {'时长':<8}")
    print("-" * 90)
    for i, s in enumerate(songs, start):
        print(f"{i:<5} {s['id']:<10} {s['name'][:24]:<25} {s['artists'][:19]:<20} "
              f"{s.get('album', '')[:19]:<20} {fmt_time(s.get('duration', 0)):<8}")


# ── 命令行入口 ─────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(
        description="网易云音乐爬虫",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  %(prog)s --search "周杰伦" --top 10
  %(prog)s --search "晴天" --download --top 3
  %(prog)s --playlist 3778678
  %(prog)s --playlist 3778678 --download
  %(prog)s --song 186016 --lyrics
  %(prog)s --song 186016 --comments --pages 3
  %(prog)s --song 186016 --download
  %(prog)s --artist 6452 --top 20 --download
  %(prog)s --toplist
        """,
    )

    parser.add_argument("--search", "-s", help="搜索关键词")
    parser.add_argument("--type", "-t", type=int, default=1,
                        help="搜索类型: 1=单曲 10=专辑 100=歌手 1000=歌单")
    parser.add_argument("--song", type=int, help="歌曲ID")
    parser.add_argument("--playlist", "-p", type=int, help="歌单ID")
    parser.add_argument("--artist", "-a", type=int, help="歌手ID")
    parser.add_argument("--toplist", action="store_true", help="列出排行榜")
    parser.add_argument("--lyrics", "-l", action="store_true", help="获取歌词")
    parser.add_argument("--comments", "-c", action="store_true", help="获取评论")
    parser.add_argument("--download", "-d", action="store_true", help="下载歌曲")
    parser.add_argument("--top", "-n", type=int, default=20, help="搜索数量 (默认20)")
    parser.add_argument("--pages", type=int, default=5, help="评论页数 (默认5)")
    parser.add_argument("--output", "-o", default="./music", help="下载目录 (默认 ./music)")
    parser.add_argument("--cookie", help="Cookie（可选，部分歌曲需要）")
    parser.add_argument("--cookie-file", help="从文件读取Cookie")
    parser.add_argument("--threads", type=int, default=3, help="并发下载数 (默认3)")
    parser.add_argument("--delay", type=float, default=1.0, help="请求间隔秒数 (默认1.0)")

    args = parser.parse_args()

    if not any([args.search, args.song, args.playlist, args.artist, args.toplist]):
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

    scraper = NeteaseMusicScraper(cookie=cookie, output_dir=args.output, delay=args.delay)

    # ── 排行榜 ──────────────────────────────────────────
    if args.toplist:
        lists = scraper.get_toplist()
        print(f"\n[排行榜] 共 {len(lists)} 个:")
        print(f"{'ID':<12} {'名称':<20} {'描述':<30} {'更新频率':<10}")
        print("-" * 75)
        for t in lists:
            desc = (t.get('description') or "")[:29]
            freq = (t.get('update_frequency') or "")[:9]
            print(f"{t['id']:<12} {t['name'][:19]:<20} {desc:<30} {freq:<10}")
        return

    # ── 搜索 ────────────────────────────────────────────
    if args.search:
        songs = scraper.search(args.search, limit=args.top, stype=args.type)

        if args.type == 1:
            print_songs_table(songs)
        elif args.type == 100:
            for s in songs:
                print(f"  ID: {s['id']:<10} 歌手: {s['name']}")
        elif args.type == 1000:
            for s in songs:
                print(f"  ID: {s['id']:<12} {s['name'][:30]:<32} {s['track_count']}首  播放: {s['play_count']}")

        if args.download and args.type == 1 and songs:
            total = 0
            for s in songs:
                if scraper.download_song(s["id"], f"{s['artists']} - {s['name']}"):
                    total += 1
                time.sleep(args.delay)
            print(f"\n下载完成: {total}/{len(songs)} 首")
        return

    # ── 歌单 ────────────────────────────────────────────
    if args.playlist:
        pl = scraper.get_playlist(args.playlist)
        print(f"\n[歌单] {pl['name']}")
        print(f"  创建者: {pl['creator']}  播放: {pl['play_count']}  歌曲: {pl['track_count']}")
        if args.download:
            print(f"  共 {len(pl['songs'])} 首歌，开始下载...")
            total = 0
            with ThreadPoolExecutor(max_workers=args.threads) as executor:
                futures = {
                    executor.submit(scraper.download_song, s["id"],
                                    f"{s['artists']} - {s['name']}"): s
                    for s in pl["songs"]
                }
                for i, future in enumerate(as_completed(futures), 1):
                    ok = future.result()
                    total += int(ok)
                    s = futures[future]
                    status = "[OK]" if ok else "[FAIL]"
                    print(f"  [{i}/{len(pl['songs'])}] {status} {s['artists']} - {s['name'][:30]}")
            print(f"\n下载完成: {total}/{len(pl['songs'])} 首")
        else:
            print_songs_table(pl["songs"])
        return

    # ── 歌手 ────────────────────────────────────────────
    if args.artist:
        songs = scraper.get_artist_top_songs(args.artist, limit=args.top)
        print(f"\n[歌手] ID={args.artist} 热门歌曲:")
        print_songs_table(songs)
        if args.download and songs:
            total = 0
            for s in songs:
                if scraper.download_song(s["id"], f"{s['artists']} - {s['name']}"):
                    total += 1
                time.sleep(args.delay)
            print(f"\n下载完成: {total}/{len(songs)} 首")
        return

    # ── 单曲 ────────────────────────────────────────────
    if args.song:
        if not any([args.lyrics, args.comments, args.download]):
            details = scraper.get_song_detail([args.song])
            if details:
                d = details[0]
                print(f"\n[歌曲] {d['artists']} - {d['name']}")
                print(f"  专辑: {d['album']}  时长: {fmt_time(d['duration'])}")
                print(f"  封面: {d['album_pic']}")

        if args.lyrics:
            lyrics = scraper.get_lyrics(args.song)
            if lyrics["lrc"]:
                print(f"\n[歌词]\n{lyrics['lrc']}")
            if lyrics["tlrc"]:
                print(f"\n[翻译]\n{lyrics['tlrc']}")
            if not lyrics["lrc"]:
                print("  未找到歌词")

        if args.comments:
            comments = scraper.get_all_comments(args.song, pages=args.pages)
            print(f"\n[评论] 共 {len(comments)} 条:")
            for i, c in enumerate(comments, 1):
                content = c['content'].replace('\n', ' ')
                print(f"  {i}. [{c['user']}] {content[:100]}")
                if len(content) > 100:
                    print(f"     ...")

        if args.download:
            scraper.download_song(args.song)
        return


if __name__ == "__main__":
    main()
