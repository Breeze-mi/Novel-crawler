# Novel Reader Pro

## 项目简介

这是一个基于 Python 的小说阅读器,使用 PySide6 提供图形用户界面，旨在帮助用户从在线小说网站抓取小说内容，并提供本地阅读和管理功能。项目支持从多个网站抓取小说，并允许用户删除书籍及其缓存文件。

## 主要功能

- 从指定小说网站抓取小说章节内容。
- 本地阅读已请求下载的小说。
- 管理已下载的小说，包括删除书籍及其关联的缓存文件。
- 支持自定义搜索框长度。
- 支持滚轮自动切换章节。
- 适配不同的网站解析逻辑，基本支持所有基于笔趣阁二开的小说网站。

## 免责声明

**本项目仅供个人学习与研究之用，不涉及任何商业用途。所有内容均来源于互联网，请用户务必尊重原作者的版权。在使用本工具进行内容抓取时，请务必适度，避免对目标网站造成过大的访问压力和负载。请在下载后 24 小时内自行删除，并自觉遵守相关法律法规。对于用户因不当使用本项目而产生的任何版权纠纷、法律责任或对第三方网站造成的任何影响，本项目作者概不负责。**

## 安装

1.  **克隆仓库**

    ```bash
    git clone https://github.com/Breeze-mi/Novel-crawler.git
    cd Novel-crawler
    ```

2.  **创建并激活虚拟环境**

    ```bash
    python -m venv .venv
    # Windows
    .venv\Scripts\activate
    # macOS/Linux
    source .venv/bin/activate
    ```

3.  **安装依赖**

    ```bash
    pip install -r requirements.txt
    ```

## 使用方法

激活虚拟环境后，运行主程序：

```bash
python novel_reader_pro.py
```

程序启动后，你可以在界面中输入小说详情页网址进行抓取和阅读。

## 依赖

项目依赖于 `requirements.txt` 中列出的库，主要包括：

- `PySide6`: 用于构建图形用户界面。
- `requests`: 用于发送 HTTP 请求，抓取网页内容。
- `beautifulsoup4`: 用于解析 HTML 内容。
- `lxml`: 一个快速的 XML/HTML 处理库。

## 打包成可执行文件 (可选)

如果你想将项目打包成独立的可执行文件，可以使用 `PyInstaller`。首先安装 `PyInstaller`：

```bash
pip install pyinstaller
```

然后运行：

```bash
pyinstaller novel_reader_pro.spec
```

这将在 `dist` 目录下生成可执行文件。

---

# To-Do List

- [ ] 优化章节解析获取逻辑，提高解析准确性，解决章节丢失问题。
- [ ] 完善对笔趣阁二开网站的支持，增加对其他小说网站的解析逻辑和支持。
- [ ] 后期可以手动导入小说源站，增加对其他未被支持的小说网站的解析功能。
- [ ] 实现切换选择不同的小说源站，同时接入使用不同的小说源站的搜索功能。
- [ ] 优化界面布局，提升用户体验。
