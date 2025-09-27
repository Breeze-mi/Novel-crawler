import sys
import json
import re
from pathlib import Path
from urllib.parse import urljoin, urlparse

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QListWidget, QListWidgetItem, QTextBrowser, QPushButton, QLabel,
    QLineEdit, QMessageBox, QSlider, QSpinBox, QCheckBox,
    QInputDialog, QToolBar, QStatusBar
)
from PySide6.QtGui import QFont, QAction, QKeySequence, QShortcut
from PySide6.QtCore import Qt, QTimer, QThread, Signal
import time
import shutil # 导入 shutil 模块

# import parsing component
from keledushu_index import fetch_html, extract_chapter_list_from_index_precise_fixed

# set data dir to script directory (绿化)
try:
    SCRIPT_DIR = Path(__file__).resolve().parent
except NameError:
    SCRIPT_DIR = Path.cwd()
APP_DIR = SCRIPT_DIR / ".pyside_novel_reader_reader_fixed"
APP_DIR.mkdir(parents=True, exist_ok=True)
LIB_FILE = APP_DIR / "library.json"
SETTINGS_FILE = APP_DIR / "settings.json"

DEFAULT_SETTINGS = {
    "font_family": "方正启体简体",
    "font_size": 22,
    "night_mode": False,
    "line_height": 1.6,
    "text_color": "#800000",
    "bg_color": "#D2B48C"
}

def load_json(path: Path, default):
    try:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        pass
    return default

def save_json(path: Path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")

library = load_json(LIB_FILE, {})
settings = load_json(SETTINGS_FILE, DEFAULT_SETTINGS.copy())

# re-use extract_title_and_content_from_chapter from previous final (kept local here)
from bs4 import BeautifulSoup
def extract_title_and_content_from_chapter(html, base_url=None):
    soup = BeautifulSoup(html, "lxml")
    title = ""
    if soup.find("h1"):
        title = soup.find("h1").get_text(strip=True)
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

# 自定义文本浏览器，支持手势翻页
class GestureTextBrowser(QTextBrowser):
    prev_chapter_requested = Signal()
    next_chapter_requested = Signal()
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.scroll_threshold = 120  # 增加滚轮阈值，减少误触发
        self.accumulated_scroll = 0
        self.last_gesture_time = 0
        self.gesture_cooldown = 1000  # 1秒冷却时间，防止连续触发
        
    def wheelEvent(self, event):
        try:
            # 获取滚动条位置
            scrollbar = self.verticalScrollBar()
            at_top = scrollbar.value() == scrollbar.minimum()
            at_bottom = scrollbar.value() == scrollbar.maximum()
            
            # 获取滚轮滚动方向
            delta = event.angleDelta().y()
            
            # 检查冷却时间
            current_time = time.time() * 1000
            if current_time - self.last_gesture_time < self.gesture_cooldown:
                super().wheelEvent(event)
                return
            
            if at_top and delta > 0:
                # 在顶部向上滚动 - 上一章
                self.accumulated_scroll += delta
                if self.accumulated_scroll > self.scroll_threshold:
                    self.prev_chapter_requested.emit()
                    self.accumulated_scroll = 0
                    self.last_gesture_time = current_time
                # 不调用super()，防止滚动
            elif at_bottom and delta < 0:
                # 在底部向下滚动 - 下一章
                self.accumulated_scroll += abs(delta)
                if self.accumulated_scroll > self.scroll_threshold:
                    self.next_chapter_requested.emit()
                    self.accumulated_scroll = 0
                    self.last_gesture_time = current_time
                # 不调用super()，防止滚动
            else:
                # 正常滚动
                self.accumulated_scroll = 0
                super().wheelEvent(event)
        except Exception as e:
            # 发生错误时执行正常滚动
            super().wheelEvent(event)

# Chapter fetch thread (same behavior)
class ChapterFetchThread(QThread):
    finished = Signal(int, dict, str)
    progress = Signal(str)
    def __init__(self, chapter_url, index, cache_dir):
        super().__init__()
        self.chapter_url = chapter_url
        self.index = index
        self.cache_dir = Path(cache_dir)
    def run(self):
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


# GUI main window (kept behavior and UI from previous final)
class NovelReaderSidebarFixed(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("小说阅读器")
        self.resize(1100, 720)
        self.library = library
        self.settings = settings
        self.current_book_id = None
        self.current_chapters = []
        self.current_book_dir = None
        self.fetch_thread = None

        root = QWidget()
        self.setCentralWidget(root)
        h = QHBoxLayout(root)

        # left UI - 优化紧凑布局
        left_col = QVBoxLayout()
        left_col.setSpacing(8)  # 减少间距
        
        # 书籍选择区域
        self.book_select = QListWidget()
        self.book_select.setMaximumWidth(280)  # 减少宽度
        self.book_select.setMaximumHeight(120)  # 限制高度
        self.book_select.itemActivated.connect(self.on_book_selected)
        left_col.addWidget(self.book_select)
        
        # 紧凑的按钮布局
        btn_grid = QVBoxLayout()
        btn_grid.setSpacing(4)  # 减少按钮间距
        
        self.import_btn = QPushButton("导入书籍")  # 简化文字
        self.import_btn.clicked.connect(self.import_book_dialog)
        self.import_btn.setMaximumHeight(32)  # 限制按钮高度
        btn_grid.addWidget(self.import_btn)
        
        # 水平排列刷新和删除按钮
        btn_row = QHBoxLayout()
        btn_row.setSpacing(4)
        self.refresh_btn = QPushButton("刷新")
        self.refresh_btn.clicked.connect(self.refresh_current_book_index)
        self.refresh_btn.setMaximumHeight(32)
        btn_row.addWidget(self.refresh_btn)
        
        self.remove_btn = QPushButton("删除")
        self.remove_btn.clicked.connect(self.remove_selected_book)
        self.remove_btn.setMaximumHeight(32)
        btn_row.addWidget(self.remove_btn)
        
        btn_grid.addLayout(btn_row)
        left_col.addLayout(btn_grid)

        # 搜索区域
        search_row = QHBoxLayout()
        search_row.setSpacing(4)
        self.chapter_search = QLineEdit()
        self.chapter_search.setPlaceholderText("搜索章节")  # 简化提示文字
        self.chapter_search.setMaximumWidth(160) # 限制搜索框宽度
        self.chapter_search.setMaximumHeight(32) # 限制搜索框高度   
        self.search_btn = QPushButton("搜索")  # 简化按钮文字
        self.search_btn.clicked.connect(self.search_chapter)
        self.search_btn.setMaximumHeight(32) # 限制搜索按钮高度
        self.search_btn.setMaximumWidth(60)  # 限制搜索按钮宽度
        search_row.addWidget(self.chapter_search)
        search_row.addWidget(self.search_btn)
        left_col.addLayout(search_row)

        # 章节目录
        self.chapter_label = QLabel("章节目录")  # 简化标签文字
        self.chapter_label.setMaximumHeight(20)
        left_col.addWidget(self.chapter_label)
        self.chapter_list = QListWidget()
        self.chapter_list.itemActivated.connect(self.on_chapter_clicked)
        left_col.addWidget(self.chapter_list, 1)

        h.addLayout(left_col, 2)  

        # right UI
        right_col = QVBoxLayout()
        top_controls = QHBoxLayout()
        self.title_label = QLabel("未打开书")
        top_controls.addWidget(self.title_label, 1)
        self.font_label = QLabel("字号")
        top_controls.addWidget(self.font_label)
        self.font_spin = QSpinBox()
        self.font_spin.setRange(10, 36)
        self.font_spin.setValue(self.settings.get("font_size", 22))
        self.font_spin.valueChanged.connect(self.change_font_size)
        top_controls.addWidget(self.font_spin)
        self.night_cb = QCheckBox("夜间")
        self.night_cb.setChecked(self.settings.get("night_mode", False))
        self.night_cb.toggled.connect(self.toggle_night_mode)
        top_controls.addWidget(self.night_cb)

        right_col.addLayout(top_controls)

        self.text_browser = GestureTextBrowser()
        self.base_font = QFont(self.settings.get("font_family", "方正启体简体"), self.settings.get("font_size", 22))
        self.text_browser.setFont(self.base_font)
        self.text_browser.setOpenExternalLinks(True)
        
        # 连接手势信号
        self.text_browser.prev_chapter_requested.connect(self.go_to_prev_chapter)
        self.text_browser.next_chapter_requested.connect(self.go_to_next_chapter)
        
        right_col.addWidget(self.text_browser, 10)

        # 添加章节导航按钮
        nav_row = QHBoxLayout()
        self.prev_btn = QPushButton("← 上一章")
        self.prev_btn.clicked.connect(self.go_to_prev_chapter)
        self.prev_btn.setEnabled(False)
        nav_row.addWidget(self.prev_btn)
        
        nav_row.addStretch()
        
        self.chapter_info = QLabel("章节 0/0")
        nav_row.addWidget(self.chapter_info)
        
        nav_row.addStretch()
        
        self.next_btn = QPushButton("下一章 →")
        self.next_btn.clicked.connect(self.go_to_next_chapter)
        self.next_btn.setEnabled(False)
        nav_row.addWidget(self.next_btn)
        
        right_col.addLayout(nav_row)

        self.status = QStatusBar()
        self.setStatusBar(self.status)
        h.addLayout(right_col, 8)  # 从7改为8，增加右侧占用空间

        # timers
        self.save_timer = QTimer(self)
        self.save_timer.setInterval(3000)
        self.save_timer.timeout.connect(self._auto_save)
        self.save_timer.start()

        tb = QToolBar("工具")
        self.addToolBar(tb)
        tb.addAction(QAction("导入书籍", self, triggered=self.import_book_dialog))

        # 添加键盘快捷键
        self.setup_shortcuts()

        self.refresh_book_select_list()
        self.apply_night_mode(self.night_cb.isChecked())

    def closeEvent(self, event):
        """程序关闭时清理资源"""
        if self.fetch_thread and self.fetch_thread.isRunning():
            self.fetch_thread.terminate()
            self.fetch_thread.wait()
        event.accept()

    def setup_shortcuts(self):
        """设置键盘快捷键"""
        # 上一章
        prev_shortcuts = [
            QShortcut(QKeySequence(Qt.Key_Left), self),
            QShortcut(QKeySequence(Qt.Key_PageUp), self),
            QShortcut(QKeySequence("Ctrl+Left"), self)
        ]
        for shortcut in prev_shortcuts:
            shortcut.activated.connect(self.go_to_prev_chapter)
        
        # 下一章
        next_shortcuts = [
            QShortcut(QKeySequence(Qt.Key_Right), self),
            QShortcut(QKeySequence(Qt.Key_PageDown), self),
            QShortcut(QKeySequence("Ctrl+Right"), self)
        ]
        for shortcut in next_shortcuts:
            shortcut.activated.connect(self.go_to_next_chapter)
        
        # 第一章
        first_shortcut = QShortcut(QKeySequence(Qt.Key_Home), self)
        first_shortcut.activated.connect(self.go_to_first_chapter)
        
        # 最后一章
        last_shortcut = QShortcut(QKeySequence(Qt.Key_End), self)
        last_shortcut.activated.connect(self.go_to_last_chapter)

    # UI / business methods (behaviour unchanged; where parsing occurs we call component)
    def refresh_book_select_list(self):
        self.book_select.clear()
        for bid, meta in self.library.items():
            t = meta.get("title") or meta.get("index_url") or bid
            item = QListWidgetItem(t)
            item.setData(Qt.UserRole, bid)
            self.book_select.addItem(item)

    def import_book_dialog(self):
        url, ok = QInputDialog.getText(self, "导入书籍（输入书籍首页 URL）", "书籍首页 URL:")
        if not ok or not url.strip():
            return
        url = url.strip()
        ok2 = QMessageBox.question(self, "版权提醒", "请确保你抓取内容仅用于个人学习/备份。继续导入？")
        if ok2 != QMessageBox.StandardButton.Yes:
            return
        try:
            html = fetch_html(url)
            chapters = extract_chapter_list_from_index_precise_fixed(html, url)
            if not chapters:
                QMessageBox.warning(self, "导入失败", "未解析到章节列表，请检查 URL 是否为书籍目录页。")
                return
            bid = str(abs(hash(url)))
            soup_title = ""
            try:
                bs = BeautifulSoup(html, "lxml")
                if bs.title and bs.title.string:
                    soup_title = bs.title.string.strip().split("-")[0].strip()
            except Exception:
                pass
            meta = {
                "title": soup_title or f"在线书 {bid}",
                "index_url": url,
                "chapters": chapters,
                "book_dir": str(APP_DIR / f"book_{bid}"),
                "chapter_index": 0
            }
            bdir = Path(meta["book_dir"])
            (bdir / "chapters").mkdir(parents=True, exist_ok=True)
            # debug file
            try:
                debug_path = bdir / "index_debug.json"
                debug_path.write_text(json.dumps(chapters, ensure_ascii=False, indent=2), encoding="utf-8")
            except Exception:
                pass
            self.library[bid] = meta
            save_json(LIB_FILE, self.library)
            self.refresh_book_select_list()
            QMessageBox.information(self, "导入成功", f"已导入书籍：{meta['title']}（共 {len(chapters)} 章）\n（debug 文件生成于脚本目录）")
        except Exception as e:
            QMessageBox.warning(self, "导入失败", f"请求或解析失败：{e}")

    def on_book_selected(self, item):
        bid = item.data(Qt.UserRole)
        self.open_book(bid)

    def open_book(self, bid):
        if bid not in self.library: return
        self.current_book_id = bid
        meta = self.library[bid]
        self.title_label.setText(meta.get("title", "未命名书"))
        self.current_chapters = meta.get("chapters", [])
        self.current_book_dir = Path(meta.get("book_dir"))
        self.chapter_list.clear()
        for ch in self.current_chapters:
            display = f"{ch.get('index', '?')}. {ch.get('title') or ''}"
            it = QListWidgetItem(display)
            it.setData(Qt.UserRole, ch)
            self.chapter_list.addItem(it)
        self.text_browser.clear()
        self.text_browser.setHtml("<i>点击左侧章节条目以加载并查看该章节内容（按需抓取并缓存）。</i>")
        self.update_navigation_buttons()

    def refresh_current_book_index(self):
        if not self.current_book_id:
            QMessageBox.information(self, "提示", "请先选中一本书")
            return
        meta = self.library[self.current_book_id]
        url = meta.get("index_url")
        if not url:
            QMessageBox.warning(self, "错误", "未记录书籍目录 URL")
            return
        try:
            html = fetch_html(url)
            chapters = extract_chapter_list_from_index_precise_fixed(html, url)
            if not chapters:
                QMessageBox.warning(self, "失败", "未解析到章节")
                return
            meta["chapters"] = chapters
            meta["chapter_index"] = 0
            save_json(LIB_FILE, self.library)
            try:
                bdir = Path(meta["book_dir"])
                debug_path = bdir / "index_debug.json"
                debug_path.write_text(json.dumps(chapters, ensure_ascii=False, indent=2), encoding="utf-8")
            except Exception:
                pass
            self.open_book(self.current_book_id)
            QMessageBox.information(self, "完成", f"目录已刷新，共 {len(chapters)} 章（并更新 debug 文件）")
        except Exception as e:
            QMessageBox.warning(self, "刷新失败", str(e))

    def search_chapter(self):
        q = self.chapter_search.text().strip()
        if not q: return
        try:
            n = int(q)
            for i in range(self.chapter_list.count()):
                it = self.chapter_list.item(i)
                ch = it.data(Qt.UserRole)
                if ch.get("index") == n:
                    self.chapter_list.setCurrentItem(it)
                    self.chapter_list.scrollToItem(it)
                    return
            QMessageBox.information(self, "未找到", f"未找到第 {n} 章")
            return
        except Exception:
            pass
        matches = []
        for i in range(self.chapter_list.count()):
            it = self.chapter_list.item(i)
            if q in it.text():
                matches.append(it)
        if not matches:
            QMessageBox.information(self, "未找到", "未找到匹配章节")
            return
        self.chapter_list.setCurrentItem(matches[0])
        self.chapter_list.scrollToItem(matches[0])

    def on_chapter_clicked(self, item: QListWidgetItem):
        ch = item.data(Qt.UserRole)
        self.load_chapter_content(ch)

    def load_chapter_content(self, chapter_data):
        """加载章节内容的通用方法"""
        # 停止之前的线程
        if self.fetch_thread and self.fetch_thread.isRunning():
            self.fetch_thread.terminate()
            self.fetch_thread.wait()
        
        idx = chapter_data.get("index")
        url = chapter_data.get("url")
        if not url or not re.search(r'\.html$', url):
            for c in self.current_chapters:
                if c.get("index") == idx:
                    url = c.get("url")
                    break
        
        if not self.current_book_dir:
            return
            
        cache_dir = Path(self.current_book_dir) / "chapters"
        self.fetch_thread = ChapterFetchThread(url, idx, cache_dir)
        self.fetch_thread.progress.connect(lambda s: self.status.showMessage(s, 5000))
        self.fetch_thread.finished.connect(self.on_chapter_fetched)
        self.fetch_thread.start()

    def on_chapter_fetched(self, index, data, error):
        if error:
            QMessageBox.warning(self, "抓取失败", f"第 {index} 章抓取失败：{error}")
            return
        title = data.get("title") or f"第{index}章"
        content = data.get("content") or ""
        self.title_label.setText(f"{self.library[self.current_book_id].get('title','')} — {title}")
        
        # 根据夜间模式调整文字颜色
        text_color = self.settings.get("text_color", DEFAULT_SETTINGS["text_color"])
        if self.settings.get("night_mode", False):
            text_color = "#d0d0d0"  # 夜间模式使用柔和的浅色文字
        
        html = "<div style='white-space:pre-wrap;font-family:%s;font-size:%dpt;line-height:%.2f;color:%s;padding:20px;'>%s</div>" % (
            self.settings.get("font_family", DEFAULT_SETTINGS["font_family"]),
            self.settings.get("font_size", 22),
            self.settings.get("line_height", 1.6),
            text_color,
            (content.replace("&","&amp;").replace("<","&lt;").replace(">","&gt;").replace("\n","<br>"))
        )
        self.text_browser.setHtml(html)
        self.library[self.current_book_id]["chapter_index"] = index - 1
        save_json(LIB_FILE, self.library)
        self.status.showMessage(f"已加载第 {index} 章", 4000)
        self.update_navigation_buttons()

    def update_navigation_buttons(self):
        """更新导航按钮状态和章节信息"""
        if not self.current_book_id or not self.current_chapters:
            self.prev_btn.setEnabled(False)
            self.next_btn.setEnabled(False)
            self.chapter_info.setText("章节 0/0")
            return
        
        current_index = self.library[self.current_book_id].get("chapter_index", 0)
        total_chapters = len(self.current_chapters)
        
        # 更新按钮状态
        self.prev_btn.setEnabled(current_index > 0)
        self.next_btn.setEnabled(current_index < total_chapters - 1)
        
        # 更新章节信息
        self.chapter_info.setText(f"章节 {current_index + 1}/{total_chapters}")

    def get_current_chapter_index(self):
        """获取当前章节在列表中的索引"""
        if not self.current_book_id:
            return -1
        return self.library[self.current_book_id].get("chapter_index", 0)

    def load_chapter_by_index(self, chapter_index):
        """根据索引加载章节"""
        if not self.current_chapters or chapter_index < 0 or chapter_index >= len(self.current_chapters):
            return
        
        chapter = self.current_chapters[chapter_index]
        
        # 更新章节列表选中状态
        for i in range(self.chapter_list.count()):
            item = self.chapter_list.item(i)
            ch = item.data(Qt.UserRole)
            if ch.get("index") == chapter.get("index"):
                self.chapter_list.setCurrentItem(item)
                self.chapter_list.scrollToItem(item)
                break
        
        # 加载章节内容
        self.on_chapter_clicked_by_data(chapter)

    def on_chapter_clicked_by_data(self, chapter_data):
        """通过章节数据加载章节（不依赖UI项目）"""
        self.load_chapter_content(chapter_data)

    def go_to_prev_chapter(self):
        """跳转到上一章"""
        try:
            if not self.current_chapters or not self.current_book_id:
                return
            current_index = self.get_current_chapter_index()
            if current_index > 0:
                self.load_chapter_by_index(current_index - 1)
                self.status.showMessage("已切换到上一章", 2000)
        except Exception as e:
            self.status.showMessage(f"切换章节失败: {str(e)}", 3000)

    def go_to_next_chapter(self):
        """跳转到下一章"""
        try:
            if not self.current_chapters or not self.current_book_id:
                return
            current_index = self.get_current_chapter_index()
            if current_index < len(self.current_chapters) - 1:
                self.load_chapter_by_index(current_index + 1)
                self.status.showMessage("已切换到下一章", 2000)
        except Exception as e:
            self.status.showMessage(f"切换章节失败: {str(e)}", 3000)

    def go_to_first_chapter(self):
        """跳转到第一章"""
        try:
            if self.current_chapters:
                self.load_chapter_by_index(0)
                self.status.showMessage("已跳转到第一章", 2000)
        except Exception as e:
            self.status.showMessage(f"跳转章节失败: {str(e)}", 3000)

    def go_to_last_chapter(self):
        """跳转到最后一章"""
        try:
            if self.current_chapters:
                self.load_chapter_by_index(len(self.current_chapters) - 1)
                self.status.showMessage("已跳转到最后一章", 2000)
        except Exception as e:
            self.status.showMessage(f"跳转章节失败: {str(e)}", 3000)

    def change_font_size(self, v):
        self.settings["font_size"] = v
        save_json(SETTINGS_FILE, self.settings)
        self.base_font.setPointSize(v)
        self.text_browser.setFont(self.base_font)
        # 重新渲染当前内容
        if self.text_browser.toHtml():
            current_html = self.text_browser.toHtml()
            self.text_browser.setHtml(current_html)

    def toggle_night_mode(self, on):
        self.settings["night_mode"] = on
        save_json(SETTINGS_FILE, self.settings)
        self.apply_night_mode(on)

    def apply_night_mode(self, on):
        if on:
            # MD3 夜间模式样式 - 低对比度护眼设计
            dark_style = """
            QMainWindow {
                background-color: #1a1a1a;
                color: #d0d0d0;
            }
            QWidget {
                background-color: #1a1a1a;
                color: #d0d0d0;
            }
            QListWidget {
                background-color: #2a2a2a;
                color: #d0d0d0;
                border: 1px solid #404040;
                border-radius: 12px;
                selection-background-color: #4a4a4a;
            }
            QListWidget::item {
                padding: 8px 12px;
                border-bottom: 1px solid #353535;
            }
            QListWidget::item:hover {
                background-color: #353535;
            }
            QListWidget::item:selected {
                background-color: #4a4a4a;
            }
            QPushButton {
                background-color: #4a4a4a;
                color: #d0d0d0;
                border: none;
                border-radius: 12px;
                padding: 8px 16px;
                font-weight: 500;
                font-size: 13px;
            }
            QPushButton:hover {
                background-color: #5a5a5a;
            }
            QPushButton:pressed {
                background-color: #3a3a3a;
            }
            QPushButton:disabled {
                background-color: #2a2a2a;
                color: #666666;
            }
            QLineEdit {
                background-color: #2a2a2a;
                color: #d0d0d0;
                border: 2px solid #404040;
                border-radius: 8px;
                padding: 6px 10px;
                font-size: 13px;
            }
            QLineEdit:focus {
                border-color: #6a6a6a;
            }
            QLabel {
                color: #d0d0d0;
            }
            QSpinBox {
                background-color: #2a2a2a;
                color: #d0d0d0;
                border: 2px solid #404040;
                border-radius: 8px;
                padding: 8px;
            }
            QCheckBox {
                color: #d0d0d0;
            }
            QCheckBox::indicator {
                width: 20px;
                height: 20px;
            }
            QCheckBox::indicator:unchecked {
                background-color: #2a2a2a;
                border: 2px solid #404040;
                border-radius: 6px;
            }
            QCheckBox::indicator:checked {
                background-color: #5a5a5a;
                border: 2px solid #5a5a5a;
                border-radius: 6px;
            }
            QTextBrowser {
                background-color: #222222;
                color: #d0d0d0;
                border: 1px solid #404040;
                border-radius: 12px;
                padding: 20px;
            }
            QStatusBar {
                background-color: #2a2a2a;
                color: #d0d0d0;
                border-top: 1px solid #404040;
            }
            QToolBar {
                background-color: #2a2a2a;
                border: none;
                spacing: 3px;
            }
            """
            self.setStyleSheet(dark_style)
        else:
            # MD3 浅色模式 - 护眼的浅棕色主题
            light_style = """
            QMainWindow {
                background-color: #D2B48C;
                color: #5D4E37;
            }
            QWidget {
                background-color: #D2B48C;
                color: #5D4E37;
            }
            QListWidget {
                background-color: #E6D3A3;
                color: #5D4E37;
                border: 1px solid #C19A6B;
                border-radius: 12px;
                selection-background-color: #DEB887;
            }
            QListWidget::item {
                padding: 8px 12px;
                border-bottom: 1px solid #C19A6B;
            }
            QListWidget::item:hover {
                background-color: #DEB887;
            }
            QListWidget::item:selected {
                background-color: #CD853F;
                color: #FFFFFF;
            }
            QPushButton {
                background-color: #CD853F;
                color: #FFFFFF;
                border: none;
                border-radius: 12px;
                padding: 8px 16px;
                font-weight: 500;
                font-size: 13px;
            }
            QPushButton:hover {
                background-color: #D2691E;
            }
            QPushButton:pressed {
                background-color: #A0522D;
            }
            QPushButton:disabled {
                background-color: #E6D3A3;
                color: #999999;
            }
            QLineEdit {
                background-color: #F5E6D3;
                color: #5D4E37;
                border: 2px solid #C19A6B;
                border-radius: 12px;
                padding: 6px 10px;
                font-size: 13px;
            }
            QLineEdit:focus {
                border-color: #CD853F;
            }
            QLabel {
                color: #5D4E37;
                font-weight: 500;
            }
            QSpinBox {
                background-color: #F5E6D3;
                color: #5D4E37;
                border: 2px solid #C19A6B;
                border-radius: 8px;
                padding: 8px;
            }
            QCheckBox {
                color: #5D4E37;
                font-weight: 500;
            }
            QCheckBox::indicator {
                width: 20px;
                height: 20px;
            }
            QCheckBox::indicator:unchecked {
                background-color: #F5E6D3;
                border: 2px solid #C19A6B;
                border-radius: 6px;
            }
            QCheckBox::indicator:checked {
                background-color: #CD853F;
                border: 2px solid #CD853F;
                border-radius: 6px;
            }
            QTextBrowser {
                background-color: #F5E6D3;
                color: #800000;
                border: 1px solid #C19A6B;
                border-radius: 12px;
                padding: 20px;
            }
            QStatusBar {
                background-color: #E6D3A3;
                color: #5D4E37;
                border-top: 1px solid #C19A6B;
            }
            QToolBar {
                background-color: #E6D3A3;
                border: none;
                spacing: 3px;
            }
            """
            self.setStyleSheet(light_style)

    def remove_selected_book(self):
        current_item = self.book_select.currentItem()
        if not current_item:
            QMessageBox.information(self, "提示", "请先选中要删除的书籍")
            return
        
        bid = current_item.data(Qt.UserRole)
        meta = self.library.get(bid)
        if not meta:
            QMessageBox.warning(self, "错误", "未找到书籍元数据")
            return

        reply = QMessageBox.question(self, "确认删除", f"确定要删除书籍 '{meta.get('title', '未知书籍')}' 及其所有缓存文件吗？",
                                     QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if reply == QMessageBox.StandardButton.No:
            return

        # 删除书籍缓存目录
        book_dir_path = Path(meta.get("book_dir"))
        if book_dir_path.exists() and book_dir_path.is_dir():
            try:
                shutil.rmtree(book_dir_path)
                print(f"已删除书籍缓存目录: {book_dir_path}")
            except Exception as e:
                QMessageBox.warning(self, "删除失败", f"无法删除书籍缓存目录 {book_dir_path}: {e}")
                return

        # 从 library 中删除书籍
        if bid in self.library:
            del self.library[bid]
            save_json(LIB_FILE, self.library)
            self.refresh_book_select_list()
            self.text_browser.clear()
            self.title_label.setText("未打开书")
            self.chapter_list.clear()
            self.current_book_id = None
            self.current_chapters = []
            self.current_book_dir = None
            self.update_navigation_buttons()
            QMessageBox.information(self, "删除成功", f"书籍 '{meta.get('title', '未知书籍')}' 及其缓存已删除。")
        else:
            QMessageBox.warning(self, "错误", "书籍已不存在于库中。")
        self.status.showMessage("书已移除", 2000)

    def _auto_save(self):
        save_json(SETTINGS_FILE, self.settings)
        save_json(LIB_FILE, self.library)


# app entry
def main():
    app = QApplication(sys.argv)
    win = NovelReaderSidebarFixed()
    win.show()
    sys.exit(app.exec())

if __name__ == "__main__":
    main()