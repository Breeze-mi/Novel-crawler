import sys
import json
import re
from pathlib import Path

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QListWidget, QListWidgetItem, QTextBrowser, QPushButton, QLabel,
    QLineEdit, QMessageBox, QSpinBox, QCheckBox,
    QInputDialog, QToolBar, QStatusBar
)
from PySide6.QtGui import QFont, QAction
from PySide6.QtCore import Qt, QTimer, Signal, QThread
import time
import shutil

from analysis_index import (
    fetch_html, 
    extract_chapter_list_from_index_precise_fixed,
    extract_title_and_content_from_chapter,
    load_json,
    save_json,
    extract_book_title_from_html,
    process_chapter_content_for_display,
    ChapterFetchThread
)
# 导入样式
from styles import DARK_STYLE, LIGHT_STYLE

# 目录获取线程：异步请求目录页与解析，避免阻塞UI
class IndexFetchThread(QThread):
    finished = Signal(list, str)  # chapters, error
    progress = Signal(str)

    def __init__(self, url):
        super().__init__()
        self.url = url

    def run(self):
        try:
            self.progress.emit("请求目录页…")
            html = fetch_html(self.url)
            self.progress.emit("解析目录…")
            chapters = extract_chapter_list_from_index_precise_fixed(html, self.url)
            self.finished.emit(chapters, "")
        except Exception as e:
            self.finished.emit([], str(e))


if getattr(sys, 'frozen', False):
    # Running in a PyInstaller bundle
    SCRIPT_DIR = Path(sys.executable).parent
else:
    # Running in a normal Python environment
    try:
        SCRIPT_DIR = Path(__file__).resolve().parent
    except NameError:
        SCRIPT_DIR = Path.cwd()

APP_DIR = SCRIPT_DIR / ".pyside_novel_reader_reader_fixed"  # 应用数据目录

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

library = load_json(LIB_FILE, {})
settings = load_json(SETTINGS_FILE, DEFAULT_SETTINGS.copy())

# 自定义文本浏览器，支持手势翻页
class GestureTextBrowser(QTextBrowser):
    """自定义文本浏览器，支持手势翻页"""
    prev_chapter_requested = Signal()
    next_chapter_requested = Signal()
    
    def __init__(self, parent=None):
        super().__init__(parent)
        # 分离上下翻页阈值与对齐保护参数
        self.prev_threshold = 340   # 顶部触发上一章更不敏感，避免误翻
        self.next_threshold = 120   # 底部触发下一章更灵敏
        self.small_scroll_ignore = 66  # 边缘小幅滚动直接消费，用于对齐保护
        self.top_enter_time = 0     # 进入顶部的时间戳(ms)
        self.bottom_enter_time = 0  # 进入底部的时间戳(ms)
        self.accumulated_scroll = 0  # 累积滚轮值
        self.last_gesture_time = 0   # 记录上一次手势触发时间
        self.gesture_cooldown = 700  # 冷却时间(毫秒)，稳定翻页
        
    def wheelEvent(self, event):
        try:
            sb = self.verticalScrollBar()
            minv = sb.minimum()
            maxv = sb.maximum()
            val = sb.value()
            edge_tol = 2  # 边缘容差，避免像素误差导致判定不稳
            at_top = val <= (minv + edge_tol)
            at_bottom = val >= (maxv - edge_tol)

            delta = event.angleDelta().y()
            now_ms = time.monotonic() * 1000

            # 进入边缘时记录时间，用于滞后判定
            if at_top:
                if self.top_enter_time == 0:
                    self.top_enter_time = now_ms
            else:
                self.top_enter_time = 0

            if at_bottom:
                if self.bottom_enter_time == 0:
                    self.bottom_enter_time = now_ms
            else:
                self.bottom_enter_time = 0

            # 冷却期内允许正常滚动
            if now_ms - self.last_gesture_time < self.gesture_cooldown:
                super().wheelEvent(event)
                return

            # 方向变化时重置累积
            if (self.accumulated_scroll > 0 and delta < 0) or (self.accumulated_scroll < 0 and delta > 0):
                self.accumulated_scroll = 0

            # 顶部向上：上一章（增加滞后与小幅对齐保护）
            if at_top and delta > 0:
                # 小幅滚动用于对齐，直接消费不累积，避免误触发上一章
                if delta < self.small_scroll_ignore or (self.top_enter_time and (now_ms - self.top_enter_time) < 250):
                    event.accept()
                    return
                self.accumulated_scroll += delta
                if self.accumulated_scroll >= self.prev_threshold:
                    self.prev_chapter_requested.emit()
                    self.accumulated_scroll = 0
                    self.last_gesture_time = now_ms
                    event.accept()
                    return
                else:
                    # 边缘对齐保护
                    event.accept()
                    return

            # 底部向下：下一章（更灵敏）
            if at_bottom and delta < 0:
                if abs(delta) < self.small_scroll_ignore or (self.bottom_enter_time and (now_ms - self.bottom_enter_time) < 120):
                    event.accept()
                    return
                self.accumulated_scroll += abs(delta)
                if self.accumulated_scroll >= self.next_threshold:
                    self.next_chapter_requested.emit()
                    self.accumulated_scroll = 0
                    self.last_gesture_time = now_ms
                    event.accept()
                    return
                else:
                    event.accept()
                    return

            # 非边缘正常滚动
            self.accumulated_scroll = 0
            super().wheelEvent(event)
        except Exception:
            super().wheelEvent(event)



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
        self.index_thread = None
        self.progress_dialog = None
<<<<<<< HEAD
=======
        self.progress_dialog = None
>>>>>>> 1cafbfb78d1a6c801ca1fffdf0ef90e52360f154

        root = QWidget()
        self.setCentralWidget(root)
        h = QHBoxLayout(root)

        # left UI - 优化紧凑布局
        left_col = QVBoxLayout()
        left_col.setSpacing(8)  # 减少间距
        
        # 书籍选择区域
        self.book_select = QListWidget()
        self.book_select.setUniformItemSizes(True)
        self.book_select.setMaximumWidth(280)  # 减少宽度
        self.book_select.setMaximumHeight(120)  # 限制高度
        self.book_select.itemActivated.connect(self.on_book_selected)
        left_col.addWidget(self.book_select)
        
        # 紧凑的按钮布局
        btn_grid = QVBoxLayout()
        btn_grid.setSpacing(4)  # 减少按钮间距
        
        self.import_btn = QPushButton("导入书籍")  # 简化文字
        self.import_btn.clicked.connect(self.import_book_dialog_async)
        self.import_btn.setMaximumHeight(32)  # 限制按钮高度
        btn_grid.addWidget(self.import_btn)
        
        # 水平排列刷新和删除按钮
        btn_row = QHBoxLayout()
        btn_row.setSpacing(4)
        self.refresh_btn = QPushButton("刷新")
        self.refresh_btn.clicked.connect(self.refresh_current_book_index_async)
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
        self.chapter_list.setUniformItemSizes(True)
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
        h.addLayout(right_col, 8)  
        # timers
        self.save_timer = QTimer(self)
        self.save_timer.setInterval(3000)
        self.save_timer.timeout.connect(self._auto_save)
        self.save_timer.start()

        tb = QToolBar("工具")
        self.addToolBar(tb)
        act = QAction("导入书籍", self)
        act.triggered.connect(self.import_book_dialog_async)
        tb.addAction(act)
        self.refresh_book_select_list()
        self.apply_night_mode(self.night_cb.isChecked())
        
    def closeEvent(self, event):
        """程序关闭时清理资源"""
        if self.fetch_thread and self.fetch_thread.isRunning():
            self.fetch_thread.terminate()
            self.fetch_thread.wait()
        event.accept()



    # UI / business methods (behaviour unchanged; where parsing occurs we call component)
    def refresh_book_select_list(self):
        self.book_select.setUpdatesEnabled(False)
        self.book_select.clear()
        for bid, meta in self.library.items():
            t = meta.get("title") or meta.get("index_url") or bid
            item = QListWidgetItem(t)
            item.setData(Qt.UserRole, bid)
            self.book_select.addItem(item)
        self.book_select.setUpdatesEnabled(True)

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
            soup_title = extract_book_title_from_html(html)
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
            QMessageBox.information(self, "导入成功", f"已导入书籍：{meta['title']}（共 {len(chapters)} 章）（debug 文件生成于脚本目录）")
        except Exception as e:
            QMessageBox.warning(self, "导入失败", f"请求或解析失败：{e}")

    def import_book_dialog_async(self):
        url, ok = QInputDialog.getText(self, "导入书籍（输入书籍首页 URL）", "书籍首页 URL:")
        if not ok or not url.strip():
            return
        url = url.strip()
        ok2 = QMessageBox.question(self, "版权提醒", "请确保你抓取内容仅用于个人学习/备份。继续导入？")
        if ok2 != QMessageBox.StandardButton.Yes:
            return
        # 异步导入，避免阻塞UI
        if self.index_thread and self.index_thread.isRunning():
            QMessageBox.information(self, "提示", "目录正在导入/刷新，请稍候")
            return
        self.index_thread = IndexFetchThread(url)
        self.import_btn.setEnabled(False)
        self.refresh_btn.setEnabled(False)
        self.index_thread.progress.connect(lambda s: self.status.showMessage(s, 3000))
        self.index_thread.finished.connect(lambda chapters, error: self._on_index_fetched_import(url, chapters, error))
        # 显示导入进度弹窗
        try:
            from PySide6.QtWidgets import QProgressDialog
            self.progress_dialog = QProgressDialog("正在导入目录…", None, 0, 0, self)
            self.progress_dialog.setWindowTitle("正在导入")
            self.progress_dialog.setWindowModality(Qt.WindowModality.WindowModal)
            self.progress_dialog.setCancelButton(None)
            self.progress_dialog.setAutoClose(False)
            self.progress_dialog.setAutoReset(False)
            self.progress_dialog.show()
        except Exception:
            pass
        self.index_thread.start()

    def _on_index_fetched_import(self, url, chapters, error):
        # 恢复按钮
        self.import_btn.setEnabled(True)
        self.refresh_btn.setEnabled(True)
        # 关闭进度弹窗
        if getattr(self, "progress_dialog", None):
            try:
                self.progress_dialog.close()
            except Exception:
                pass
            self.progress_dialog = None
        if error:
            QMessageBox.warning(self, "导入失败", f"请求或解析失败：{error}")
            return
        if not chapters:
            QMessageBox.warning(self, "导入失败", "未解析到章节列表，请检查 URL 是否为书籍目录页。")
            return
        try:
            bid = str(abs(hash(url)))
            # 获取标题
            try:
                html_title = fetch_html(url)
                soup_title = extract_book_title_from_html(html_title)
            except Exception:
                soup_title = ""
            meta = {
                "title": soup_title or f"在线书 {bid}",
                "index_url": url,
                "chapters": chapters,
                "book_dir": str(APP_DIR / f"book_{bid}"),
                "chapter_index": 0
            }
            bdir = Path(meta["book_dir"])
            (bdir / "chapters").mkdir(parents=True, exist_ok=True)
            try:
                debug_path = bdir / "index_debug.json"
                debug_path.write_text(json.dumps(chapters, ensure_ascii=False, indent=2), encoding="utf-8")
            except Exception:
                pass
            self.library[bid] = meta
            save_json(LIB_FILE, self.library)
            self.refresh_book_select_list()
            QMessageBox.information(self, "导入成功", f"已导入书籍：{meta['title']}（共 {len(chapters)} 章）（debug 文件生成于脚本目录）")
        except Exception as e:
            QMessageBox.warning(self, "导入失败", f"处理数据失败：{e}")

    def refresh_current_book_index_async(self):
        if not self.current_book_id:
            QMessageBox.information(self, "提示", "请先选中一本书")
            return
        meta = self.library[self.current_book_id]
        url = meta.get("index_url")
        if not url:
            QMessageBox.warning(self, "错误", "未记录书籍目录 URL")
            return
        # 异步刷新，避免阻塞UI
        if self.index_thread and self.index_thread.isRunning():
            QMessageBox.information(self, "提示", "目录正在导入/刷新，请稍候")
            return
        self.index_thread = IndexFetchThread(url)
        self.refresh_btn.setEnabled(False)
        self.import_btn.setEnabled(False)
        self.index_thread.progress.connect(lambda s: self.status.showMessage(s, 3000))
        self.index_thread.finished.connect(lambda chapters, error: self._on_index_fetched_refresh(chapters, error))
        # 显示刷新进度弹窗
        try:
            from PySide6.QtWidgets import QProgressDialog
            self.progress_dialog = QProgressDialog("正在刷新目录…", None, 0, 0, self)
            self.progress_dialog.setWindowTitle("正在刷新")
            self.progress_dialog.setWindowModality(Qt.WindowModality.WindowModal)
            self.progress_dialog.setCancelButton(None)
            self.progress_dialog.setAutoClose(False)
            self.progress_dialog.setAutoReset(False)
            self.progress_dialog.show()
        except Exception:
            pass
        self.index_thread.start()

    def _on_index_fetched_refresh(self, chapters, error):
        # 恢复按钮
        self.refresh_btn.setEnabled(True)
        self.import_btn.setEnabled(True)
        # 关闭进度弹窗
        if getattr(self, "progress_dialog", None):
            try:
                self.progress_dialog.close()
            except Exception:
                pass
            self.progress_dialog = None
        if error:
            QMessageBox.warning(self, "刷新失败", error)
            return
        if not chapters:
            QMessageBox.warning(self, "失败", "未解析到章节")
            return
        meta = self.library[self.current_book_id]
        try:
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
        self.chapter_list.setUpdatesEnabled(False)
        self.chapter_list.clear()
        for ch in self.current_chapters:
            display = f"{ch.get('index', '?')}. {ch.get('title') or ''}"
            it = QListWidgetItem(display)
            it.setData(Qt.UserRole, ch)
            self.chapter_list.addItem(it)
        self.chapter_list.setUpdatesEnabled(True)
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
        
        # 使用analysis_index.py中的函数处理章节内容
        html = process_chapter_content_for_display(
            content,
            self.settings.get("font_family", DEFAULT_SETTINGS["font_family"]),
            self.settings.get("font_size", 22),
            self.settings.get("line_height", 1.6),
            self.settings.get("night_mode", False),
            self.settings.get("text_color", DEFAULT_SETTINGS["text_color"])
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
            # 使用从styles.py导入的夜间模式样式
            self.setStyleSheet(DARK_STYLE)
        else:
            # 使用从styles.py导入的浅色模式样式
            self.setStyleSheet(LIGHT_STYLE)

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
            except Exception as e:
                QMessageBox.warning(self, "删除失败", f"无法删除缓存目录: {str(e)}")
                return

        # 从库中删除书籍
        del self.library[bid]
        save_json(LIB_FILE, self.library)
        
        # 刷新书籍列表
        self.refresh_book_select_list()
        
        # 清空当前显示
        if self.current_book_id == bid:
            self.current_book_id = None
            self.current_chapters = []
            self.current_book_dir = None
            self.chapter_list.clear()
            self.text_browser.clear()
            self.title_label.setText("未打开书")
            self.update_navigation_buttons()
        
        QMessageBox.information(self, "删除成功", "书籍已成功删除")

    def _auto_save(self):
        """自动保存设置和库"""
        try:
            save_json(SETTINGS_FILE, self.settings)
            save_json(LIB_FILE, self.library)
        except Exception:
            pass
def main():
    app = QApplication(sys.argv)
    app.setStyle("Fusion")  # 使用Fusion风格，在所有平台上看起来一致
    window = NovelReaderSidebarFixed()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()