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
from threading import Thread

# 预编译常用正则，降低重复编译开销
_RE_NUM_HTML_TAIL = re.compile(r'(\d+)\.html$', re.IGNORECASE)
_RE_CHAPTER_CONTAINER_HINT = re.compile(r'全部章节|全部章|全部目录', re.IGNORECASE)
_RE_ANCHOR_IN_UL = re.compile(r'<a\s+[^>]*href="(\d+\.html)"[^>]*>([^<]+)</a>', re.IGNORECASE)
_RE_TITLE_CHAPNUM = re.compile(r'第\s*([0-9０-９零〇一二三四五六七八九十百千万]+)\s*[章掌回集卷]', re.IGNORECASE)
_RE_TITLE_ANYNUM = re.compile(r'(?<!\d)(\d{1,6})(?!\d)')
_RE_NAV_PATH = re.compile(r'/sort/|/author/|/fullbook/|/mybook|/cover/|/index', re.IGNORECASE)

try:
    import requests
    from bs4 import BeautifulSoup
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


def fetch_html(url: str, timeout: int = 20, retries: int = 3) -> str:
    """简单的 GET 请求带重试，返回响应文本（自动检测编码）。"""
    for attempt in range(1, retries + 1):
        try:
            r = requests.get(url, headers=HEADERS, timeout=timeout)
            r.raise_for_status()
            r.encoding = r.apparent_encoding
            return r.text
        except Exception:
            if attempt == retries:
                raise
            time.sleep(0.3 * attempt)


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
    # 将“第...张/璋/漳/仗”归一化为“章”，仅在模式位置替换，避免误改正文
    t = re.sub(r'(第\s*[零〇一二三四五六七八九十百千万0-9]+\s*)[张璋漳仗]', r'\1章', t)
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
    soup = BeautifulSoup(index_html, "lxml")

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
            href_raw = a.get("href", "").strip()
            if not href_raw:
                continue
            href = urljoin(base_url, href_raw).split('#')[0].split('?')[0]
            if not _is_chapter_href(href):
                continue
            if href in seen:
                continue
            title = _normalize_title(_clean_text(a.get_text(" ", strip=True)))
            entries.append({"title": title or None, "url": href})
            seen.add(href)
    else:
        # 整页回退扫描（优化：严格过滤路径，采集时去重，避免全页重复工作）
        seen = set()
        for a in soup.find_all("a", href=True):
            href_raw = a.get("href", "").strip()
            if not href_raw:
                continue
            href = urljoin(base_url, href_raw).split('#')[0].split('?')[0]
            if href in seen:
                continue
            if not _is_chapter_href(href):
                continue
            path = (urlparse(href).path or "")
            if _RE_NAV_PATH.search(path):
                continue
            title = _normalize_title(_clean_text(a.get_text(" ", strip=True)))
            entries.append({"title": title or None, "url": href})
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
                            url_abs = urljoin(base_url, href_rel).split('#')[0].split('?')[0]
                            if url_abs not in existing_urls:
                                found_entry = {"title": title_text, "url": url_abs}
                            break
                    if found_entry:
                        entries.append(found_entry)
                        existing_urls.add(found_entry["url"])
    except Exception:
        pass

    return _finalize_entries(entries)


def _extract_from_dl_structure(dl_elements, base_url):
    """处理笔趣看风格的 <dl> 结构，优先提取正文卷"""
    main_chapters = []  # 正文卷章节
    latest_chapters = []  # 最新章节

    for dl in dl_elements:
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
                        href_raw = a.get("href", "").strip()
                        if href_raw:
                            href = urljoin(base_url, href_raw).split('#')[0].split('?')[0]
                            if _is_chapter_href(href):
                                # 标题统一使用 get_text，避免属性类型导致解析失败
                                title = _normalize_title(_clean_text(a.get_text(" ", strip=True)))
                                main_chapters.append({"title": title or None, "url": href})

            elif re.search(r'最新章节|最新|更新', dt_text):
                # 这是最新章节列表
                for dd in dd_elements:
                    a = dd.find("a", href=True)
                    if a:
                        href_raw = a.get("href", "").strip()
                        if href_raw:
                            href = urljoin(base_url, href_raw).split('#')[0].split('?')[0]
                            if _is_chapter_href(href):
                                # 标题统一使用 get_text，避免属性类型导致解析失败
                                title = _normalize_title(_clean_text(a.get_text(" ", strip=True)))
                                latest_chapters.append({"title": title or None, "url": href})

    # 优先返回正文卷，如果没有正文卷则返回最新章节（但需要反转顺序）
    if main_chapters:
        return main_chapters
    elif latest_chapters:
        # 最新章节通常是倒序的，需要反转
        return list(reversed(latest_chapters))

    return []


def _supplement_entries_from_ul(entries, ul_el, base_url):
    """从指定的章节UL源码中补齐遗漏的<a>锚点，仅在该UL范围内扫描，避免全页慢扫描"""
    try:
        if not ul_el:
            return entries
        existing = {e["url"] for e in entries}
        ul_html = str(ul_el)
        # 受限正则：只在该UL源码中匹配锚点
        for m in re.finditer(r'<a\\s+[^>]*href="(\\d+\\.html)"[^>]*>([^<]+)</a>', ul_html, flags=re.IGNORECASE):
            href_rel = m.group(1)
            title_text = _normalize_title(_clean_text(m.group(2)))
            url_abs = urljoin(base_url, href_rel).split('#')[0].split('?')[0]
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

    # 仅按页面抓取顺序返回，避免标题中的异常数字导致排序错乱
    for i, e in enumerate(final, start=1):
        e["index"] = i
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
    soup = BeautifulSoup(html, "lxml")
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


def extract_book_title_from_html(html):
    """
    从HTML中提取书籍标题

    参数:
        html: 书籍页面的HTML内容

    返回:
        str: 提取的书籍标题，如果无法提取则返回空字符串
    """
    try:
        soup = BeautifulSoup(html, "lxml")
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
    "ChapterFetchThread"
]