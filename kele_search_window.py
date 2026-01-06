"""

使用 CFCookie 方案进行搜索
"""
import logging
from typing import List, Dict

from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLineEdit, 
    QPushButton, QListWidget, QListWidgetItem, QLabel, QFrame
)
from PySide6.QtCore import Qt, QThread, Signal

# 导入搜索核心功能
from kele_search import (
    search_kele_books, 
    load_cf_clearance, 
    save_cf_clearance,
    get_cookie_info
)


class SearchThread(QThread):
    """搜索线程"""
    finished = Signal(list, str)  # (results, error)
    progress = Signal(str)  # 进度信息
    
    def __init__(self, keyword: str):
        super().__init__()
        self.keyword = keyword
        
    def run(self):
        """执行搜索"""
        try:
            self.progress.emit(f"正在搜索: {self.keyword}")
            results = search_kele_books(self.keyword)
            
            if not results:
                self.finished.emit([], "未找到相关书籍")
                return
                
            self.progress.emit(f"找到 {len(results)} 本书籍")
            self.finished.emit(results, "")
            
        except Exception as e:
            logging.exception("搜索失败")
            self.finished.emit([], str(e))


class SearchWindow(QMainWindow):
    """独立的搜索窗口"""
    book_selected = Signal(str, str)  # (url, title)
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowFlags(Qt.WindowType.Window)
        self.setWindowTitle("可乐读书 - 搜索书籍")
        self.resize(950, 600)
        self.search_thread = None
        self.search_results = []
        self._night_mode = False
        self.setup_ui()
        self.load_cookie()
        
    def setup_ui(self):
        """设置UI"""
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        
        layout = QVBoxLayout(central_widget)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)
        
        # ===== 顶部区域：搜索框和Cookie输入框 =====
        top_layout = QHBoxLayout()
        top_layout.setSpacing(24)
        
        # 左侧：搜索区域
        search_frame = QFrame()
        search_layout = QHBoxLayout(search_frame)
        search_layout.setContentsMargins(0, 0, 0, 0)
        search_layout.setSpacing(8)
        
        self.search_label = QLabel("搜索:")
        search_layout.addWidget(self.search_label)
        
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("输入书名或作者名...")
        self.search_input.returnPressed.connect(self.do_search)
        self.search_input.setMinimumWidth(200)
        search_layout.addWidget(self.search_input)
        
        self.search_btn = QPushButton("搜  索")
        self.search_btn.clicked.connect(self.do_search)
        self.search_btn.setMinimumWidth(80)
        self.search_btn.setMinimumHeight(32)
        search_layout.addWidget(self.search_btn)
        
        top_layout.addWidget(search_frame)
        top_layout.addStretch()
        
        # 右侧：Cookie 配置区域
        cookie_frame = QFrame()
        cookie_layout = QHBoxLayout(cookie_frame)
        cookie_layout.setContentsMargins(0, 0, 0, 0)
        cookie_layout.setSpacing(6)
        
        self.cookie_label = QLabel("Cookie:")
        cookie_layout.addWidget(self.cookie_label)
        
        # 固定前缀标签 - 使用与列表相同的文字颜色
        self.prefix_label = QLabel("cf_clearance=")
        cookie_layout.addWidget(self.prefix_label)
        
        self.cookie_input = QLineEdit()
        self.cookie_input.setPlaceholderText("粘贴值...")
        self.cookie_input.setMinimumWidth(180)
        cookie_layout.addWidget(self.cookie_input)
        
        self.save_cookie_btn = QPushButton("保  存")
        self.save_cookie_btn.clicked.connect(self.save_cookie)
        self.save_cookie_btn.setMinimumWidth(70)
        self.save_cookie_btn.setMinimumHeight(32)
        cookie_layout.addWidget(self.save_cookie_btn)
        
        top_layout.addWidget(cookie_frame)
        
        layout.addLayout(top_layout)
        
        # ===== 提示标签 =====
        self.tip_label = QLabel("提示: 首次使用需要配置 Cookie")
        layout.addWidget(self.tip_label)
        
        # ===== 结果列表 =====
        self.result_list = QListWidget()
        self.result_list.itemDoubleClicked.connect(self.on_result_double_clicked)
        self.result_list.itemClicked.connect(self.on_result_clicked)
        layout.addWidget(self.result_list, 1)
        
        # ===== 底部按钮 =====
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        
        self.import_btn = QPushButton("导入选中书籍")
        self.import_btn.clicked.connect(self.on_import_clicked)
        self.import_btn.setEnabled(False)
        self.import_btn.setMinimumWidth(120)
        self.import_btn.setMinimumHeight(36)
        btn_layout.addWidget(self.import_btn)
        
        self.close_btn = QPushButton("关  闭")
        self.close_btn.clicked.connect(self.close)
        self.close_btn.setMinimumWidth(80)
        self.close_btn.setMinimumHeight(36)
        btn_layout.addWidget(self.close_btn)
        
        layout.addLayout(btn_layout)
        
    def set_night_mode(self, night_mode: bool):
        """设置夜间模式，同步主窗口主题"""
        self._night_mode = night_mode
        self._update_prefix_style()
        
    def _update_prefix_style(self):
        """更新前缀标签样式，使用与列表文字相同的颜色"""
        if self._night_mode:
            # 夜间模式：使用 #d0d0d0 (与 QListWidget 文字颜色一致)
            self.prefix_label.setStyleSheet(
                "color: #d0d0d0; font-family: Consolas, 'Courier New', monospace; font-weight: bold;"
            )
        else:
            # 亮色模式：使用 #800000 (与 QListWidget 文字颜色一致)
            self.prefix_label.setStyleSheet(
                "color: #800000; font-family: Consolas, 'Courier New', monospace; font-weight: bold;"
            )
        
    def load_cookie(self):
        """加载现有 cookie"""
        cookie = load_cf_clearance()
        if cookie:
            self.cookie_input.setText(cookie)
            
            # 获取 Cookie 信息
            cookie_info = get_cookie_info()
            if cookie_info:
                age_hours = cookie_info['age_hours']
                expire_hours = cookie_info['estimated_expire_hours']
                
                if expire_hours > 1:
                    tip = f"✓ Cookie 已加载（已使用 {age_hours:.1f} 小时，预计还剩 {expire_hours:.1f} 小时有效）"
                    self._set_tip(tip, "success")
                elif expire_hours > 0:
                    tip = f"⚠ Cookie 即将过期（已使用 {age_hours:.1f} 小时，预计还剩 {expire_hours*60:.0f} 分钟）"
                    self._set_tip(tip, "warning")
                else:
                    tip = f"❌ Cookie 可能已过期（已使用 {age_hours:.1f} 小时），建议重新获取"
                    self._set_tip(tip, "error")
            else:
                self._set_tip("✓ Cookie 已加载，可以开始搜索", "success")
        else:
            self._set_tip("⚠ 未配置 Cookie，请先配置", "warning")
            
    def save_cookie(self):
        """保存 cookie"""
        cookie = self.cookie_input.text().strip()
        if not cookie:
            self._set_tip("❌ Cookie 不能为空", "error")
            return
        
        if save_cf_clearance(cookie):
            self._set_tip("✓ Cookie 已保存（预计有效期约 12 小时）", "success")
            # 重新加载以显示时间信息
            self.load_cookie()
        else:
            self._set_tip("❌ Cookie 保存失败", "error")
        
    def do_search(self):
        """执行搜索"""
        keyword = self.search_input.text().strip()
        if not keyword:
            self._set_tip("⚠ 请输入搜索关键词", "warning")
            return
        
        if not load_cf_clearance():
            self._set_tip("⚠ 未配置 Cookie，请先配置", "error")
            return
        
        # 清空之前的结果
        self.result_list.clear()
        self.search_results = []
        self.import_btn.setEnabled(False)
        
        # 禁用搜索按钮
        self.search_btn.setEnabled(False)
        self.search_btn.setText("搜索中...")
        
        # 启动搜索线程
        self.search_thread = SearchThread(keyword)
        self.search_thread.finished.connect(self.on_search_finished)
        self.search_thread.progress.connect(self.on_search_progress)
        self.search_thread.start()
        
    def on_search_progress(self, message: str):
        """搜索进度更新"""
        self._set_tip(message, "info")
        
    def on_search_finished(self, results: List[Dict], error: str):
        """搜索完成"""
        self.search_btn.setEnabled(True)
        self.search_btn.setText("搜  索")
        
        if error:
            self._set_tip(f"❌ {error}", "error")
            return
        
        if not results:
            self._set_tip("未找到相关书籍", "info")
            return
        
        # 显示结果
        self.search_results = results
        for book in results:
            title = book.get('title', '未知')
            author = book.get('author', '未知')
            latest = book.get('latest', '')
            
            display_text = f"{title} - {author}"
            if latest:
                display_text += f"  [{latest}]"
            
            item = QListWidgetItem(display_text)
            item.setData(Qt.ItemDataRole.UserRole, book)
            self.result_list.addItem(item)
        
        self._set_tip(f"✓ 找到 {len(results)} 本书籍，双击或选中后点击导入", "success")
        self.import_btn.setEnabled(True)
        
    def on_result_clicked(self, item):
        """单击结果项"""
        self.import_btn.setEnabled(True)
        
    def on_result_double_clicked(self, item):
        """双击结果项"""
        self.on_import_clicked()
        
    def on_import_clicked(self):
        """导入选中的书籍"""
        current_item = self.result_list.currentItem()
        if not current_item:
            self._set_tip("⚠ 请先选择书籍", "warning")
            return
        
        book = current_item.data(Qt.ItemDataRole.UserRole)
        if not book or not book.get('url'):
            self._set_tip("❌ 无效的书籍数据", "error")
            return
        
        book_url = book.get('url')
        book_title = book.get('title', '未知')
        
        # 发送信号给主窗口
        self.book_selected.emit(book_url, book_title)
        self.close()
        
    def _set_tip(self, text: str, level: str = "info"):
        """设置提示信息"""
        self.tip_label.setText(text)
        
        # 根据级别设置颜色
        if self._night_mode:
            colors = {
                "success": "#66bb6a",  # 绿色
                "warning": "#ffa726",  # 橙色
                "error": "#ef5350",    # 红色
                "info": "#d0d0d0"      # 默认文字色
            }
        else:
            colors = {
                "success": "#2e7d32",  # 深绿
                "warning": "#f57c00",  # 深橙
                "error": "#c62828",    # 深红
                "info": "#5D4E37"      # 默认文字色
            }
        
        color = colors.get(level, colors["info"])
        self.tip_label.setStyleSheet(f"color: {color}; padding: 4px 0;")
