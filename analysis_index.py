'''
 # analysis_index.py
 # 组件：负责从网站获取并解析小说信息、章节目录和章节内容
 # 版权所有：2025 Breeze-mi
 # 日期：2025/09/28
'''
import re
import time
import json
from pathlib import Path
from urllib.parse import urljoin, urlparse

# 预编译常用正则，降低重复编译开销
_RE_NUM_HTML_TAIL = re.compile(r'(\d+)\.html$', re.IGNORECASE)
_RE_CHAPTER_CONTAINER_HINT = re.compile(r'全部章节|全部章|全部目录', re.IGNORECASE)
_RE_ANCHOR_IN_UL = re.compile(r'<a\s+[^>]*href="(\d+\.html)"[^>]*>([^<]+)</a>', re.IGNORECASE)
_RE_TITLE_CHAPNUM = re.compile(r'第\s*([0-9０-９零〇一二三四五六七八九十百千万]+)\s*[章掌回集卷]', re.IGNORECASE)
_RE_NAV_PATH = re.compile(r'/sort/|/author/|/fullbook/|/mybook|/cover/|/index|/class\\d+-|/quanben|/top|/dll|/user/', re.IGNORECASE)
# 分页页匹配（常见于目录分页，如 index_2.html / list_2.html）
_RE_PAGINATION = re.compile(r'(?:^|/)(?:index|list)_(\d+)\.html$', re.IGNORECASE)

try:
    import requests
    from bs4 import BeautifulSoup, Tag
except Exception as e:
    # 在使用组件前请确保安装 requests 和 beautifulsoup4
    raise RuntimeError("请先安装 requests 和 beautifulsoup4: pip install requests beautifulsoup4 lxml") from e

# 尝试导入Qt相关库，用于线程处理
try:
    from PySide6.QtCore import QThread, Signal
except ImportError:
    # 如果没有PySide6，定义一个简单的替代类
    class QThread:
        def __init__(self):
            pass

    class Signal:
        def __init__(self, *args):
            self.callbacks = []

        def connect(self, callback):
            self.callbacks.append(callback)

        def emit(self, *args):
            for callback in self.callbacks:
                callback(*args)

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; WOW64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/108.0.5359.125 Safari/537.36"
HEADERS = {"User-Agent": USER_AGENT}

def _bs(html):
    """
    安全构造 BeautifulSoup：
    - 将输入统一转换为 UTF-8 字节（errors="replace"），避免 lxml 在内部重编码时报错
    - 优先使用 lxml 解析，失败则回退到内置 html.parser
    """
    try:
        if isinstance(html, bytes):
            data = html
        else:
            data = (html or "").encode("utf-8", "replace")
        return BeautifulSoup(data, "lxml", from_encoding="utf-8")
    except Exception:
        try:
            return BeautifulSoup(html or "", "html.parser")
        except Exception:
            return BeautifulSoup("", "html.parser")


def fetch_html(url: str, timeout: int = 20, retries: int = 3) -> str:
    """GET 请求带重试，字节级解码，稳健支持 gbk/gb18030/utf-8，避免目录/分页乱码造成解析丢失。"""
    def _detect_charset_from_headers(ct: str) -> str:
        if not ct:
            return ""
        m = re.search(r'charset\s*=\s*([A-Za-z0-9_\-]+)', ct, flags=re.IGNORECASE)
        if not m:
            return ""
        enc = m.group(1).strip().lower()
        return enc

    def _detect_charset_from_meta(raw: bytes) -> str:
        try:
            # <meta charset="gbk"> 或 <meta http-equiv="Content-Type" content="text/html; charset=gbk">
            m1 = re.search(br'<meta[^>]+charset=["\']?\s*([A-Za-z0-9_\-]+)\s*["\']?', raw, flags=re.IGNORECASE)
            if m1:
                return m1.group(1).decode("ascii", "ignore").lower()
            m2 = re.search(br'<meta[^>]+content=["\'][^"]*charset\s*=\s*([A-Za-z0-9_\-]+)[^"\']*["\']', raw, flags=re.IGNORECASE)
            if m2:
                return m2.group(1).decode("ascii", "ignore").lower()
        except Exception:
            pass
        return ""

    def _normalize_html(txt: str) -> str:
        # 统一换行，去除 BOM
        if txt and txt[0] == "\ufeff":
            txt = txt[1:]
        return txt.replace("\r\n", "\n").replace("\r", "\n")

    for attempt in range(1, retries + 1):
        try:
            resp = requests.get(url, headers=HEADERS, timeout=timeout)
            resp.raise_for_status()
            raw = resp.content or b""
            if not raw:
                return ""

            enc = _detect_charset_from_headers(resp.headers.get("Content-Type", "")) or _detect_charset_from_meta(raw)

            # 将 gbk 统一映射为 gb18030，覆盖更多汉字范围
            candidates = []
            if enc:
                enc_low = enc.lower()
                if enc_low in ("gbk", "gb2312"):
                    candidates.append("gb18030")
                else:
                    candidates.append(enc_low)
            # 常见优先
            candidates.extend(["utf-8", "gb18030"])

            last_err = None
            for codec in candidates:
                try:
                    txt = raw.decode(codec, errors="strict")
                    return _normalize_html(txt)
                except Exception as e:
                    last_err = e
                    continue
            # 最终兜底：宽松解码，确保不因个别字符中断
            try:
                txt = raw.decode("gb18030", errors="replace")
                return _normalize_html(txt)
            except Exception:
                if last_err:
                    raise last_err
                raise
        except Exception:
            if attempt == retries:
                raise
            time.sleep(0.3 * attempt)


def _locate_full_chapter_index(url: str, html: str) -> str:
    """从详情页 HTML 中定位完整章节目录页。找到则返回绝对URL，否则返回空字符串。"""
    try:
        netloc = (urlparse(url).netloc or "").lower()
        path = (urlparse(url).path or "")

        # 优先从 meta/mobile-agent 或 OG 标签中读取移动目录地址
        try:
            soup = _bs(html)
            # og:novel:read_url / og:url
            for prop in ("og:novel:read_url", "og:url"):
                m = soup.find("meta", attrs={"property": prop})
                if m and m.get("content"):
                    cu = str(m.get("content")).strip()
                    if cu and "/book/" in cu and cu.endswith("/"):
                        return cu
            # 页面中的“手机版/移动版”链接
            for a in soup.find_all("a", href=True):
                href = (a.get("href") or "").strip()
                if href and "/book/" in href:
                    absu = _abs_url(url, href)
                    if "m." in (urlparse(absu).netloc or "") and absu.endswith("/"):
                        return absu
        except Exception:
            pass

        # 适配 tbxsvv.cc / tbxsw.cc：PC目录形如 /html/140/140582/ -> 移动目录 https://m.{root}/book/140582/
        if ("tbxsvv.cc" in netloc) or ("tbxsw.cc" in netloc):
            m = re.search(r'/html/\d+/(\d+)/', path)
            if m:
                book_id = m.group(1)
                root = netloc.split(".", 1)[-1]  # tbxsvv.cc or tbxsw.cc
                return f"https://m.{root}/book/{book_id}/"

        # 适配 syvvw.cc：详情页 /1/{id}/ 跳到 /book/{id}.html
        if "syvvw.cc" in netloc:
            m = re.search(r'href=["\'](/book/\d+\.html)["\']', html, flags=re.IGNORECASE)
            if m:
                return _abs_url(url, m.group(1))

    except Exception:
        pass
    return ""

# -- 内部工具函数（组件内部使用） --
def _clean_text(s: str) -> str:
    if not s:
        return ""
    t = re.sub(r'[\r\t\xa0]+', ' ', s)
    return " ".join(t.split()).strip()

def _normalize_title(title: str) -> str:
    """标题归一化：修正常见错别字与空白，仅在章节模式处容错"""
    t = _clean_text(title or "")
    if not t:
        return t
    # 常见错字归一：'底/都' -> '第'（仅限章节号位置前缀）
    t = re.sub(r'^(底|都)(\s*[零〇一二三四五六七八九十百千万0-9]+)', r'第\2', t)
    # 将“第...张/璋/漳/仗/中/钟/衷”归一化为“章”，仅在模式位置替换
    t = re.sub(r'(第\s*[零〇一二三四五六七八九十百千万0-9]+\s*)[张璋漳仗中钟衷]', r'\1章', t)
    # 统一空白
    t = re.sub(r'\s+', ' ', t).strip()
    return t

_CHN_DIGITS = {"零":0,"〇":0,"一":1,"二":2,"三":3,"四":4,"五":5,"六":6,"七":7,"八":8,"九":9}
_CHN_UNITS = {"十":10,"百":100,"千":1000,"万":10000}
def _chinese_numeral_to_int(s: str):
    """中文数字转阿拉伯数字（常见格式），失败返回None"""
    if not s: return None
    s = s.strip()
    if s.isdigit():
        try: return int(s)
        except: return None
    total = 0
    current = 0
    has_unit = False
    for ch in s:
        if ch in _CHN_DIGITS:
            current = current * 10 + _CHN_DIGITS[ch]
        elif ch in _CHN_UNITS:
            unit = _CHN_UNITS[ch]
            has_unit = True
            if current == 0: current = 1
            total += current * unit
            current = 0
        else:
            return None
    total += current
    if total == 0 and has_unit and current == 0:
        return 10
    return total if total > 0 else None

def _is_chapter_href(href: str) -> bool:
    if not href:
        return False
    href = href.strip()
    if href.lower().startswith("javascript:") or href.startswith("#"):
        return False
    return href.lower().endswith(".html")

def _abs_url(base_url: str, href_raw: str) -> str:
    """将相对链接规范化为绝对URL，并去除 #/? 尾部碎片"""
    if not href_raw:
        return ""
    return urljoin(base_url, href_raw).split('#')[0].split('?')[0]

def _is_nav_path(url: str) -> bool:
    """判定URL路径是否为站点导航类路径"""
    path = (urlparse(url).path or "")
    return bool(_RE_NAV_PATH.search(path))

# 非章节标题噪声过滤（常见于移动站“直达页面底部/加入书架”等）
_RE_NOISE_TITLE = re.compile(r'(直达页面底部|直达底部|直达底|加入书架)', re.IGNORECASE)
def _is_noise_title(title: str) -> bool:
    t = _normalize_title(title or "")
    if not t:
        return False
    return bool(_RE_NOISE_TITLE.search(t))

# 基于 href 的噪声过滤（含锚点跳转、页底关键词等）
def _is_noise_href(href_raw: str) -> bool:
    if not href_raw:
        return False
    s = href_raw.strip().lower()
    # 直接锚点或包含锚点的底部跳转
    if s.startswith("#"):
        return True
    if "#footer" in s or "#bottom" in s or "footer" in s and ".html" in s:
        return True
    # 常见“直达底部/页底”关键词
    return ("底部" in s or "页底" in s) and (s.startswith("javascript:") or "#" in s or ".html" in s)

def _entry_from_anchor(a, base_url: str):
    """
    将 <a> 标签解析为章节条目：
      - 过滤无效/噪声 href（javascript:, #, 页底等）
      - 归一化绝对URL，仅接受以 .html 结尾的章节链接
      - 清洗并归一化标题，过滤“直达底部/加入书架”等噪声标题
    返回: dict{"title": str|None, "url": str} 或 None
    """
    try:
        href_raw = (a.get("href") or "").strip()
        if not href_raw or _is_noise_href(href_raw):
            return None
        href = _abs_url(base_url, href_raw)
        if not _is_chapter_href(href) or _is_nav_path(href):
            return None
        title = _normalize_title(_clean_text(a.get_text(" ", strip=True)))
        if _is_noise_title(title):
            return None
        return {"title": title or None, "url": href}
    except Exception:
        return None

def _parse_chapnum(t: str, u: str):
    """从标题或URL解析章节号（优化：优先URL尾数，标题为兜底；容错掌/章/中文数字/全角/前导零）"""
    # 1) URL尾数优先（最快）
    if u:
        m_url = _RE_NUM_HTML_TAIL.search(u)
        if m_url:
            try:
                return int(m_url.group(1))
            except:
                pass
    # 2) 标题兜底（仅当URL无数字时使用复杂解析）
    if t:
        norm = _normalize_title(t)
        m = _RE_TITLE_CHAPNUM.search(norm)
        if m:
            s = m.group(1)
            s2 = ''.join(chr(ord(ch) - 65248) if '０' <= ch <= '９' else ch for ch in s).strip()
            if re.fullmatch(r'\d+', s2):
                try:
                    return int(s2.lstrip('0') or '0')
                except:
                    pass
            cn = _chinese_numeral_to_int(s2)
            if cn is not None:
                return cn
        # 更宽松：标题中的纯数字
        m2 = re.search(r'(?<!\d)(\d{1,6})(?!\d)', norm)
        if m2:
            try:
                return int(m2.group(1))
            except:
                pass
    # 备选：URL中的数字.html
    m3 = re.search(r'(\d+)\.html$', u)
    if m3:
        try:
            return int(m3.group(1))
        except:
            pass
    return None


def extract_chapter_list_from_index_precise_fixed(index_html: str, base_url: str):
    """
    从书籍详情页 HTML 中提取"全部章节"目录列表，返回：
      [{'index': i, 'title': title, 'url': url, 'chapter_num': maybe_int}, ...]
    策略与细节：
      - 优先使用 id="allChapters2"（或 id="allChapters" 下的 <ul class="chapter">）；
      - 否则在页面上寻找 class="chapter" 的 <ul>，并优先选取包含"全部章节"附近的那个或最多 <li> 的那个；
      - 特别处理笔趣看风格的 <dl> 结构，优先提取"正文卷"部分，避免章节顺序错乱；
      - 仅采集 .html 链接（过滤菜单、首页、分类、书架等非章节项）；
      - 保持页面 DOM 顺序（避免盲目按 URL 数字排序造成乱序或丢章）；
      - 尝试解析章节号（title 或 url 的尾部数字），放到 chapter_num 中，便于后续校验/排序。
    """
    soup = _bs(index_html)

    # 检测是否为笔趣看风格的 <dl> 结构
    dl_elements = soup.find_all("dl")
    if dl_elements:
        # 尝试处理笔趣看风格的章节列表
        entries = _extract_from_dl_structure(dl_elements, base_url)
        if entries:
            return _finalize_entries(entries)

    # 1) direct id -> ul.chapter
    all_chapters_ul = None
    el = soup.find(id="allChapters2")
    if el:
        if el.name == "ul" and "chapter" in (el.get("class") or []):
            all_chapters_ul = el
        else:
            found = el.find("ul", class_="chapter")
            if found:
                all_chapters_ul = found
    if not all_chapters_ul:
        el2 = soup.find(id="allChapters")
        if el2:
            found = el2.find("ul", class_="chapter")
            if found:
                all_chapters_ul = found

    # 2) fallback: find ul.chapter with nearby '全部章节' or the longest list（优化：限域判断，减少文本获取）
    if not all_chapters_ul:
        uls = soup.find_all("ul", class_="chapter")
        candidate = None
        if uls:
            # 优先选择有“全部章节”提示的容器
            for u in uls:
                try:
                    parent_text = u.parent.get_text(" ", strip=True) if u.parent else ""
                    if parent_text and _RE_CHAPTER_CONTAINER_HINT.search(parent_text):
                        candidate = u
                        break
                    ok = False
                    for sib in u.previous_siblings:
                        text = getattr(sib, "get_text", None)
                        txt = text(" ", strip=True) if callable(text) else (sib.strip() if isinstance(sib, str) else "")
                        if txt and _RE_CHAPTER_CONTAINER_HINT.search(txt):
                            ok = True
                            break
                    if ok:
                        candidate = u
                        break
                except Exception:
                    continue
            # 次选：选择 li 数最多的UL
            if candidate is None:
                try:
                    u_sorted = sorted(uls, key=lambda x: len(x.find_all("li")), reverse=True)
                    if u_sorted and len(u_sorted[0].find_all("li")) >= 5:
                        candidate = u_sorted[0]
                except Exception:
                    pass
        all_chapters_ul = candidate

    entries = []
    seen = set()
    if all_chapters_ul:
        for a in all_chapters_ul.find_all("a", href=True):
            e = _entry_from_anchor(a, base_url)
            if not e:
                continue
            href = e["url"]
            if href in seen:
                continue
            entries.append(e)
            seen.add(href)
    else:
        # 整页回退扫描（优化：严格过滤路径，采集时去重，避免全页重复工作）
        seen = set()
        for a in soup.find_all("a", href=True):
            e = _entry_from_anchor(a, base_url)
            if not e:
                continue
            href = e["url"]
            if href in seen:
                continue
            entries.append(e)
            seen.add(href)

    # 针对已定位的章节UL做一次受限正则补齐，避免Soup遗漏（性能友好）
    try:
        if all_chapters_ul:
            entries = _supplement_entries_from_ul(entries, all_chapters_ul, base_url)
    except Exception:
        pass

    # 检查并尝试补齐缺失章节（基于标题/URL解析得到的章节号）
    try:
        # 优化：仅在条目数较少或编号范围明确时进行缺章补齐；严格限流、仅在UL源码中扫描
        nums = []
        for e in entries:
            # 优先用URL尾数（快速）
            n = None
            u = e.get("url") or ""
            m_url = _RE_NUM_HTML_TAIL.search(u)
            if m_url:
                try:
                    n = int(m_url.group(1))
                except:
                    n = None
            if n is None:
                n = _parse_chapnum(e.get("title") or "", u)  # 兜底
            if isinstance(n, int):
                nums.append(n)
        if nums and len(nums) >= 5:
            nums.sort()
            min_num, max_num = nums[0], nums[-1]
            # 大范围缺口补齐会非常耗时，这里限制最大补齐数量，且仅在UL源码中扫描
            expected = set(range(min_num, max_num + 1))
            present = set(nums)
            missing = sorted(expected - present)
            if all_chapters_ul and missing:
                limit = 120 if len(entries) > 1500 else 240
                if len(missing) > limit:
                    missing = missing[:limit]
                existing_urls = {e["url"] for e in entries}
                ul_html = str(all_chapters_ul)
                for chapter_num in missing:
                    # 模式生成（避免大范围 re.search 多次拼接）
                    patterns = (
                        rf'<a\s+[^>]*href="(\d+\.html)"[^>]*>\s*第\s*0*{chapter_num}\s*章[^<]*</a>',
                        rf'<a\s+[^>]*href="(\d+\.html)"[^>]*>\s*第\s*0*{chapter_num}\s*掌[^<]*</a>',
                        rf'<a\s+[^>]*href="(\d+\.html)"[^>]*>[^<]*{chapter_num}[^<]*</a>',
                    )
                    found_entry = None
                    for pat in patterns:
                        m = re.search(pat, ul_html, flags=re.IGNORECASE)
                        if m:
                            href_rel = m.group(1)
                            full = m.group(0)
                            tmatch = re.search(r'>([^<]+)</a>', full)
                            title_text = _normalize_title(_clean_text(tmatch.group(1) if tmatch else f"第{chapter_num}章"))
                            url_abs = _abs_url(base_url, href_rel)
                            if url_abs not in existing_urls:
                                found_entry = {"title": title_text, "url": url_abs}
                            break
                    if found_entry:
                        entries.append(found_entry)
                        existing_urls.add(found_entry["url"])
    except Exception:
        pass

    # 目录分页抓取与合并（如 index_2.html / list_2.html）- 优先下拉页码顺序遍历，未命中再回退 BFS
    try:
        # 优先：从首页下拉列表收集全部分页，按页码升序遍历
        pages = []
        pages.append((1, base_url))  # 第1页

        try:
            options = soup.find_all("option")
            for opt in options:
                val = str(opt.get("value") or "").strip()
                if not val:
                    continue
                absu = _abs_url(base_url, val)
                m = _RE_PAGINATION.search((urlparse(absu).path or ""))
                if m:
                    idx = int(m.group(1))
                    if idx >= 2:
                        pages.append((idx, absu))
            # 去重并按页码排序
            seenp = set()
            pages = sorted([(i, u) for i, u in pages if not (u in seenp or seenp.add(u))], key=lambda x: x[0])
        except Exception:
            pages = [(1, base_url)]

        # 若存在 index_2.html 之类分页，则严格按“正文”列表逐页采集（每页20条）
        has_paged = any(i >= 2 for i, _ in pages)
        if has_paged:
            entries = []
            for idx, purl in pages:
                try:
                    p_html = index_html if idx == 1 else fetch_html(purl)
                    page_entries = _extract_entries_from_paged_html(p_html, purl)
                    if page_entries:
                        entries.extend(page_entries)
                except Exception:
                    continue
        else:
            # 回退：使用原 BFS 方案发现其它分页
            def collect_pagination_urls(soup_obj, current_url):
                found = set()
                cpath = (urlparse(current_url).path or "")
                cdir = cpath[: cpath.rfind("/") + 1] if "/" in cpath else cpath

                for a in soup_obj.find_all("a", href=True):
                    rel = (a.get("href") or "").strip()
                    if not rel:
                        continue
                    absu = _abs_url(current_url, rel)
                    path = (urlparse(absu).path or "")
                    if not _RE_PAGINATION.search(path):
                        continue
                    if cdir and not path.startswith(cdir):
                        continue
                    if absu and absu != current_url:
                        found.add(absu)

                for opt in soup_obj.find_all("option"):
                    val = str(opt.get("value") or "").strip()
                    if not val:
                        continue
                    absu = _abs_url(current_url, val)
                    path = (urlparse(absu).path or "")
                    if not _RE_PAGINATION.search(path):
                        continue
                    if cdir and not path.startswith(cdir):
                        continue
                    if absu and absu != current_url:
                        found.add(absu)
                return found

            visited = set([base_url])
            queue = list(collect_pagination_urls(soup, base_url))
            for u in queue:
                visited.add(u)

            i = 0
            while i < len(queue):
                purl = queue[i]
                i += 1
                try:
                    p_html = fetch_html(purl)
                    p_soup = _bs(p_html)
                    page_entries = _extract_entries_from_paged_html(p_html, purl)
                    if page_entries:
                        entries.extend(page_entries)
                    more = collect_pagination_urls(p_soup, purl)
                    for nxt in more:
                        if nxt not in visited:
                            visited.add(nxt)
                            queue.append(nxt)
                except Exception:
                    continue
    except Exception:
        pass

    return _finalize_entries(entries)


def _extract_from_dl_structure(dl_elements, base_url):
    """处理笔趣看风格的 <dl> 结构，优先提取正文卷"""
    main_chapters = []  # 正文卷章节
    latest_chapters = []  # 最新章节

    for dl in dl_elements:
        if not hasattr(dl, "find_all"):
            continue
        dt_elements = dl.find_all("dt")

        for dt in dt_elements:
            dt_text = _clean_text(dt.get_text())

            # 收集该 dt 后面的所有 dd 元素，直到下一个 dt
            dd_elements = []
            current = dt.next_sibling
            while current:
                if getattr(current, "name", None) == "dt":
                    break
                if getattr(current, "name", None) == "dd":
                    dd_elements.append(current)
                current = current.next_sibling

            # 根据 dt 的内容判断章节类型
            if re.search(r'正文卷|正文|第.*卷', dt_text):
                # 这是正文卷，优先处理
                for dd in dd_elements:
                    a = dd.find("a", href=True)
                    if a:
                        e = _entry_from_anchor(a, base_url)
                        if e:
                            main_chapters.append(e)

            elif re.search(r'最新章节|最新|更新', dt_text):
                # 这是最新章节列表
                for dd in dd_elements:
                    a = dd.find("a", href=True)
                    if a:
                        e = _entry_from_anchor(a, base_url)
                        if e:
                            latest_chapters.append(e)

    # 优先返回正文卷，如果没有正文卷则返回最新章节（但需要反转顺序）
    if main_chapters:
        return main_chapters
    elif latest_chapters:
        # 最新章节通常是倒序的，需要反转
        return list(reversed(latest_chapters))

    # 兜底：部分站点仅有 div#list 下的单一 dl，dt 文字不含“正文/最新”，但 dd 里全是章节
    try:
        collected = []
        for dl in dl_elements:
            # 限定在 #list 下的 dl 优先
            parent = getattr(dl, "parent", None)
            in_list = False
            while parent is not None:
                if getattr(parent, "get", None) and parent.get("id") == "list":
                    in_list = True
                    break
                parent = getattr(parent, "parent", None)
            # 收集 dd>a
            dd_links = dl.find_all("dd")
            for dd in dd_links:
                a = dd.find("a", href=True)
                if not a:
                    continue
                e = _entry_from_anchor(a, base_url)
                if e:
                    collected.append(e)
            # 如果在 #list 下且已收集到一定数量，认为是章节列表
            if in_list and len(collected) >= 5:
                return collected
        # 若未命中 #list 优先，也可在全局 dl 里判断数量充足时作为弱兜底
        if len(collected) >= 20:
            return collected
    except Exception:
        pass

    return [] 


def _extract_entries_from_paged_html(index_html: str, base_url: str):
    """
    从分页目录页中提取章节条目（仅限章节容器范围），避免误采导航。
    优先 div#list 下的 dl/dd/a；次选 ul.chapter 下的 a。
    """
    try:
        soup = _bs(index_html)
        entries = []

        # 优先：精准提取“正文”对应的 ul.chapter，避免混入“最新章节预览”
        try:
            intros = soup.find_all("div", class_="intro")
            target_ul = None
            for intro in intros:
                try:
                    if intro.get_text(strip=True) == "正文":
                        sib = intro
                        while sib is not None:
                            sib = getattr(sib, "next_sibling", None)
                            if not getattr(sib, "name", None):
                                continue
                            if sib.name == "ul" and "chapter" in (sib.get("class") or []):
                                target_ul = sib
                                break
                        if target_ul:
                            break
                except Exception:
                    continue
            if target_ul:
                for a in target_ul.find_all("a", href=True):
                    e = _entry_from_anchor(a, base_url)
                    if e:
                        entries.append(e)
                if entries:
                    return entries
        except Exception:
            pass

        # 1) 优先 #list dl 结构
        try:
            dl_in_list = soup.select_one("#list dl")
        except Exception:
            dl_in_list = None
        if dl_in_list:
            dd_links = getattr(dl_in_list, "find_all", lambda *_: [])("dd")
            for dd in dd_links:
                a = dd.find("a", href=True)
                if not a:
                    continue
                e = _entry_from_anchor(a, base_url)
                if e:
                    entries.append(e)
            if entries:
                return entries

        # 2) 次选 ul.chapter
        uls = soup.find_all("ul", class_="chapter")
        for u in uls or []:
            for a in u.find_all("a", href=True):
                e = _entry_from_anchor(a, base_url)
                if e:
                    entries.append(e)
        return entries
    except Exception:
        return []

def _supplement_entries_from_ul(entries, ul_el, base_url):
    """从指定的章节UL源码中补齐遗漏的<a>锚点，仅在该UL范围内扫描，避免全页慢扫描"""
    try:
        if not ul_el:
            return entries
        existing = {e["url"] for e in entries}
        ul_html = str(ul_el)
        # 受限正则：只在该UL源码中匹配锚点
        for m in _RE_ANCHOR_IN_UL.finditer(ul_html):
            href_rel = m.group(1)
            title_text = _normalize_title(_clean_text(m.group(2)))
            url_abs = _abs_url(base_url, href_rel)
            if _is_chapter_href(url_abs) and url_abs not in existing:
                entries.append({"title": title_text or None, "url": url_abs})
                existing.add(url_abs)
    except Exception:
        # 补充失败不影响主流程
        pass
    return entries

def _finalize_entries(entries):
    """最终处理章节列表：去重、添加索引和章节号"""
    # de-duplicate preserving order
    seen_urls = set()
    cleaned = []
    for e in entries:
        u = e["url"]
        if u in seen_urls:
            continue
        seen_urls.add(u)
        cleaned.append(e)

    final = []
    for i, e in enumerate(cleaned, start=1):
        # 优先用URL尾数作为章节号（快速），标题作为兜底
        url = e["url"]
        chapnum = None
        m_url = _RE_NUM_HTML_TAIL.search(url)
        if m_url:
            try:
                chapnum = int(m_url.group(1))
            except:
                chapnum = None
        if chapnum is None:
            chapnum = _parse_chapnum(e.get("title"), url)
        title = _normalize_title(e.get("title") or (f"第{i}章" if chapnum is None else f"第{chapnum}章"))
        final.append({"index": i, "title": title, "url": url, "chapter_num": chapnum})

    return final


def extract_title_and_content_from_chapter(html, base_url=None):
    """
    从章节页面HTML中提取标题和正文内容

    参数:
        html: 章节页面的HTML内容
        base_url: 基础URL，用于处理相对链接

    返回:
        tuple: (标题, 内容, 段落列表)
    """
    soup = _bs(html)
    title = ""
    h1_el = soup.find("h1")
    if h1_el and hasattr(h1_el, "get_text"):
        title = h1_el.get_text(strip=True)
    if not title and soup.title and soup.title.string:
        title = soup.title.string.strip()
        title = re.sub(r"\s*[-_—|].*$", "", title).strip()
    ids = ("content", "chaptercontent", "contentbox", "read-content", "bookcontent", "txt", "nr1")
    classes = ("content", "chapter-content", "read-content", "novel-content", "contentbox", "article", "maintext", "nr")
    candidates = []
    for idn in ids:
        el = soup.find(id=idn)
        if el: candidates.append(el)
    for cls in classes:
        for el in soup.find_all(class_=cls):
            candidates.append(el)
    if not candidates:
        divs = [d for d in soup.find_all(['div','article','section']) if len(d.get_text(strip=True)) > 120]
        divs.sort(key=lambda d: len(d.get_text()), reverse=True)
        if divs:
            candidates.append(divs[0])
    for cont in candidates:
        if not hasattr(cont, "get_text"):
            continue
        for bad in cont.select('script, style, iframe, noscript, .ads, .advert, .paybox'):
            bad.decompose()
        paragraphs = []
        ps = cont.find_all('p')
        if ps:
            for p in ps:
                t = p.get_text("\n", strip=True)
                if t:
                    paragraphs.append(t)
        else:
            raw = cont.get_text("\n", strip=True)
            lines = [ln.strip() for ln in raw.splitlines() if ln.strip()]
            paragraphs = lines
        if paragraphs:
            content = "\n\n".join(paragraphs)
            return title or "", content, paragraphs
    raw = soup.body.get_text("\n", strip=True) if soup.body else soup.get_text("\n", strip=True)
    lines = [ln.strip() for ln in raw.splitlines() if ln.strip()]
    content = "\n\n".join(lines)
    return title or "", content, lines


def load_json(path: Path, default):
    """
    从指定路径加载JSON文件，如果失败则返回默认值

    参数:
        path: JSON文件路径
        default: 加载失败时返回的默认值

    返回:
        加载的JSON对象或默认值
    """
    try:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        pass
    return default


def save_json(path: Path, obj):
    """
    将对象保存为JSON文件

    参数:
        path: 保存路径
        obj: 要保存的对象
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")


def create_book_directory_and_debug(meta, chapters):
    """
    创建书籍目录并保存调试文件
    
    参数:
        meta: 书籍元数据
        chapters: 章节列表
    """
    bdir = Path(meta["book_dir"])
    (bdir / "chapters").mkdir(parents=True, exist_ok=True)
    
    try:
        debug_path = bdir / "index_debug.json"
        debug_path.write_text(json.dumps(chapters, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass


def generate_book_id_from_url(url):
    """
    从URL生成书籍ID
    
    参数:
        url: 书籍URL
        
    返回:
        str: 生成的书籍ID
    """
    return str(abs(hash(url)))


def create_book_metadata(url, chapters, soup_title=None):
    """
    创建书籍元数据
    
    参数:
        url: 书籍URL
        chapters: 章节列表
        soup_title: 从HTML提取的标题
        
    返回:
        tuple: (book_id, metadata)
    """
    from pathlib import Path
    import sys
    
    # 获取应用目录
    if getattr(sys, 'frozen', False):
        script_dir = Path(sys.executable).parent
    else:
        try:
            script_dir = Path(__file__).resolve().parent
        except NameError:
            script_dir = Path.cwd()
    
    app_dir = script_dir / ".pyside_novel_reader_reader_fixed"
    
    bid = generate_book_id_from_url(url)
    
    meta = {
        "title": soup_title or f"在线书 {bid}",
        "index_url": url,
        "chapters": chapters,
        "book_dir": str(app_dir / f"book_{bid}"),
        "chapter_index": 0
    }
    
    return bid, meta


def extract_book_title_from_html(html):
    """
    从HTML中提取书籍标题

    参数:
        html: 书籍页面的HTML内容

    返回:
        str: 提取的书籍标题，如果无法提取则返回空字符串
    """
    try:
        soup = _bs(html)
        if soup.title and soup.title.string:
            title = soup.title.string.strip().split("-")[0].strip()
            return title
    except Exception:
        pass
    return ""


def process_chapter_content_for_display(content, font_family, font_size, line_height, night_mode=False, default_text_color="#800000"):
    """
    处理章节内容以便在UI中显示

    参数:
        content: 章节内容
        font_family: 字体
        font_size: 字号
        line_height: 行高
        night_mode: 是否为夜间模式
        default_text_color: 默认文字颜色

    返回:
        str: 处理后的HTML内容
    """
    # 根据夜间模式调整文字颜色
    text_color = "#d0d0d0" if night_mode else default_text_color

    # 处理内容中的特殊字符和换行符
    # 正确的HTML转义，避免内容中的符号影响显示
    processed_content = (content or "").replace("&", "&").replace("<", "<").replace(">", ">").replace("\n", "<br>")

    html = f"""<div style='white-space:pre-wrap;font-family:{font_family};font-size:{font_size}pt;line-height:{line_height};color:{text_color};padding:20px;'>{processed_content}</div>"""

    return html


# Index fetch thread - 处理目录获取和解析
class IndexFetchThread(QThread):
    """
    目录获取线程：异步请求目录页与解析，避免阻塞UI
    
    包含内存优化的章节提取功能，支持大量章节的分批处理
    """
    finished = Signal(list, str)  # chapters, error
    progress = Signal(str)
    chapter_batch_ready = Signal(list, int, int)  # batch_chapters, current_count, total_estimated

    def __init__(self, url):
        super().__init__()
        self.url = url
        self._should_stop = False

    def stop(self):
        """停止线程执行"""
        self._should_stop = True

    def run(self):
        """线程主执行函数"""
        try:
            self.progress.emit("请求目录页…")
            html = fetch_html(self.url)
            # 适配：部分站点（如 m.syvvw.cc）详情页不含完整目录，尝试跳转到 /book/{id}.html
            alt_url = _locate_full_chapter_index(self.url, html)
            if alt_url and alt_url != self.url:
                try:
                    self.progress.emit("发现完整目录页，跳转解析…")
                    html = fetch_html(alt_url)
                    self.url = alt_url
                except Exception:
                    # 跳转失败不影响后续解析
                    pass
            self.progress.emit("解析目录…")
            
            # 使用流式处理来避免内存峰值
            chapters = self._extract_chapters_with_memory_optimization(html, self.url)
            
            if not self._should_stop:
                self.finished.emit(chapters, "")
        except Exception as e:
            if not self._should_stop:
                self.finished.emit([], str(e))

    def _extract_chapters_with_memory_optimization(self, html, base_url):
        """内存优化的章节提取方法"""
        try:
            # 针对存在目录分页的站点（tbxsvv/tbxsw/syvvw），强制走标准解析以覆盖所有分页
            host = (urlparse(base_url).netloc or "").lower()
            if ("tbxsvv.cc" in host) or ("tbxsw.cc" in host) or ("syvvw.cc" in host):
                return extract_chapter_list_from_index_precise_fixed(html, base_url)

            # 首先快速估算章节数量
            self.progress.emit("估算章节数量…")
            estimated_count = self._estimate_chapter_count(html)
            
            if estimated_count > 3000:
                # 对于大量章节，使用分批处理（仅在无分页站点使用）
                self.progress.emit(f"检测到大量章节({estimated_count}+)，使用内存优化模式…")
                return self._extract_chapters_in_batches(html, base_url, estimated_count)
            else:
                # 对于较少章节，使用原始方法
                return extract_chapter_list_from_index_precise_fixed(html, base_url)
                
        except Exception as e:
            # 如果优化方法失败，回退到原始方法
            self.progress.emit("优化模式失败，回退到标准模式…")
            return extract_chapter_list_from_index_precise_fixed(html, base_url)

    def _estimate_chapter_count(self, html):
        """快速估算章节数量"""
        # 简单计算 .html 链接的数量作为估算
        html_links = re.findall(r'href="[^"]*\.html"', html, re.IGNORECASE)
        return len(html_links)

    def _extract_chapters_in_batches(self, html, base_url, estimated_count):
        """分批提取章节，减少内存占用"""
        import gc
        
        all_chapters = []
        batch_size = 500  # 每批处理500章
        
        try:
            self.progress.emit("开始分批解析章节…")
            
            # 使用更轻量的解析方式
            soup = _bs(html)
            
            # 找到章节容器
            chapter_container = self._find_chapter_container(soup)
            if not chapter_container:
                # 如果找不到容器，回退到原始方法
                return extract_chapter_list_from_index_precise_fixed(html, base_url)
            
            # 获取所有章节链接
            chapter_links = chapter_container.find_all("a", href=True)
            total_links = len(chapter_links)
            
            self.progress.emit(f"找到 {total_links} 个链接，开始分批处理…")
            
            processed_count = 0
            batch_chapters = []
            seen_urls = set()
            
            for i, link in enumerate(chapter_links):
                if self._should_stop:
                    break
                    
                try:
                    href = link.get("href", "").strip()
                    if not href:
                        continue
                        
                    # 构建完整URL
                    full_url = _abs_url(base_url, href)
                    
                    # 检查是否为章节链接
                    if not self._is_valid_chapter_url(full_url):
                        continue
                        
                    # 避免重复
                    if full_url in seen_urls:
                        continue
                    seen_urls.add(full_url)
                    
                    # 提取标题
                    title = self._clean_title(link.get_text(strip=True))
                    
                    # 创建章节对象（轻量化）
                    chapter = {
                        "index": processed_count + 1,
                        "title": title,
                        "url": full_url
                    }
                    
                    batch_chapters.append(chapter)
                    processed_count += 1
                    
                    # 达到批次大小或处理完成时，处理当前批次
                    if len(batch_chapters) >= batch_size or i == len(chapter_links) - 1:
                        # 发送批次数据
                        self.chapter_batch_ready.emit(batch_chapters.copy(), processed_count, total_links)
                        
                        # 添加到总列表
                        all_chapters.extend(batch_chapters)
                        
                        # 清理当前批次，释放内存
                        batch_chapters.clear()
                        
                        # 更新进度
                        progress_pct = int((processed_count / total_links) * 100)
                        self.progress.emit(f"已处理 {processed_count}/{total_links} 章节 ({progress_pct}%)")
                        
                        # 强制垃圾回收
                        if processed_count % 1000 == 0:
                            gc.collect()
                            
                except Exception as e:
                    # 单个章节处理失败不影响整体
                    continue
            
            self.progress.emit(f"章节解析完成，共 {len(all_chapters)} 章")
            return all_chapters
            
        except Exception as e:
            self.progress.emit(f"分批处理失败: {str(e)}")
            # 回退到原始方法
            return extract_chapter_list_from_index_precise_fixed(html, base_url)

    def _find_chapter_container(self, soup):
        """查找章节容器"""
        # 部分站点为 div#list <dl> 结构，优先识别
        try:
            dl_in_list = soup.select_one("#list dl")
            if dl_in_list and dl_in_list.find_all("a", href=True):
                return dl_in_list
        except Exception:
            pass

        # 常见容器集合
        containers = [
            soup.find(id="allChapters2"),
            soup.find(id="allChapters"),
            soup.find("ul", class_="chapter"),
            soup.find("div", class_="listmain"),
            soup.find("div", id="list"),
        ]
        for container in containers:
            if container and container.find_all("a", href=True):
                return container

        # 如果都找不到，返回整个文档
        return soup

    def _is_valid_chapter_url(self, url):
        """检查是否为有效的章节URL（复用全局判定）"""
        return _is_chapter_href(url) and not _is_nav_path(url)

    def _clean_title(self, title):
        """清理章节标题（复用全局清洗与归一化）"""
        return _normalize_title(_clean_text(title))


# Chapter fetch thread
class ChapterFetchThread(QThread):
    """
    章节内容获取线程

    用于异步获取章节内容，避免阻塞UI线程
    """
    finished = Signal(int, dict, str)
    progress = Signal(str)

    def __init__(self, chapter_url, index, cache_dir):
        """
        初始化章节获取线程

        参数:
            chapter_url: 章节URL
            index: 章节索引
            cache_dir: 缓存目录
        """
        super().__init__()
        self.chapter_url = chapter_url
        self.index = index
        self.cache_dir = Path(cache_dir)

    def run(self):
        """
        线程运行函数
        获取章节内容，如果缓存存在则从缓存读取，否则从网络获取并缓存
        """
        try:
            json_path = self.cache_dir / f"{self.index:04d}.json"
            if json_path.exists():
                try:
                    data = json.loads(json_path.read_text(encoding="utf-8"))
                    self.finished.emit(self.index, data, "")
                    return
                except Exception:
                    pass
            self.progress.emit(f"请求章节: {self.chapter_url}")
            html = fetch_html(self.chapter_url)
            title, content, paragraphs = extract_title_and_content_from_chapter(html, base_url=self.chapter_url)
            data = {"index": self.index, "title": title, "url": self.chapter_url, "content": content, "paragraphs": paragraphs}
            self.cache_dir.mkdir(parents=True, exist_ok=True)
            json_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            self.finished.emit(self.index, data, "")
        except Exception as e:
            self.finished.emit(self.index, {}, str(e))


# module exports
__all__ = [
    "fetch_html",
    "extract_chapter_list_from_index_precise_fixed",
    "extract_title_and_content_from_chapter",
    "extract_book_title_from_html",
    "process_chapter_content_for_display",
    "load_json",
    "save_json",
    "create_book_directory_and_debug",
    "generate_book_id_from_url",
    "create_book_metadata",
    "IndexFetchThread",
    "ChapterFetchThread"
]

