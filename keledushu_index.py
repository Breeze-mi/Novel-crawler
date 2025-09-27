'''
 # keledushu_index.py
 # 组件：负责从 keledushu 以及笔趣阁风格的书籍详情页获取并解析出“全部章节”目录
 # 版权所有：2025 Breeze-mi
 # 日期：2025/09/27
'''

import re  
import time  
from urllib.parse import urljoin, urlparse  
  
try:  
    import requests  
    from bs4 import BeautifulSoup  
except Exception as e:  
    # 在使用组件前请确保安装 requests 和 beautifulsoup4  
    raise RuntimeError("请先安装 requests 和 beautifulsoup4: pip install requests beautifulsoup4 lxml") from e  
  
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
  
def _is_chapter_href(href: str) -> bool:  
    if not href:  
        return False  
    href = href.strip()  
    if href.lower().startswith("javascript:") or href.startswith("#"):  
        return False  
    return href.lower().endswith(".html")  
  
def _parse_chapnum(t: str, u: str):  
    if t:  
        m = re.search(r'第\s*([0-9０-９]+)\s*章', t)  
        if m:  
            s = m.group(1)  
            s2 = ''.join(chr(ord(ch) - 65248) if '０' <= ch <= '９' else ch for ch in s)  
            try:  
                return int(s2)  
            except:  
                pass  
    m2 = re.search(r'(\d+)\.html$', u)  
    if m2:  
        try:  
            return int(m2.group(1))  
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
  
    # 2) fallback: find ul.chapter with nearby '全部章节' or the longest list  
    if not all_chapters_ul:  
        uls = soup.find_all("ul", class_="chapter")  
        candidate = None  
        if uls:  
            for u in uls:  
                parent_text = u.parent.get_text(" ", strip=True) if u.parent else ""  
                if re.search(r'全部章节|全部章|全部目录', parent_text):  
                    candidate = u  
                    break  
                ok = False  
                for sib in u.previous_siblings:  
                    text = ""  
                    if hasattr(sib, "get_text"):  
                        text = sib.get_text(" ", strip=True)  
                    elif isinstance(sib, str):  
                        text = sib.strip()  
                    if text and re.search(r'全部章节|全部章|全部目录', text):  
                        ok = True  
                        break  
                if ok:  
                    candidate = u  
                    break  
            if candidate is None:  
                u_sorted = sorted(uls, key=lambda x: len(x.find_all("li")), reverse=True)  
                if u_sorted and len(u_sorted[0].find_all("li")) >= 5:  
                    candidate = u_sorted[0]  
        all_chapters_ul = candidate  
  
    entries = []  
    if all_chapters_ul:  
        for a in all_chapters_ul.find_all("a", href=True):  
            href_raw = a.get("href", "").strip()  
            if not href_raw:  
                continue  
            href = urljoin(base_url, href_raw).split('#')[0].split('?')[0]  
            if not _is_chapter_href(href):  
                continue  
            title = _clean_text(a.get("title") or a.get("aria-label") or a.get_text(" ", strip=True))  
            if re.search(r'首页|菜单|玄幻|武侠|言情|历史|网游|科幻|恐怖|其他|全本|书架', title):  
                continue  
            entries.append({"title": title or None, "url": href})  
    else:  
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
            title = _clean_text(a.get("title") or a.get("aria-label") or a.get_text(" ", strip=True))  
            parsed = urlparse(href)  
            path = parsed.path or ""  
            if re.search(r'/sort/|/author/|/fullbook/|/mybook|/cover/|/index', path):  
                continue  
            if re.search(r'首页|菜单|玄幻|武侠|言情|历史|网游|科幻|恐怖|其他|全本|书架', title):  
                continue  
            seen.add(href)  
            entries.append({"title": title or None, "url": href})  
  
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
                if current.name == "dt":  
                    break  
                if current.name == "dd":  
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
                                title = _clean_text(a.get("title") or a.get_text(" ", strip=True))  
                                if not re.search(r'首页|菜单|玄幻|武侠|言情|历史|网游|科幻|恐怖|其他|全本|书架', title):  
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
                                title = _clean_text(a.get("title") or a.get_text(" ", strip=True))  
                                if not re.search(r'首页|菜单|玄幻|武侠|言情|历史|网游|科幻|恐怖|其他|全本|书架', title):  
                                    latest_chapters.append({"title": title or None, "url": href})  
      
    # 优先返回正文卷，如果没有正文卷则返回最新章节（但需要反转顺序）  
    if main_chapters:
        return main_chapters
    elif latest_chapters:
        # 最新章节通常是倒序的，需要反转
        return list(reversed(latest_chapters))  
      
    return []  
  
  
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
        chapnum = _parse_chapnum(e.get("title"), e["url"])  
        title = e.get("title") or (f"第{i}章" if chapnum is None else f"第{chapnum}章")  
        final.append({"index": i, "title": title, "url": e["url"], "chapter_num": chapnum})  
  
    return final  
  
  
# module exports  
__all__ = [  
    "fetch_html",  
    "extract_chapter_list_from_index_precise_fixed",  
]
