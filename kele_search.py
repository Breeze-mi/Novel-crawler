"""
Cookie 方案
使用预设的 cf_clearance cookie 进行搜索
"""
import re
import time
import logging
import os
from typing import List, Dict
from urllib.parse import urljoin
import requests
from bs4 import BeautifulSoup


try:
    from PySide6.QtCore import QThread, Signal
    QT_AVAILABLE = True
except ImportError:
    QT_AVAILABLE = False


# 可乐读书搜索配置
KELE_SEARCH_URL = "https://www.keledushu.com/s.php"#搜索接口
KELE_BASE_URL = "https://www.keledushu.com"
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/142.0.0.0 Safari/537.36"

# Cloudflare clearance cookie（需要手动获取并填写）
# 获取方法：
# 1. 使用浏览器访问 https://www.keledushu.com
# 2. 完成 CF 验证
# 3. 打开开发者工具（F12） -> Application -> Cookies
# 4. 找到 cf_clearance，复制其值
# 5. 粘贴到下面的变量中，或保存到 cf_cookies.txt 文件
CF_CLEARANCE = ""  # 留空则优先使用 cf_cookies.txt 文件

# Cookie 配置文件路径
COOKIE_FILE = os.path.join(os.path.dirname(__file__), "cf_cookies.txt")
COOKIE_META_FILE = os.path.join(os.path.dirname(__file__), "cf_cookies_meta.json")


def load_cf_clearance():
    """
    加载 CF clearance cookie
    """
    # 1. 优先使用代码中配置的
    if CF_CLEARANCE and CF_CLEARANCE.strip():
        cookie = CF_CLEARANCE.strip()
        # 自动清理 cf_clearance= 前缀
        if cookie.startswith('cf_clearance='):
            cookie = cookie[len('cf_clearance='):]
        logging.info("使用代码中配置的 cf_clearance")
        return cookie
    
    # 2. 尝试从配置文件读取
    try:
        if os.path.exists(COOKIE_FILE):
            with open(COOKIE_FILE, 'r', encoding='utf-8') as f:
                cookie = f.read().strip()
                if cookie:
                    # 自动清理 cf_clearance= 前缀
                    if cookie.startswith('cf_clearance='):
                        cookie = cookie[len('cf_clearance='):]
                    logging.info(f"从配置文件加载 cf_clearance: {COOKIE_FILE}")
                    return cookie
    except Exception as e:
        logging.warning(f"读取 cookie 文件失败: {e}")
    
    return None


def get_cookie_info():
    """
    获取 Cookie 信息（保存时间、预计过期时间）
    返回: {'saved_time': timestamp, 'age_hours': float, 'estimated_expire_hours': float}
    """
    try:
        if os.path.exists(COOKIE_META_FILE):
            import json
            with open(COOKIE_META_FILE, 'r', encoding='utf-8') as f:
                meta = json.load(f)
                saved_time = meta.get('saved_time', 0)
                current_time = time.time()
                age_hours = (current_time - saved_time) / 3600
                
                # Cloudflare cookie 通常有效期：30分钟到24小时
                # 保守估计：12小时
                estimated_expire_hours = 12 - age_hours
                
                return {
                    'saved_time': saved_time,
                    'age_hours': age_hours,
                    'estimated_expire_hours': max(0, estimated_expire_hours)
                }
    except Exception as e:
        logging.warning(f"读取 cookie 元数据失败: {e}")
    
    return None


def save_cf_clearance(clearance):
    """保存 CF clearance cookie 到文件，并记录保存时间"""
    try:
        # 保存 cookie
        with open(COOKIE_FILE, 'w', encoding='utf-8') as f:
            f.write(clearance)
        
        # 保存元数据（时间戳）
        import json
        meta = {
            'saved_time': time.time(),
            'saved_time_readable': time.strftime('%Y-%m-%d %H:%M:%S')
        }
        with open(COOKIE_META_FILE, 'w', encoding='utf-8') as f:
            json.dump(meta, f, indent=2, ensure_ascii=False)
        
        logging.info(f"cf_clearance 已保存到: {COOKIE_FILE}")
        return True
    except Exception as e:
        logging.error(f"保存 cookie 文件失败: {e}")
        return False


def search_kele_books(keyword: str, timeout: int = 30) -> List[Dict]:
    """
    使用预设的 cf_clearance cookie 搜索可乐读书
    
    参数:
        keyword: 搜索关键词
        timeout: 超时时间（秒）
        
    返回:
        书籍列表: [{'title': str, 'author': str, 'url': str, 'latest': str}, ...]
    """
    if not keyword or not keyword.strip():
        return []
    
    keyword = keyword.strip()
    
    # 加载 cf_clearance
    cf_clearance = load_cf_clearance()
    if not cf_clearance:
        raise Exception(
            "未配置 cf_clearance cookie！\n\n"
            "请按以下步骤获取：\n"
            "1. 使用浏览器访问 https://www.keledushu.com\n"
            "2. 完成 Cloudflare 验证\n"
            "3. 按 F12 打开开发者工具\n"
            "4. 切换到 Application 标签\n"
            "5. 左侧选择 Cookies -> https://www.keledushu.com\n"
            "6. 找到 cf_clearance，复制其值\n"
            "7. 保存到 cf_cookies.txt 文件中\n"
            f"   文件位置: {COOKIE_FILE}"
        )
    
    try:
        logging.info(f"使用 cookie 搜索: keyword='{keyword}'")
        
        # 创建 session
        session = requests.Session()
        
        # 设置完整的请求头（完全匹配浏览器）
        session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/142.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7',
            'Accept-Language': 'zh-CN,zh;q=0.9,en-IN;q=0.8,en-US;q=0.7,en;q=0.6',
            'Accept-Encoding': 'gzip, deflate, br',  # 不包含 zstd（requests 库不支持自动解压）
            'Cache-Control': 'max-age=0',
            'Priority': 'u=0, i',  # 添加优先级头
            'Sec-Ch-Ua': '"Chromium";v="142", "Google Chrome";v="142", "Not_A Brand";v="99"',
            'Sec-Ch-Ua-Arch': '"x86"',
            'Sec-Ch-Ua-Bitness': '"64"',
            'Sec-Ch-Ua-Full-Version': '"142.0.7444.176"',
            'Sec-Ch-Ua-Full-Version-List': '"Chromium";v="142.0.7444.176", "Google Chrome";v="142.0.7444.176", "Not_A Brand";v="99.0.0.0"',
            'Sec-Ch-Ua-Mobile': '?0',
            'Sec-Ch-Ua-Model': '""',
            'Sec-Ch-Ua-Platform': '"Windows"',
            'Sec-Ch-Ua-Platform-Version': '"10.0.0"',
            'Sec-Fetch-Dest': 'document',
            'Sec-Fetch-Mode': 'navigate',
            'Sec-Fetch-Site': 'same-origin',
            'Sec-Fetch-User': '?1',
            'Upgrade-Insecure-Requests': '1',
        })
        
        # 设置 cookies
        session.cookies.set('cf_clearance', cf_clearance, domain='.keledushu.com', path='/')
        
        # 步骤1: 访问主页
        try:
            logging.info("访问主页中...")
            home_response = session.get(KELE_BASE_URL, timeout=10)
            logging.info(f"主页状态码: {home_response.status_code}")
            time.sleep(1)  # 等待一下
        except Exception as e:
            logging.warning(f"访问主页失败: {e}，继续尝试搜索...")
        
        # 步骤2: 设置Referer
        session.headers['Referer'] = KELE_BASE_URL + '/'
        session.headers['Origin'] = KELE_BASE_URL
        
        # 构造搜索数据
        data = {
            'type': 'articlename',
            's': keyword,
            'submit': ''
        }
        
        logging.info("发送搜索请求...")
        
        # 使用POST方式（更标准）
        session.headers['Content-Type'] = 'application/x-www-form-urlencoded'
        
        response = session.post(
            KELE_SEARCH_URL,
            data=data,
            timeout=timeout,
            allow_redirects=True
        )
        
        logging.info(f"最终响应状态码: {response.status_code}")
        
        # 检查是否成功
        if response.status_code == 403:
            raise Exception(
                "cf_clearance 已过期或无效！\n\n"
                "请重新获取 cookie：\n"
                "1. 清除浏览器缓存\n"
                "2. 重新访问 https://www.keledushu.com\n"
                "3. 完成验证后获取新的 cf_clearance\n"
                f"4. 更新 {COOKIE_FILE} 文件"
            )
        
        response.raise_for_status()
        
        # 解析结果
        html = response.text
        
        # 调试：检查响应内容
        logging.info(f"响应长度: {len(html)} 字符")
        logging.info(f"Content-Type: {response.headers.get('Content-Type')}")
        logging.info(f"Content-Encoding: {response.headers.get('Content-Encoding')}")
        
        # 检查响应前100字符（用于调试）
        preview = html[:200].replace('\n', ' ').replace('\r', ' ')
        logging.info(f"响应预览: {preview}")
        
        # 检查是否包含搜索结果标记
        if 'list-item' in html:
            logging.info("✓ 检测到 list-item 标记")
        if '搜索' in html:
            logging.info("✓ 检测到搜索关键词")
        if 'table' in html:
            logging.info("✓ 检测到 table 标签")
        
        # 检查是否真的是搜索结果
        if 'cloudflare' in html.lower() and 'list-item' not in html:
            raise Exception("cf_clearance 已过期，请重新获取")
        
        results = parse_search_results(html)
        
        logging.info(f"搜索完成: 找到 {len(results)} 本书")
        return results
        
    except Exception as e:
        logging.exception(f"搜索失败: {e}")
        raise


def parse_search_results(html: str) -> List[Dict]:
    """
    解析搜索结果页面
    
    返回:
        [{'title': str, 'author': str, 'url': str, 'latest': str}, ...]
    """
    soup = BeautifulSoup(html, 'html.parser')
    results = []
    
    try:
        # 可乐读书的搜索结果使用 table.list-item 结构
        tables = soup.find_all('table', class_='list-item')
        
        if tables:
            logging.info(f"找到 {len(tables)} 个搜索结果项")
            for table in tables:
                try:
                    # 提取书名和链接
                    title_link = table.find('div', class_='article').find('a')
                    if not title_link:
                        continue
                    
                    title = title_link.get_text(strip=True)
                    url = title_link.get('href', '')
                    if url and not url.startswith('http'):
                        url = urljoin(KELE_BASE_URL, url)
                    
                    # 提取作者
                    author = '未知'
                    author_link = table.find('a', href=re.compile(r'/author/'))
                    if author_link:
                        author = author_link.get_text(strip=True)
                    
                    # 提取最新章节
                    latest = ''
                    latest_span = table.find('span', class_='mr15', text=re.compile(r'最新：'))
                    if latest_span:
                        latest_link = latest_span.find('a')
                        if latest_link:
                            latest = latest_link.get_text(strip=True)
                    
                    results.append({
                        'title': title,
                        'author': author,
                        'url': url,
                        'latest': latest,
                        'status': ''
                    })
                    
                    logging.debug(f"解析到书籍: {title} - {author}")
                    
                except Exception as e:
                    logging.warning(f"解析单个结果失败: {e}")
                    continue
    
    except Exception as e:
        logging.exception(f"解析搜索结果失败: {e}")
    
    logging.info(f"最终解析到 {len(results)} 本书籍")
    return results


class KeleSearchThread(QThread):
    """可乐读书搜索线程"""
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


# 测试代码
if __name__ == "__main__":
    import sys
    
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s'
    )
    
    if len(sys.argv) > 1:
        keyword = " ".join(sys.argv[1:])
        print(f"搜索: {keyword}")
        try:
            results = search_kele_books(keyword)
            print(f"找到 {len(results)} 本书:")
            for i, book in enumerate(results, 1):
                print(f"{i}. {book['title']} - {book['author']} - {book['url']}")
        except Exception as e:
            print(f"搜索失败: {e}")
    else:
        print("用法: python kele_search.py <关键词>")
        print(f"\n或配置 cookie 文件: {COOKIE_FILE}")

