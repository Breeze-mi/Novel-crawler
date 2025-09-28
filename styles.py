# 样式定义文件
# 包含应用程序的夜间模式和浅色模式样式

# MD3 夜间模式样式 - 低对比度护眼设计
DARK_STYLE = """
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

# MD3 浅色模式 - 护眼的浅棕色主题
LIGHT_STYLE = """
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