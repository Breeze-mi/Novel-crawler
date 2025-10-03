__version__ = "1.0.1"
import sys

import re
import time
import shutil
import logging
from pathlib import Path

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QListWidget, QListWidgetItem, QTextBrowser, QPushButton, QLabel,
    QLineEdit, QMessageBox, QSpinBox, QCheckBox,
    QInputDialog, QToolBar, QStatusBar, QProgressDialog
)
from PySide6.QtGui import QFont, QAction, QTextOption
from PySide6.QtCore import Qt, QTimer, Signal
# 可选引入：WebEngine 用于真·直排（writing-mode）
try:
    from PySide6.QtWebEngineWidgets import QWebEngineView
    WEBENGINE_AVAILABLE = True
except Exception:
    WEBENGINE_AVAILABLE = False
from runlog import setup_app_logger
from analysis_index import (
    fetch_html, 
    load_json,
    save_json,
    extract_book_title_from_html,
    process_chapter_content_for_display,
    create_book_directory_and_debug,

    create_book_metadata,
    IndexFetchThread,
    ChapterFetchThread
)
# 导入样式
from styles import DARK_STYLE, LIGHT_STYLE, wrap_vertical_html


if getattr(sys, 'frozen', False):
    # Running in a PyInstaller bundle
    SCRIPT_DIR = Path(sys.executable).parent
else:
    # Running in a normal Python environment
    try:
        SCRIPT_DIR = Path(__file__).resolve().parent
    except NameError:
        SCRIPT_DIR = Path.cwd()

APP_DIR = SCRIPT_DIR / "data"  # 应用数据目录

APP_DIR.mkdir(parents=True, exist_ok=True)
BOOKS_DIR = APP_DIR / "books"
BOOKS_DIR.mkdir(parents=True, exist_ok=True)

LIB_FILE = APP_DIR / "library.json"
SETTINGS_FILE = APP_DIR / "settings.json"

setup_app_logger(str(APP_DIR / "app.log") ,add_console=True) #是否开启控制台日志输出
logging.info("应用启动")
# English: Application started
# logging.info("Application started")

DEFAULT_SETTINGS = {
    "font_family": "方正启体简体",
    "font_size": 22,
    "night_mode": False,
    "line_height": 1.6,
    "text_color": "#800000",
    "bg_color": "#D2B48C",
    "vertical_mode": False
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
        self.prev_threshold = 1000   # 顶部触发上一章更不敏感，避免误翻
        self.next_threshold = 120   # 底部触发下一章更灵敏
        self.small_scroll_ignore = 90  # 边缘小幅滚动直接消费，用于对齐保护
        self.top_enter_time = 0     # 进入顶部的时间戳(ms)
        self.bottom_enter_time = 0  # 进入底部的时间戳(ms)
        self.accumulated_scroll = 0  # 累积滚轮值
        self.last_gesture_time = 0   # 记录上一次手势触发时间
        self.gesture_cooldown = 800  # 冷却时间(毫秒)，稳定翻页
        
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

# 直排专用 Web 视图：将鼠标滚轮纵向滚动转换为横向滚动，符合 vertical-rl 的阅读习惯
if 'WEBENGINE_AVAILABLE' in globals() and WEBENGINE_AVAILABLE:
    class VerticalWebView(QWebEngineView):
        # 在竖排中使用滚轮切章所需的信号
        prev_chapter_requested = Signal()
        next_chapter_requested = Signal()

        def __init__(self, parent=None):
            super().__init__(parent)
            # 滚轮切章的冷却控制，避免误触发
            self._gesture_cooldown_ms = 800
            self._last_gesture_ts = 0
            # 滚轮计数阈值：上一章需 6 次、下一章需 4 次
            self._prev_ticks_needed = 6
            self._next_ticks_needed = 4
            self._prev_tick_counter = 0
            self._next_tick_counter = 0

        def wheelEvent(self, event):
            try:
                # 将纵向滚轮映射为水平滚动：向上滚轮 => 向右滚动（上一列），向下滚轮 => 向左滚动（下一列）
                delta_y = event.angleDelta().y()
                step = int(delta_y * 0.6)  # 已修正方向：下(负) -> 向左；上(正) -> 向右
                # 先执行滚动
                self.page().runJavaScript(f"window.scrollBy({{left: {step}, top: 0, behavior: 'auto'}});")

                # 边缘检测 + 冷却判断（异步读取滚动位置）
                import time as _t
                now_ms = int(_t.monotonic() * 1000)
                cooldown_active = (now_ms - self._last_gesture_ts) < self._gesture_cooldown_ms

                def _edge_check_cb(res):
                    # res 为 JSON 字符串，包含 x(滚动X), w(scrollWidth), cw(clientWidth)
                    try:
                        import json
                        data = json.loads(res) if isinstance(res, str) else res
                        x = int(data.get("x", 0))
                        w = int(data.get("w", 0))
                        cw = int(data.get("cw", 0))
                        edge_tol = 2
                        at_right = (x + cw) >= (w - edge_tol)
                        at_left = x <= edge_tol
                        nonlocal now_ms
                        # 非对应边缘或方向时，重置对应计数
                        if not at_right and delta_y > 0:
                            self._prev_tick_counter = 0
                        if not at_left and delta_y < 0:
                            self._next_tick_counter = 0
                        if cooldown_active:
                            return
                        # 在最右边且向上滚（向右）=> 累计到达阈值触发上一章
                        if at_right and delta_y > 0:
                            self._prev_tick_counter += 1
                            self._next_tick_counter = 0
                            if self._prev_tick_counter >= self._prev_ticks_needed:
                                self.prev_chapter_requested.emit()
                                self._last_gesture_ts = now_ms
                                self._prev_tick_counter = 0
                        # 在最左边且向下滚（向左）=> 累计到达阈值触发下一章
                        elif at_left and delta_y < 0:
                            self._next_tick_counter += 1
                            self._prev_tick_counter = 0
                            if self._next_tick_counter >= self._next_ticks_needed:
                                self.next_chapter_requested.emit()
                                self._last_gesture_ts = now_ms
                                self._next_tick_counter = 0
                    except Exception:
                        pass

                js_probe = """
(() => {
  const de = document.documentElement;
  return JSON.stringify({x: de.scrollLeft, w: de.scrollWidth, cw: de.clientWidth});
})()
"""
                self.page().runJavaScript(js_probe, _edge_check_cb)
                event.accept()
            except Exception:
                super().wheelEvent(event)
else:
    VerticalWebView = None

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
        self.chapter_by_idx = {}
        self.fetch_thread = None
        self.index_thread = None
        self.progress_dialog = None

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
        
        # 按钮区域
        btn_grid = QVBoxLayout()
        btn_grid.setSpacing(4)
        
        self.import_btn = QPushButton("导入书籍")
        self.import_btn.clicked.connect(self.import_book_dialog_async)
        self.import_btn.setMaximumHeight(32)
        btn_grid.addWidget(self.import_btn)
        
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
        self.chapter_search.setPlaceholderText("搜索章节")
        self.chapter_search.setMaximumWidth(160)
        self.chapter_search.setMaximumHeight(32)
        self.search_btn = QPushButton("搜索")
        self.search_btn.clicked.connect(self.search_chapter)
        self.search_btn.setMaximumHeight(32)
        self.search_btn.setMaximumWidth(60)
        search_row.addWidget(self.chapter_search)
        search_row.addWidget(self.search_btn)
        left_col.addLayout(search_row)

        # 章节目录
        self.chapter_label = QLabel("章节目录")  # 简化标签文字
        self.chapter_label.setMaximumHeight(20)
        left_col.addWidget(self.chapter_label)
        self.chapter_list = QListWidget()
        self.chapter_list.setUniformItemSizes(True)
        self.chapter_list.setVerticalScrollMode(QListWidget.ScrollPerPixel)
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

        # 直排开关
        self.vertical_cb = QCheckBox("直排")
        self.vertical_cb.setChecked(self.settings.get("vertical_mode", False))
        self.vertical_cb.toggled.connect(self.toggle_vertical_mode)
        top_controls.addWidget(self.vertical_cb)
        right_col.addLayout(top_controls)
        self.text_browser = GestureTextBrowser()
        self.base_font = QFont(self.settings.get("font_family", "方正启体简体"), self.settings.get("font_size", 22))
        self.text_browser.setFont(self.base_font)
        self.text_browser.setOpenExternalLinks(True)
        self.text_browser.setWordWrapMode(QTextOption.WrapAtWordBoundaryOrAnywhere)
        # 连接手势信号
        self.text_browser.prev_chapter_requested.connect(self.go_to_prev_chapter)
        self.text_browser.next_chapter_requested.connect(self.go_to_next_chapter)
        right_col.addWidget(self.text_browser, 10)

        # WebEngine 视图（用于真·直排）
        self.web_view = VerticalWebView() if 'WEBENGINE_AVAILABLE' in globals() and WEBENGINE_AVAILABLE and VerticalWebView else None
        if self.web_view:
            right_col.addWidget(self.web_view, 10)
            self.web_view.setVisible(self.settings.get("vertical_mode", False))
            # 直排视图滚轮切章：连接到主窗口的上一章/下一章
            if hasattr(self.web_view, "prev_chapter_requested"):
                self.web_view.prev_chapter_requested.connect(self.go_to_prev_chapter)
            if hasattr(self.web_view, "next_chapter_requested"):
                self.web_view.next_chapter_requested.connect(self.go_to_next_chapter)
        # 初始模式下的可见性
        self.text_browser.setVisible(not self.settings.get("vertical_mode", False) or not self.web_view)
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
        self._settings_dirty = False
        self._library_dirty = False
        self._fetching = False
        self._current_raw_content = None

        tb = QToolBar("工具")
        self.addToolBar(tb)
        act = QAction("导入书籍", self)
        act.triggered.connect(self.import_book_dialog_async)
        tb.addAction(act)
        self.refresh_book_select_list()
        self.apply_night_mode(self.night_cb.isChecked())
        
    def closeEvent(self, event):
        """程序关闭时清理资源"""
        # 清理章节获取线程（优雅退出）
        try:
            t = self.fetch_thread
            if t and t.isRunning():
                t.requestInterruption()
                t.quit()
                t.wait()
        except Exception:
            pass
        
        # 清理目录获取线程（优雅退出，兼容自定义 stop）
        if self.index_thread and self.index_thread.isRunning():
            try:
                if hasattr(self.index_thread, "stop"):
                    self.index_thread.stop()  
                if hasattr(self.index_thread, "requestInterruption"):
                    self.index_thread.requestInterruption()
                self.index_thread.quit()
                self.index_thread.wait()
            except Exception:
                pass
        
        # 清理进度弹窗
        if hasattr(self, 'progress_dialog') and self.progress_dialog:
            self.progress_dialog.close()
            self.progress_dialog.deleteLater()
            self.progress_dialog = None
        
        event.accept()

    # UI / business methods (behaviour unchanged; where parsing occurs we call component)
    def refresh_book_select_list(self):
        self.book_select.setUpdatesEnabled(False)
        self.book_select.clear()
        for bid, meta in self.library.items():
            title = meta.get("title") or meta.get("index_url") or bid
            item = QListWidgetItem(title)
            item.setData(Qt.UserRole, bid)
            self.book_select.addItem(item)
        self.book_select.setUpdatesEnabled(True)

    def import_book_dialog_async(self):
        url, ok = QInputDialog.getText(self, "导入书籍（输入书籍首页 URL）", "书籍首页 URL:")
        if not ok or not url.strip():
            return
        url = url.strip()
        ok2 = QMessageBox.question(self, "版权提醒", "请确保你抓取内容仅用于个人学习/备份。继续导入？")
        if ok2 != QMessageBox.StandardButton.Yes:
            return
        # 启动异步导入
        logging.info(f"请求导入书籍: url='{url}'")
        # English: request to import book
        # logging.info(f"import book requested: url='{url}'")
        self._start_index_fetch(url, "正在导入目录…", "正在导入", 
                               lambda chapters, error: self._handle_index_fetch_result(chapters, error, is_import=True, url=url))

    def refresh_current_book_index_async(self):
        if not self.current_book_id:
            QMessageBox.information(self, "提示", "请先选中一本书")
            return
        
        meta = self.library[self.current_book_id]
        url = meta.get("index_url")
        if not url:
            QMessageBox.warning(self, "错误", "未记录书籍目录 URL")
            return
            
        self._start_index_fetch(url, "正在刷新目录…", "正在刷新", 
                               lambda chapters, error: self._handle_index_fetch_result(chapters, error, is_import=False))

    def _start_index_fetch(self, url, dialog_message, dialog_title, callback):
        """统一的索引获取启动方法"""
        if self.index_thread and self.index_thread.isRunning():
            QMessageBox.information(self, "提示", "目录正在导入/刷新，请稍候")
            return
        
        # 清理旧的线程对象
        if self.index_thread:
            self.index_thread.deleteLater()
            self.index_thread = None
        
        self.index_thread = IndexFetchThread(url)
        self.import_btn.setEnabled(False)
        self.refresh_btn.setEnabled(False)
        
        # 连接信号
        self.index_thread.progress.connect(lambda s: self.status.showMessage(s, 3000))
        self.index_thread.finished.connect(callback)
        self.index_thread.chapter_batch_ready.connect(self._on_chapter_batch_ready)
        
        # 显示进度弹窗
        self._show_progress_dialog(dialog_message, dialog_title)
        logging.info(f"开始获取目录: url='{url}'")
        # English: index fetch start
        # logging.info(f"index fetch start: url='{url}'")
        self.index_thread.start()

    def _handle_index_fetch_result(self, chapters, error, is_import=False, url=None):
        """统一的索引获取结果处理方法"""
        # 恢复按钮状态
        self.import_btn.setEnabled(True)
        self.refresh_btn.setEnabled(True)
        
        # 清理资源
        self._close_progress_dialog()
        if self.index_thread:
            self.index_thread.deleteLater()
            self.index_thread = None
        
        # 处理错误
        if error:
            action = "导入" if is_import else "刷新"
            QMessageBox.warning(self, f"{action}失败", f"请求或解析失败：{error}")
            return
            
        if not chapters:
            action = "导入" if is_import else "刷新"
            message = "未解析到章节列表，请检查 URL 是否为书籍目录页。" if is_import else "未解析到章节"
            QMessageBox.warning(self, f"{action}失败", message)
            return
        
        try:
            if is_import:
                self._handle_import_success(url, chapters)
            else:
                self._handle_refresh_success(chapters)
        except Exception as e:
            action = "导入" if is_import else "刷新"
            QMessageBox.warning(self, f"{action}失败", f"处理数据失败：{e}")

    def _handle_import_success(self, url, chapters):
        """处理导入成功"""
        # 获取书籍标题
        try:
            html_title = fetch_html(url)
            soup_title = extract_book_title_from_html(html_title)
        except Exception:
            soup_title = ""
        
        # 创建书籍元数据
        bid, meta = create_book_metadata(url, chapters, soup_title)
        # 将书籍缓存统一放到应用数据目录下的 books 文件夹
        meta["book_dir"] = str((BOOKS_DIR / bid).resolve())
        
        # 创建目录并保存调试文件
        create_book_directory_and_debug(meta, chapters)
        
        # 保存到库
        self.library[bid] = meta
        save_json(LIB_FILE, self.library)
        self.refresh_book_select_list()
        
        logging.info(f"导入成功: bid={bid}, 标题='{meta.get('title','')}', 章节数={len(chapters)}")
        # English: import success
        # logging.info(f"import success: bid={bid}, title='{meta.get('title','')}', chapters={len(chapters)}")
        QMessageBox.information(self, "导入成功",f"已导入书籍：{meta['title']}（共 {len(chapters)} 章）")

    def _handle_refresh_success(self, chapters):
        """处理刷新成功"""
        meta = self.library[self.current_book_id]
        meta["chapters"] = chapters
        prev_idx = meta.get("chapter_index", 0)
        if 0 <= prev_idx < len(chapters):
            meta["chapter_index"] = prev_idx
        else:
            meta["chapter_index"] = 0
        
        # 保存并更新调试文件
        save_json(LIB_FILE, self.library)
        create_book_directory_and_debug(meta, chapters)
        
        logging.info(f"目录刷新成功: bid={self.current_book_id}, 章节数={len(chapters)}")
        # English: index refresh success
        # logging.info(f"index refresh success: bid={self.current_book_id}, chapters={len(chapters)}")
        # 重新打开书籍
        self.open_book(self.current_book_id)
        QMessageBox.information(self, "完成", f"目录已刷新，共 {len(chapters)} 章")



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
        self._build_chapter_index_map()
        
        logging.info(f"打开书籍: bid={bid}, 章节数={len(self.current_chapters)}")
        # English: open book
        # logging.info(f"open_book: bid={bid}, chapters={len(self.current_chapters)}")
        # 优化大量章节的处理
        self._populate_chapter_list_optimized()
        
        self.text_browser.clear()
        if getattr(self, 'web_view', None):
            self.web_view.setHtml("")
        self.render_html("<i>点击左侧章节条目以加载并查看该章节内容（按需抓取并缓存）。</i>")
        self.update_navigation_buttons()
        # 自动定位并加载上次阅读的章节（若存在）
        idx = meta.get("chapter_index", 0)
        if self.current_chapters and 0 <= idx < len(self.current_chapters):
            self.load_chapter_by_index(idx)



    def _build_chapter_index_map(self):
        """构建章节索引到章节数据的映射，便于快速查找"""
        try:
            self.chapter_by_idx = {
                ch.get('index'): ch
                for ch in self.current_chapters
                if isinstance(ch, dict) and 'index' in ch
            }
        except Exception:
            self.chapter_by_idx = {}

    def search_chapter(self):
        q = self.chapter_search.text().strip()
        if not q: return
        try:
            n = int(q)
            for i in range(self.chapter_list.count()):
                it = self.chapter_list.item(i)
                item_index = it.data(Qt.UserRole)
                if item_index == n:
                    self.chapter_list.setCurrentItem(it)
                    self.chapter_list.scrollToItem(it)
                    return
            QMessageBox.information(self, "未找到", f"未找到第 {n} 章")
            return
        except Exception:
            pass
        # 大小写不敏感搜索
        q_lower = q.lower()
        matches = []
        for i in range(self.chapter_list.count()):
            it = self.chapter_list.item(i)
            if q_lower in (it.text() or "").lower():
                matches.append(it)
        if not matches:
            QMessageBox.information(self, "未找到", "未找到匹配章节")
            return
        self.chapter_list.setCurrentItem(matches[0])
        self.chapter_list.scrollToItem(matches[0])

    def on_chapter_clicked(self, item: QListWidgetItem):
        # 获取章节索引
        chapter_index = item.data(Qt.UserRole)
        if chapter_index is None:
            return
        # 抓取进行中则忽略新的点击，避免并发
        if getattr(self, "_fetching", False):
            return
        
        # 根据索引查找完整的章节数据（使用映射避免线性遍历）
        chapter_data = self.chapter_by_idx.get(chapter_index)
        if chapter_data:
            self.load_chapter_content(chapter_data)

    def load_chapter_content(self, chapter_data):
        """加载章节内容的通用方法"""
        # 停止并清理之前的线程（优雅退出）
        try:
            t = self.fetch_thread
            if t and t.isRunning():
                t.requestInterruption()
                t.quit()
                t.wait()
        except Exception:
            pass
        
        # 清理旧的线程对象
        if self.fetch_thread:
            self.fetch_thread.deleteLater()
            self.fetch_thread = None
        
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
        self.fetch_thread.finished.connect(self._cleanup_fetch_thread)
        self._fetching = True
        logging.info(f"开始抓取章节: index={idx}, url='{url}'")
        # English: chapter fetch start
        # logging.info(f"chapter fetch start: index={idx}, url='{url}'")
        self.fetch_thread.start()

    def on_chapter_fetched(self, index, data, error):
        if error:
            QMessageBox.warning(self, "抓取失败", f"第 {index} 章抓取失败：{error}")
            logging.info(f"抓取章节失败: index={index}, error={error}")
            # English: chapter fetch failed
            # logging.info(f"chapter fetch failed: index={index}, error={error}")
            self._fetching = False
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
        
        self.render_html(html)
        self._current_raw_content = content
        self.library[self.current_book_id]["chapter_index"] = index - 1
        self._library_dirty = True
        self._fetching = False
        self.status.showMessage(f"已加载第 {index} 章", 4000)
        logging.info(f"章节加载完成: index={index}, 标题='{title}'")
        # English: chapter loaded
        # logging.info(f"chapter loaded: index={index}, title='{title}'")
        self.update_navigation_buttons()

    def _cleanup_fetch_thread(self, *args):
        """线程完成后的安全清理：避免访问已删除的 C++ 对象"""
        try:
            t = self.fetch_thread
            self.fetch_thread = None
            if t:
                t.deleteLater()
        except Exception:
            pass

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
        target_index = chapter.get("index")
        for i in range(self.chapter_list.count()):
            item = self.chapter_list.item(i)
            item_index = item.data(Qt.UserRole)
            if item_index == target_index:
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



    # ========== 直排渲染相关 ==========


    def render_html(self, html):
        """按当前模式渲染 HTML 到合适的视图"""
        vertical = self.settings.get("vertical_mode", False)
        if vertical and getattr(self, 'web_view', None):
            vhtml = wrap_vertical_html(
                html,
                self.settings.get("font_family", DEFAULT_SETTINGS["font_family"]),
                self.settings.get("font_size", 22),
                self.settings.get("line_height", 1.6),
                self.settings.get("night_mode", False),
                self.settings.get("text_color", DEFAULT_SETTINGS["text_color"]),
                self.settings.get("bg_color", "#ffffff"),
            )
            self.web_view.setHtml(vhtml)
            # 直排下默认定位到最右侧（文章开头）
            try:
                QTimer.singleShot(60, lambda: self.web_view.page().runJavaScript(
                    "window.scrollTo({left: document.documentElement.scrollWidth, top: 0, behavior: 'auto'});"
                ))
            except Exception:
                pass
        else:
            self.text_browser.setHtml(html)

    def toggle_vertical_mode(self, on):
        """切换直排模式"""
        self.settings["vertical_mode"] = on
        self._settings_dirty = True
        if getattr(self, 'web_view', None):
            self.web_view.setVisible(on)
        # 无 WebEngine 时仍显示 QTextBrowser
        self.text_browser.setVisible(not on or not getattr(self, 'web_view', None))
        if on and not getattr(self, 'web_view', None):
            QMessageBox.information(self, "直排不可用", "当前环境未检测到 WebEngine 组件，已继续使用横排显示。如需直排，请安装 PySide6（包含 QtWebEngine）后重启应用。")

        # 重新渲染当前内容
        if getattr(self, "_current_raw_content", None) is not None:
            html = process_chapter_content_for_display(
                self._current_raw_content,
                self.settings.get("font_family", DEFAULT_SETTINGS["font_family"]),
                self.settings.get("font_size", 22),
                self.settings.get("line_height", 1.6),
                self.settings.get("night_mode", False),
                self.settings.get("text_color", DEFAULT_SETTINGS["text_color"])
            )
            self.render_html(html)
        elif getattr(self, 'web_view', None) and on:
            self.web_view.setHtml("")

    def change_font_size(self, v):
        self.settings["font_size"] = v
        self._settings_dirty = True
        self.base_font.setPointSize(v)
        self.text_browser.setFont(self.base_font)
        # 重新渲染当前内容（使用原始文本，保持一致性）
        if getattr(self, "_current_raw_content", None) is not None:
            html = process_chapter_content_for_display(
                self._current_raw_content,
                self.settings.get("font_family", DEFAULT_SETTINGS["font_family"]),
                self.settings.get("font_size", 22),
                self.settings.get("line_height", 1.6),
                self.settings.get("night_mode", False),
                self.settings.get("text_color", DEFAULT_SETTINGS["text_color"])
            )
            self.render_html(html)

    def toggle_night_mode(self, on):
        self.settings["night_mode"] = on
        self._settings_dirty = True
        self.apply_night_mode(on)
        # 夜间模式切换后，基于原始文本重新渲染以保持一致性
        if getattr(self, "_current_raw_content", None) is not None:
            html = process_chapter_content_for_display(
                self._current_raw_content,
                self.settings.get("font_family", DEFAULT_SETTINGS["font_family"]),
                self.settings.get("font_size", 22),
                self.settings.get("line_height", 1.6),
                self.settings.get("night_mode", False),
                self.settings.get("text_color", DEFAULT_SETTINGS["text_color"])
            )
            self.render_html(html)

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

        logging.info(f"请求删除书籍: bid={bid}, 标题='{meta.get('title','未知书籍')}'")
        # English: remove book requested
        # logging.info(f"remove book requested: bid={bid}, title='{meta.get('title','未知书籍')}'")
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
        
        logging.info(f"书籍已删除: bid={bid}, 标题='{meta.get('title','未知书籍')}'")
        # English: book removed
        # logging.info(f"book removed: bid={bid}, title='{meta.get('title','未知书籍')}'")
        QMessageBox.information(self, "删除成功", "书籍已成功删除")

    def _show_progress_dialog(self, message, title):
        """显示进度弹窗"""
        try:
            # 先清理旧的弹窗
            self._close_progress_dialog()
            
            self.progress_dialog = QProgressDialog(message, "", 0, 0, self)
            self.progress_dialog.setWindowTitle(title)
            self.progress_dialog.setWindowModality(Qt.WindowModality.NonModal)
            self.progress_dialog.setCancelButton(None)
            self.progress_dialog.setAutoClose(False)
            self.progress_dialog.setAutoReset(False)
            self.progress_dialog.show()
        except Exception:
            pass

    def _close_progress_dialog(self):
        """关闭并清理进度弹窗"""
        if hasattr(self, 'progress_dialog') and self.progress_dialog:
            try:
                self.progress_dialog.close()
                self.progress_dialog.deleteLater()
            except Exception:
                pass
            finally:
                self.progress_dialog = None

    def _populate_chapter_list_optimized(self):
        """优化的章节列表填充方法，处理大量章节时避免内存泄漏"""
        self.chapter_list.setUpdatesEnabled(False)
        self.chapter_list.clear()
        
        chapter_count = len(self.current_chapters)
        
        if chapter_count > 2000:
            self._populate_large_chapter_list(chapter_count)
        else:
            self._populate_standard_chapters()
        
        self.chapter_list.setUpdatesEnabled(True)
        self.status.showMessage(f"已加载 {chapter_count} 章节", 3000)

    def _populate_large_chapter_list(self, chapter_count):
        """处理大量章节的分批加载"""
        self.status.showMessage(f"正在加载 {chapter_count} 章节，请稍候...", 5000)
        batch_size = 200
        
        for i in range(0, chapter_count, batch_size):
            batch_end = min(i + batch_size, chapter_count)
            batch_chapters = self.current_chapters[i:batch_end]
            
            # 批量创建并添加项目
            for ch in batch_chapters:
                display = f"{ch.get('index', '?')}. {ch.get('title') or ''}"
                item = QListWidgetItem(display)
                item.setData(Qt.UserRole, ch.get('index'))
                self.chapter_list.addItem(item)
            
            QApplication.processEvents()
            
            # 更新进度
            progress = int((batch_end / chapter_count) * 100)
            self.status.showMessage(f"加载章节进度: {progress}% ({batch_end}/{chapter_count})", 1000)
            
            # 定期垃圾回收
            if i % 1000 == 0:
                import gc
                gc.collect()

    def _populate_standard_chapters(self):
        """处理标准数量章节的加载"""
        for ch in self.current_chapters:
            display = f"{ch.get('index', '?')}. {ch.get('title') or ''}"
            item = QListWidgetItem(display)
            item.setData(Qt.UserRole, ch.get('index'))
            self.chapter_list.addItem(item)

    def _on_chapter_batch_ready(self, batch_chapters, current_count, total_estimated):
        """处理章节批次数据（用于大量章节的实时反馈）"""
        try:
            if hasattr(self, 'progress_dialog') and self.progress_dialog:
                progress_pct = int((current_count / total_estimated) * 100) if total_estimated > 0 else 0
                self.progress_dialog.setLabelText(f"正在处理章节: {current_count}/{total_estimated} ({progress_pct}%)")
        except Exception:
            pass

    def _auto_save(self):
        """自动保存设置和库"""
        try:
            if getattr(self, "_settings_dirty", False):
                save_json(SETTINGS_FILE, self.settings)
                self._settings_dirty = False
            if getattr(self, "_library_dirty", False):
                save_json(LIB_FILE, self.library)
                self._library_dirty = False
                logging.info("library.json 已保存")
                # English: library.json saved
                # logging.info("library.json saved")
        except Exception:
            logging.exception("自动保存失败")
def main():
    app = QApplication(sys.argv)
    app.setStyle("Fusion")  # 使用Fusion风格，在所有平台上看起来一致
    window = NovelReaderSidebarFixed()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()