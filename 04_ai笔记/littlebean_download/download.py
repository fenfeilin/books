#!/usr/bin/env python3
"""
Littlebean 资源批量下载脚本

用法:
    python3 download.py                 # 用同目录的 config.json
    python3 download.py my_config.json  # 指定配置文件
    python3 download.py --dry-run       # 只分析不下载

配置见 config.json：填多个 book 链接 + 输出目录 + 请求头(X-HB-Token)。
脚本会自动从链接里提取 xbe_book_id，查书名、拉音频/视频列表并下载。
只下载公开接口返回的资源，不绕过登录/付费。
"""

import json
import os
import re
import sys
import urllib.parse
import urllib.request

BASE = "https://littlebean.baobaobooks.com"
NAME_API = BASE + "/xiaobienapi/bookshelf/v1/v3_3_0/books/{book_id}"
AUDIO_APIS = [
    BASE + "/xiaobienapi/bookshelf/v1/v3_3_0/user/audios?book_id={book_id}",
    BASE + "/xiaobienapi/bookshelf/v1/v2_1_4/{book_id}/audios",
    BASE + "/xiaobienapi/bookshelf/v1/xiaobien/books/{book_id}",
]

INVALID = re.compile(r'[\\/:*?"<>|]')


def sanitize(name, fallback):
    name = (name or "").strip()
    name = INVALID.sub("_", name)
    return name or fallback


def extract_book_id(url):
    """从 url 里取 xbe_book_id。"""
    q = urllib.parse.urlparse(url).query
    params = urllib.parse.parse_qs(q)
    if "xbe_book_id" in params:
        return params["xbe_book_id"][0]
    m = re.search(r"xbe_book_id[=/](\w+)", url)
    return m.group(1) if m else None


def http_get(url, headers, wechat_url=None):
    h = dict(headers)
    if wechat_url:
        h["Wechat-Url"] = wechat_url
    req = urllib.request.Request(url, headers=h)
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read()


def get_json(url, headers, wechat_url=None):
    try:
        return json.loads(http_get(url, headers, wechat_url).decode("utf-8"))
    except Exception as e:
        print(f"    接口失败 {url}\n      {e}")
        return None


def walk(obj, key):
    """递归找出所有指定 key 的值。"""
    found = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k == key and isinstance(v, str):
                found.append(v)
            else:
                found.extend(walk(v, key))
    elif isinstance(obj, list):
        for item in obj:
            found.extend(walk(item, key))
    return found


def collect_resources(data):
    """从音频列表 JSON 里收集 (resource_url, name) 列表，按出现顺序去重。"""
    items, seen = [], set()

    def visit(obj):
        if isinstance(obj, dict):
            url = obj.get("resource_url")
            if isinstance(url, str) and url.startswith("http") and url not in seen:
                seen.add(url)
                name = obj.get("resource_name") or ""
                t1 = obj.get("first_type_name") or ""
                t2 = obj.get("sec_type_name") or ""
                items.append((url, name, f"{t1} {t2}".strip()))
            for v in obj.values():
                visit(v)
        elif isinstance(obj, list):
            for v in obj:
                visit(v)

    visit(data)
    return items


def download_file(url, path, overwrite=False):
    if os.path.exists(path) and os.path.getsize(path) > 0 and not overwrite:
        print(f"    跳过(已存在): {os.path.basename(path)}")
        return "skip"
    tmp = path + ".part"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=120) as r, open(tmp, "wb") as f:
            while True:
                chunk = r.read(1 << 16)
                if not chunk:
                    break
                f.write(chunk)
        os.replace(tmp, path)
        print(f"    ✓ {os.path.basename(path)}")
        return "ok"
    except Exception as e:
        if os.path.exists(tmp):
            os.remove(tmp)
        print(f"    ✗ 下载失败: {url}\n      {e}")
        return "fail"


def fetch_audio_list(book_id, headers, wechat_url):
    for api in AUDIO_APIS:
        data = get_json(api.format(book_id=book_id), headers, wechat_url)
        if data:
            res = collect_resources(data)
            if res:
                return res
    return []


def fetch_book_name(book_id, headers, wechat_url):
    data = get_json(NAME_API.format(book_id=book_id), headers, wechat_url)
    if not data:
        return None
    for key in ("book_name", "name", "title"):
        vals = walk(data, key)
        if vals:
            return vals[0]
    return None


def ext_for(url, type_label):
    m = re.search(r"\.(mp3|mp4|m4a|aac|wav)(\?|$)", url, re.I)
    if m:
        return "." + m.group(1).lower()
    return ".mp4" if "video" in (type_label or "").lower() else ".mp3"


def is_video(url, type_label):
    return ext_for(url, type_label) == ".mp4"


def process_book(idx, book, cfg, dry_run):
    url = book["url"]
    book_id = book.get("xbe_book_id") or extract_book_id(url)
    if not book_id:
        print(f"[{idx}] 无法从链接提取 xbe_book_id: {url}")
        return

    headers = cfg["headers"]
    print(f"\n[{idx}] book_id={book_id}")

    name = fetch_book_name(book_id, headers, url)
    folder_name = sanitize(f"{idx} - {name}" if name else f"{idx} - book_{book_id}",
                           f"{idx} - book_{book_id}")
    print(f"    书名: {name or '(未取到)'}")

    resources = fetch_audio_list(book_id, headers, url)
    audios = [r for r in resources if not is_video(r[0], r[2])]
    videos = [r for r in resources if is_video(r[0], r[2])]
    print(f"    资源: MP3={len(audios)}  MP4={len(videos)}")

    if dry_run:
        return

    want_audio = cfg["download"].get("audio", True)
    want_video = cfg["download"].get("video", True)
    overwrite = cfg["download"].get("overwrite", False)

    target = [r for r in resources
              if (want_audio and not is_video(r[0], r[2]))
              or (want_video and is_video(r[0], r[2]))]
    if not target:
        print("    没有需要下载的资源。")
        return

    out = os.path.join(cfg["output_dir"], folder_name)
    os.makedirs(out, exist_ok=True)
    for n, (res_url, res_name, type_label) in enumerate(target, 1):
        base = sanitize(f"{n:02d} - {res_name} - {type_label}".strip(" -"),
                        f"{n:02d}")
        path = os.path.join(out, base + ext_for(res_url, type_label))
        download_file(res_url, path, overwrite)


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    dry_run = "--dry-run" in sys.argv
    config_path = args[0] if args else os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "config.json")

    with open(config_path, encoding="utf-8") as f:
        cfg = json.load(f)

    cfg.setdefault("headers", {})
    cfg.setdefault("download", {})
    os.makedirs(cfg["output_dir"], exist_ok=True)

    print(f"配置: {config_path}")
    print(f"输出: {cfg['output_dir']}")
    print(f"模式: {'仅分析(dry-run)' if dry_run else '分析并下载'}")

    for idx, book in enumerate(cfg.get("books", []), 1):
        try:
            process_book(idx, book, cfg, dry_run)
        except Exception as e:
            print(f"[{idx}] 出错: {e}")

    print("\n完成。")


if __name__ == "__main__":
    main()
