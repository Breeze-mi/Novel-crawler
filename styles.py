# MD3 夜间模式样式 - 低对比度护眼设计
DARK_STYLE = """
/* 主窗口样式 */
QMainWindow {
    background-color: #1a1a1a; /* 背景颜色 */
    color: #d0d0d0; /* 文本颜色 */
}
/* 通用组件样式 */
QWidget {
    background-color: #1a1a1a; /* 背景颜色 */
    color: #d0d0d0; /* 文本颜色 */
}
/* 列表组件样式 */
QListWidget {
    background-color: #2a2a2a; /* 背景颜色 */
    color: #d0d0d0; /* 文本颜色 */
    border: 1px solid #404040; /* 边框 */
    border-radius: 12px; /* 边框圆角 */
    selection-background-color: #4a4a4a; /* 选中项背景颜色 */
}
/* 列表项样式 */
QListWidget::item {
    padding: 8px 12px; /* 内边距 */
    border-bottom: 1px solid #353535; /* 底部边框 */
}
/* 列表项悬停样式 */
QListWidget::item:hover {
    background-color: #353535; /* 悬停背景颜色 */
}
/* 列表项选中样式 */
QListWidget::item:selected {
    background-color: #4a4a4a; /* 选中背景颜色 */
}
/* 按钮样式 */
QPushButton {
    background-color: #4a4a4a; /* 背景颜色 */
    color: #d0d0d0; /* 文本颜色 */
    border: none; /* 无边框 */
    border-radius: 12px; /* 边框圆角 */
    padding: 8px 16px; /* 内边距 */
    font-weight: 500; /* 字体粗细 */
    font-size: 13px; /* 字体大小 */
}
/* 按钮悬停样式 */
QPushButton:hover {
    background-color: #5a5a5a; /* 悬停背景颜色 */
}
/* 按钮按下样式 */
QPushButton:pressed {
    background-color: #3a3a3a; /* 按下背景颜色 */
}
/* 按钮禁用样式 */
QPushButton:disabled {
    background-color: #2a2a2a; /* 禁用背景颜色 */
    color: #666666; /* 禁用文本颜色 */
}
/* 行编辑框样式 */
QLineEdit {
    background-color: #2a2a2a; /* 背景颜色 */
    color: #d0d0d0; /* 文本颜色 */
    border: 2px solid #404040; /* 边框 */
    border-radius: 8px; /* 边框圆角 */
    padding: 6px 10px; /* 内边距 */
    font-size: 13px; /* 字体大小 */
}
/* 行编辑框焦点样式 */
QLineEdit:focus {
    border-color: #6a6a6a; /* 焦点边框颜色 */
}
/* 标签样式 */
QLabel {
    color: #d0d0d0; /* 文本颜色 */
}
/* 数字选择框样式 */
QSpinBox {
    background-color: #2a2a2a; /* 背景颜色 */
    color: #d0d0d0; /* 文本颜色 */
    border: 2px solid #404040; /* 边框 */
    border-radius: 8px; /* 边框圆角 */
    padding: 8px; /* 内边距 */
}
/* 复选框样式 */
QCheckBox {
    color: #d0d0d0; /* 文本颜色 */
}
/* 复选框指示器样式 */
QCheckBox::indicator {
    width: 20px; /* 宽度 */
    height: 20px; /* 高度 */
}
/* 复选框未选中指示器样式 */
QCheckBox::indicator:unchecked {
    background-color: #2a2a2a; /* 背景颜色 */
    border: 2px solid #404040; /* 边框 */
    border-radius: 6px; /* 边框圆角 */
}
/* 复选框选中指示器样式 */
QCheckBox::indicator:checked {
    background-color: #5a5a5a; /* 背景颜色 */
    border: 2px solid #5a5a5a; /* 边框 */
    border-radius: 6px; /* 边框圆角 */
}
/* 文本浏览器样式 */
QTextBrowser {
    background-color: #222222; /* 背景颜色 */
    color: #d0d0d0; /* 文本颜色 */
    border: 1px solid #404040; /* 边框 */
    border-radius: 12px; /* 边框圆角 */
    padding: 20px; /* 内边距 */
}
/* 状态栏样式 */
QStatusBar {
    background-color: #2a2a2a; /* 背景颜色 */
    color: #d0d0d0; /* 文本颜色 */
    border-top: 1px solid #404040; /* 顶部边框 */
}
/* 工具栏样式 */
QToolBar {
    background-color: #2a2a2a; /* 背景颜色 */
    border: none; /* 无边框 */
    spacing: 3px; /* 间距 */
}
"""

# MD3 浅色模式 - 护眼的浅棕色主题
LIGHT_STYLE = """
/* 主窗口样式 */
QMainWindow {
    background-color: #D2B48C; /* 背景颜色 */
    color: #5D4E37; /* 文本颜色 */
}
/* 通用组件样式 */
QWidget {
    background-color: #D2B48C; /* 背景颜色 */
    color: #5D4E37; /* 文本颜色 */
}
/* 所有列表组件样式 */
QListWidget {
    background-color: #E6D3A3; /* 背景颜色 */
    color: #800000; /* 文本颜色 */
    border: 1px solid #C19A6B; /* 边框 */
    border-radius: 12px; /* 边框圆角 */
    selection-background-color: #DEB887; /* 选中项背景颜色 */
}
/* 列表项样式 */
QListWidget::item {
    padding: 8px 12px; /* 内边距 */
    border-bottom: 1px solid #C19A6B; /* 底部边框 */
}
/* 列表项悬停样式 */
QListWidget::item:hover {
    background-color: #DEB887; /* 悬停背景颜色 */
}
/* 列表项选中样式 */
QListWidget::item:selected {
    background-color: #CD853F; /* 选中背景颜色 */
    color: #FFFFFF; /* 选中文本颜色 */
}
/* 按钮样式 */
QPushButton {
    background-color: #CD853F; /* 背景颜色 */
    color: #FFFFFF; /* 文本颜色 */
    border: none; /* 无边框 */
    border-radius: 12px; /* 边框圆角 */
    padding: 8px 16px; /* 内边距 */
    font-weight: 500; /* 字体粗细 */
    font-size: 13px; /* 字体大小 */
}
/* 按钮悬停样式 */
QPushButton:hover {
    background-color: #D2691E; /* 悬停背景颜色 */
}
/* 按钮按下样式 */
QPushButton:pressed {
    background-color: #A0522D; /* 按下背景颜色 */
}
/* 按钮禁用样式 */
QPushButton:disabled {
    background-color: #E6D3A3; /* 禁用背景颜色 */
    color: #999999; /* 禁用文本颜色 */
}
/* 行编辑框样式 */
QLineEdit {
    background-color: #F5E6D3; /* 背景颜色 */
    color: #5D4E37; /* 文本颜色 */
    border: 2px solid #C19A6B; /* 边框 */
    border-radius: 12px; /* 边框圆角 */
    padding: 6px 10px; /* 内边距 */
    font-size: 13px; /* 字体大小 */
}
/* 行编辑框焦点样式 */
QLineEdit:focus {
    border-color: #CD853F; /* 焦点边框颜色 */
}
/* 标签样式 */
QLabel {
    color: #5D4E37; /* 文本颜色 */
    font-weight: 500; /* 字体粗细 */
}
/* 数字选择框样式 */
QSpinBox {
    background-color: #F5E6D3; /* 背景颜色 */
    color: #5D4E37; /* 文本颜色 */
    border: 2px solid #C19A6B; /* 边框 */
    border-radius: 8px; /* 边框圆角 */
    padding: 8px; /* 内边距 */
}
/* 复选框样式 */
QCheckBox {
    color: #5D4E37; /* 文本颜色 */
    font-weight: 500; /* 字体粗细 */
}
/* 复选框指示器样式 */
QCheckBox::indicator {
    width: 20px; /* 宽度 */
    height: 20px; /* 高度 */
}
/* 复选框未选中指示器样式 */
QCheckBox::indicator:unchecked {
    background-color: #F5E6D3; /* 背景颜色 */
    border: 2px solid #C19A6B; /* 边框 */
    border-radius: 6px; /* 边框圆角 */
}
/* 复选框选中指示器样式 */
QCheckBox::indicator:checked {
    background-color: #CD853F; /* 背景颜色 */
    border: 2px solid #CD853F; /* 边框 */
    border-radius: 6px; /* 边框圆角 */
}
/* 文本浏览器样式 */
QTextBrowser {
    background-color: #F5E6D3; /* 背景颜色 */
    color: #800000; /* 文本颜色 */
    border: 1px solid #C19A6B; /* 边框 */
    border-radius: 12px; /* 边框圆角 */
    padding: 20px; /* 内边距 */
}
/* 状态栏样式 */
QStatusBar {
    background-color: #E6D3A3; /* 背景颜色 */
    color: #5D4E37; /* 文本颜色 */
    border-top: 1px solid #C19A6B; /* 顶部边框 */
}
/* 工具栏样式 */
QToolBar {
    background-color: #E6D3A3; /* 背景颜色 */
    border: none; /* 无边框 */
    spacing: 3px; /* 间距 */
}
"""

# 直排排版 HTML 包装函数（与主程序一致）
def wrap_vertical_html(inner_html, font_family, font_size, line_height, night, text_color, bg_color=None):
    """
    生成包含直排 CSS 的完整 HTML。
    参数：
      - inner_html: 已生成的章节 HTML 片段
      - font_family: 字体
      - font_size: 字号（px）
      - line_height: 行高
      - night: 是否夜间模式（决定深色背景）
      - text_color: 文本颜色
      - bg_color: 背景色（可选；白天模式下优先使用该色）
    """
    if bg_color is None:
        bg = "#121212" if night else "#ffffff"
    else:
        bg = "#121212" if night else bg_color
    return f"""<!doctype html>
<meta charset="utf-8">
<style>
  html,body {{
    margin:0; height:100%; background:{bg}; color:{text_color};
  }}
  .vwrap {{
    writing-mode: vertical-rl;
    text-orientation: mixed;
    font-feature-settings: "vert" 1, "vrt2" 1;
    font-family: "{font_family}", "Noto Serif CJK SC", "Source Han Serif SC", serif;
    font-size: {font_size}px;
    line-height: {line_height};
    padding: 12px 16px;
    /* 减少标点贴近问题与更自然断行 */
    letter-spacing: 0.02em;
    line-break: strict;
    word-break: keep-all;
    overflow-wrap: anywhere;
    hanging-punctuation: allow-end;
    text-rendering: optimizeLegibility;
    scroll-behavior: smooth;
  }}
  a {{ color: {text_color}; text-decoration: underline; }}
</style>
<div class="vwrap">{inner_html}</div>"""