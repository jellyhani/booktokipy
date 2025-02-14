#!/usr/bin/env python
# -*- coding: utf-8 -*-

import os
import re
import time
import random
import logging
import json
import traceback
from datetime import datetime

# Selenium
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.action_chains import ActionChains
from selenium.common.exceptions import TimeoutException, NoSuchElementException

import undetected_chromedriver as uc

# HTML 파싱
from bs4 import BeautifulSoup
from urllib.parse import urljoin

# ePub 생성 (ebooklib)
try:
    from ebooklib import epub
except ImportError:
    print("[WARNING] ebooklib 미설치. ePub 생성 기능 사용 시 `pip install ebooklib` 필요.")
    epub = None


class DebugLogger:
    def __init__(self, log_dir='logs'):
        os.makedirs(log_dir, exist_ok=True)
        
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        debug_log_file = f'{log_dir}/debug_{timestamp}.txt'
        feedback_log_file = f'{log_dir}/feedback_{timestamp}.txt'
        
        self.debug_logger = logging.getLogger('debug')
        self.debug_logger.setLevel(logging.DEBUG)
        debug_handler = logging.FileHandler(debug_log_file, encoding='utf-8')
        debug_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
        self.debug_logger.addHandler(debug_handler)
        
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
        self.debug_logger.addHandler(console_handler)
        
        self.feedback_logger = logging.getLogger('feedback')
        self.feedback_logger.setLevel(logging.INFO)
        feedback_handler = logging.FileHandler(feedback_log_file, encoding='utf-8')
        feedback_handler.setFormatter(logging.Formatter('%(asctime)s - %(message)s'))
        self.feedback_logger.addHandler(feedback_handler)
        
        self.browser_info = {}

    def log_browser_info(self, driver):
        try:
            info = {
                'user_agent': driver.execute_script('return navigator.userAgent'),
                'plugins_length': driver.execute_script('return navigator.plugins.length'),
                'languages': driver.execute_script('return navigator.languages'),
                'webdriver_status': driver.execute_script('return navigator.webdriver'),
                'platform': driver.execute_script('return navigator.platform'),
                'hardware_concurrency': driver.execute_script('return navigator.hardwareConcurrency'),
                'memory': driver.execute_script('return navigator.deviceMemory'),
                'screen_info': driver.execute_script('return {width: screen.width, height: screen.height, depth: screen.colorDepth}')
            }
            self.browser_info = info
            self.debug_logger.info(f'브라우저 정보:\n{json.dumps(info, ensure_ascii=False, indent=2)}')
        except Exception as e:
            self.debug_logger.error(f'브라우저 정보 수집 실패: {str(e)}')

    def log_local_storage(self, driver, label=""):
        try:
            script = r"""
                let storeData = {};
                for (let i=0; i<localStorage.length; i++){
                    let k = localStorage.key(i);
                    storeData[k] = localStorage.getItem(k);
                }
                return storeData;
            """
            data = driver.execute_script(script)
            self.debug_logger.debug(f'[localStorage] {label}:\n{json.dumps(data, ensure_ascii=False, indent=2)}')
        except Exception as e:
            self.debug_logger.error(f"localStorage 로깅 실패 ({label}): {str(e)}")

    def log_session_storage(self, driver, label=""):
        try:
            script = r"""
                let storeData = {};
                for (let i=0; i<sessionStorage.length; i++){
                    let k = sessionStorage.key(i);
                    storeData[k] = sessionStorage.getItem(k);
                }
                return storeData;
            """
            data = driver.execute_script(script)
            self.debug_logger.debug(f'[sessionStorage] {label}:\n{json.dumps(data, ensure_ascii=False, indent=2)}')
        except Exception as e:
            self.debug_logger.error(f"sessionStorage 로깅 실패 ({label}): {str(e)}")

    def log_partial_page_source(self, driver, label="", length=500):
        try:
            ps = driver.page_source
            if len(ps) <= length*2:
                snippet = ps
            else:
                snippet = ps[:length] + "\n...\n" + ps[-length:]
            self.debug_logger.debug(f'[PageSource {label}] length={len(ps)}:\n{snippet}')
        except Exception as e:
            self.debug_logger.error(f"페이지 소스 로깅 실패 ({label}): {str(e)}")

    def log_request_info(self, driver):
        try:
            performance = driver.execute_script("return window.performance.getEntries()")
            relevant_info = [{
                'name': entry['name'],
                'duration': entry.get('duration', 0),
                'type': entry['entryType'],
                'size': entry.get('transferSize', 0)
            } for entry in performance]
            self.debug_logger.info(f'네트워크 요청 정보:\n{json.dumps(relevant_info, ensure_ascii=False, indent=2)}')
        except Exception as e:
            self.debug_logger.error(f'네트워크 정보 수집 실패: {str(e)}')
            
    def log_cloudflare_status(self, page_source):
        cloudflare_indicators = [
            'checking your browser',
            'ddos protection',
            'security check to access',
            'please wait...',
            'just a moment, please...',
            'please stand by, while we are checking your browser',
            'please enable cookies',
            '사람인지 확인',
            '보안을 검토'
        ]
        
        detected = []
        lower_html = page_source.lower()
        for keyword in cloudflare_indicators:
            if keyword in lower_html:
                detected.append(keyword)
        
        if detected:
            self.debug_logger.warning(f'클라우드플레어 감지: {", ".join(detected)}')
            return True
        return False
        
    def log_debug(self, message):
        self.debug_logger.debug(message)
        
    def log_error(self, message, error):
        err_trace = traceback.format_exc()
        self.debug_logger.error(f'{message}:\n{str(error)}\n{err_trace}')
        
    def log_feedback(self, message):
        self.feedback_logger.info(message)
        
    def log_performance(self, driver):
        try:
            metrics = driver.execute_script("""
                const navigation = performance.getEntriesByType('navigation')[0];
                const memory = performance.memory || {};
                return {
                    'page_load_time': navigation.loadEventEnd - navigation.startTime,
                    'dns_time': navigation.domainLookupEnd - navigation.domainLookupStart,
                    'connection_time': navigation.connectEnd - navigation.connectStart,
                    'ttfb': navigation.responseStart - navigation.requestStart,
                    'dom_interactive_time': navigation.domInteractive - navigation.startTime,
                    'used_memory': memory.usedJSHeapSize,
                    'total_memory': memory.totalJSHeapSize
                }
            """)
            self.debug_logger.info(f'성능 메트릭:\n{json.dumps(metrics, ensure_ascii=False, indent=2)}')
        except Exception as e:
            self.debug_logger.error(f'성능 메트릭 수집 실패: {str(e)}')


class CloudflareBypass:
    def __init__(self):
        self.driver = None
        self.logger = DebugLogger()
        
    def _create_driver(self):
        self.logger.log_debug("브라우저 드라이버 생성 시작")
        
        options = uc.ChromeOptions()
        
        # -------- [추가] 최대한 빠르게 로드하기 위한 설정 --------
        # 1) headless 모드 (수동 캡차가 없다면 True 권장)
        # options.add_argument('--headless')
        # options.add_argument('--disable-gpu')
        
        # 2) pageLoadStrategy='eager' : DOMContentLoaded 시점에 반환
        options.page_load_strategy = 'eager'
        
        # -------- [기존 설정들] --------
        options.add_argument('--profile-directory=Default')
        options.add_argument('--user-data-dir=./chrome_profile')
        options.add_argument('--disable-dev-shm-usage')
        options.add_argument('--no-sandbox')
        options.add_argument('--disable-setuid-sandbox')
        options.add_argument('--disable-infobars')
        options.add_argument('--disable-logging')
        options.add_argument('--disable-login-animations')
        options.add_argument('--no-default-browser-check')
        options.add_argument('--no-first-run')
        options.add_argument('--ignore-certificate-errors')
        options.add_argument('--force-webrtc-ip-handling-policy=disable_non_proxied_udp')
        options.add_argument('--disable-blink-features=AutomationControlled')
        
        options.add_argument('--start-maximized')
        options.add_argument('--lang=ko-KR')
        
        prefs = {
            'intl.accept_languages': 'ko-KR,ko,en-US,en',
            'profile.default_content_setting_values.notifications': 2,
            'credentials_enable_service': False,
            'profile.password_manager_enabled': False
        }
        options.add_experimental_option('prefs', prefs)
        
        try:
            driver = uc.Chrome(options=options, use_subprocess=True)
            self.logger.log_debug("브라우저 드라이버 생성 완료")
            
            # [중요] 이미지/CSS/폰트 등 리소스 차단 (CDP)
            try:
                block_urls = [
                    '*.png','*.jpg','*.jpeg','*.gif','*.svg','*.ico',
                    '*.css','*.woff','*.woff2','*.ttf','*.eot',
                    '*.mp4','*.webm','*.ogg',
                    # 광고/analytics 도메인 추가 가능
                ]
                driver.execute_cdp_cmd("Network.setBlockedURLs", {"urls": block_urls})
                self.logger.log_debug("이미지/폰트/CSS 등 리소스 차단 설정 완료")
            except Exception as e:
                self.logger.log_debug(f"리소스 차단 설정 실패: {e}")
            
            return driver
        except Exception as e:
            self.logger.log_error("브라우저 드라이버 생성 실패", e)
            raise

    def _inject_stealth_scripts(self):
        self.logger.log_debug("스텔스 스크립트 주입 시작")
        stealth_script = '''
            delete Object.getPrototypeOf(navigator).webdriver;
        '''
        try:
            self.driver.execute_cdp_cmd('Page.addScriptToEvaluateOnNewDocument', {
                'source': stealth_script
            })
            self.logger.log_debug("스텔스 스크립트 주입 완료")
        except Exception as e:
            self.logger.log_error("스텔스 스크립트 주입 실패", e)
            raise

    def emulate_human_behavior(self):
        """
        - 속도 향상을 위해, 사용자 행동 에뮬레이션(마우스이동/스크롤)은 최소화하거나 생략 가능
        - 여기서는 간단히 스크롤 몇 번만
        """
        try:
            self.logger.log_debug("사용자 행동 에뮬레이션 시작")
            scroll_positions = [200, 500]  # 줄이거나 생략
            for pos in scroll_positions:
                self.driver.execute_script(f"window.scrollTo(0, {pos});")
                time.sleep(0.5)
            
            self.logger.log_debug("사용자 행동 에뮬레이션 완료")
        except Exception as e:
            self.logger.log_error("사용자 행동 에뮬레이션 실패", e)

    def handle_turnstile(self):
        """Turnstile 등 체크박스가 있을 경우 처리 (시간 단축 위해 1~2초 대기)"""
        try:
            self.logger.log_debug("Turnstile 챌린지 처리 시작")
            time.sleep(2)
            
            iframes = self.driver.find_elements(By.TAG_NAME, "iframe")
            found_iframe = False
            
            for iframe in iframes:
                src = iframe.get_attribute("src") or ""
                if "turnstile" in src.lower() or "challenge" in src.lower() or "cloudflare" in src.lower():
                    self.logger.log_debug(f"Turnstile iframe: {src}")
                    found_iframe = True
                    self.driver.switch_to.frame(iframe)
                    
                    try:
                        clickable = WebDriverWait(self.driver, 3).until(
                            EC.element_to_be_clickable((By.XPATH, "//input[@type='checkbox']"))
                        )
                        clickable.click()
                        time.sleep(2)
                    except:
                        pass
                    self.driver.switch_to.default_content()
                    break
            
            if not found_iframe:
                return False

            time.sleep(1)
            page_source = self.driver.page_source.lower()
            if any(w in page_source for w in ["checking your browser","사람인지 확인","보안을 검토","security check","just a moment"]):
                self.logger.log_debug("Turnstile 여전히 감지됨")
                return False
            else:
                self.logger.log_debug("Turnstile 통과됨!")
                return True
        except Exception as e:
            self.logger.log_error("Turnstile 실패", e)
            return False

    def _wait_for_js_challenge(self, timeout=8):
        self.logger.log_debug("JS Challenge 대기 시작")
        start = time.time()
        while time.time() - start < timeout:
            page_source = self.driver.page_source.lower()
            if not any(word in page_source for word in [
                "checking your browser","사람인지 확인","보안을 검토","security check","just a moment","please wait"
            ]):
                self.logger.log_debug("JS Challenge 통과됨")
                return True
            time.sleep(1)
        return False

    def verify_page_loaded(self):
        try:
            WebDriverWait(self.driver, 5).until(
                lambda d: ( len(d.find_elements(By.CSS_SELECTOR, "body"))>0 )
            )
            return True
        except:
            return False

    def _wait_for_page_load(self, timeout=15):
        self.logger.log_debug(f"페이지 로드 대기 (타임아웃: {timeout}초)")
        start_time = time.time()
        
        while time.time() - start_time < timeout:
            ps = self.driver.page_source.lower()
            if any(w in ps for w in ["checking your browser","사람인지 확인","보안을 검토","security check","just a moment","please wait"]):
                self.logger.log_debug("보안체크 감지 -> emulate + turnstile")
                self.emulate_human_behavior()
                if self.handle_turnstile():
                    time.sleep(1)
                    if self._wait_for_js_challenge(timeout=5):
                        if self.verify_page_loaded():
                            self.logger.log_debug("보안체크 해소됨 => 로드완료")
                        return True
                else:
                    # turnstile 못찾음 or 실패
                    time.sleep(2)
            else:
                # 보안문구 없음 => 로드끝 추정
                if self.verify_page_loaded():
                    self.logger.log_debug("페이지 정상 로드됨")
                return True
        
        self.logger.log_debug("페이지 로드 대기 타임아웃")
        return False

    def visit_page(self, url, max_retries=2):
        for attempt in range(max_retries):
            try:
                if not self.driver:
                    self.logger.log_debug("브라우저 초기화 시작")
                    self.driver = self._create_driver()
                    self._inject_stealth_scripts()
                    self.logger.log_browser_info(self.driver)
                
                self.logger.log_debug(f"페이지 방문 시도: {url} (시도 {attempt+1}/{max_retries})")
                self.driver.get(url)
                
                if self._wait_for_page_load():
                    self.logger.log_feedback("Cloudflare 우회 성공")
                    return True
                
                self.logger.log_feedback(f"클라우드플레어 우회 실패 (시도 {attempt+1}/{max_retries})")
                if attempt < max_retries - 1:
                    self.driver.delete_all_cookies()
                    self.driver.execute_script("window.localStorage.clear();")
                    self.driver.execute_script("window.sessionStorage.clear();")
                    time.sleep(3)
            except Exception as e:
                self.logger.log_error(f"페이지 방문 오류 (시도 {attempt+1})", e)
                if attempt < max_retries - 1:
                    if self.driver:
                        self.driver.quit()
                        self.driver = None
                    time.sleep(3)
        return False

    def get_page_content(self):
        try:
            if self.driver:
                return self.driver.page_source
        except Exception as e:
            self.logger.log_error("페이지 콘텐츠 가져오기 실패", e)
        return None

    def close(self):
        try:
            if self.driver:
                self.driver.quit()
                self.logger.log_debug("브라우저 종료됨")
        except Exception as e:
            self.logger.log_error("브라우저 종료 실패", e)
        finally:
            self.driver = None


class BookTokiCrawler:
    def __init__(self, bypasser: CloudflareBypass, start_url: str):
        self.bypasser = bypasser
        self.start_url = start_url
        self.info = {}
        self.base_folder = ""

    def sanitize_filename(self, name):
        return re.sub(r'[\\/:*?"<>|]', '_', name)

    def create_folder(self, folder_name):
        if not os.path.exists(folder_name):
            os.makedirs(folder_name, exist_ok=True)

    def wait_for_user_captcha(self):
        print("\n[CAPTCHA DETECTED] 브라우저에서 직접 해결 후 엔터")
        input("[Press Enter after captcha solved] >> ")

    def check_and_wait_captcha(self):
        html = self.bypasser.get_page_content()
        if not html:
            return
        soup = BeautifulSoup(html, "html.parser")
        form = soup.select_one("div.form-body > form.form")
        if form:
            action = form.get("action", "").lower()
            if "captcha_check.php" in action:
                self.wait_for_user_captcha()

    def run_main_page(self):
        ok = self.bypasser.visit_page(self.start_url)
        if not ok:
            print("[ERROR] 메인 페이지 우회 실패.")
            return False
        self.check_and_wait_captcha()
        return True

    def get_text_after_icon(self, icon_elem):
        if not icon_elem:
            return ""
        nxt = icon_elem
        while nxt:
            nxt = nxt.next_sibling
            if nxt and nxt.string and nxt.string.strip():
                return nxt.string.strip()
        return ""

    def parse_main_info(self):
        html = self.bypasser.get_page_content()
        if not html:
            print("[ERROR] 소스 없음")
            return None
        
        soup = BeautifulSoup(html, "html.parser")
        col_sm_8 = soup.select_one("div.col-sm-8")
        if not col_sm_8:
            print("[ERROR] div.col-sm-8 없음.")
            return None
        
        view_contents = col_sm_8.select("div.view-content")
        if not view_contents:
            print("[ERROR] view-content 없음.")
            return None
        
        title = ""
        if view_contents:
            span_title = view_contents[0].select_one("span")
            if span_title:
                title = span_title.get_text(strip=True)

        company = ""
        genre = ""
        writer = ""

        if len(view_contents) > 1:
            second_vc = view_contents[1]
            building_i = second_vc.select_one("i.fa.fa-building-o")
            company = self.get_text_after_icon(building_i)
            
            tag_i = second_vc.select_one("i.fa.fa-tag")
            genre = self.get_text_after_icon(tag_i)
            
            user_i = second_vc.select_one("i.fa.fa-user")
            writer = self.get_text_after_icon(user_i)

        info = {
            "title": title,
            "company": company,
            "genre": genre,
            "writer": writer,
        }
        print(f"[INFO] 메인 정보: {info}")
        return info

    def make_base_folder(self, info):
        w = info.get("writer","NoWriter")
        g = info.get("genre","NoGenre")
        t = info.get("title","NoTitle")
        folder_name = f"[{w}][{g}][{t}]"
        folder_name = self.sanitize_filename(folder_name)
        self.create_folder(folder_name)
        return folder_name

    def format_text_for_readability(self, text, max_line_length=80):
        lines = text.splitlines()
        formatted_lines = []
        
        blank_count = 0
        for line in lines:
            line = line.rstrip()
            if not line.strip():
                blank_count += 1
                if blank_count <= 1:
                    formatted_lines.append("")
            else:
                blank_count = 0
                while len(line) > max_line_length:
                    formatted_lines.append(line[:max_line_length])
                    line = line[max_line_length:]
                formatted_lines.append(line)
        
        return "\n".join(formatted_lines)

    def parse_episode_list(self, base_folder):
        html = self.bypasser.get_page_content()
        if not html:
            print("[ERROR] 메인 페이지 소스 없음.")
            return
        soup = BeautifulSoup(html, "html.parser")
        serial_form = soup.select_one("form#serial-move")
        if not serial_form:
            print("[ERROR] form#serial-move 없음.")
            return
        
        list_body = serial_form.select_one("ul.list-body")
        if not list_body:
            print("[ERROR] ul.list-body 없음.")
            return
        
        li_list = list_body.select("li.list-item")
        if not li_list:
            print("[INFO] 회차 항목이 없음.")
            return
        
        for li in li_list:
            wr_num = li.select_one("div.wr-num")
            episode_no = wr_num.get_text(strip=True) if wr_num else ""
            
            a_tag = li.select_one("div.wr-subject > a")
            if not a_tag:
                continue
            
            for sp in a_tag.select("span"):
                sp.extract()
            ep_title = a_tag.get_text(strip=True)
            href = a_tag.get("href")
            if not href:
                continue
            
            abs_url = urljoin(self.bypasser.driver.current_url, href)
            print(f"[EPISODE] No:{episode_no}, Title:{ep_title}, URL:{abs_url}")
            
            ep_folder = os.path.join(base_folder, self.sanitize_filename(f"{episode_no}회"))
            self.create_folder(ep_folder)
            
            self.crawl_episode_content(abs_url, ep_folder, episode_no, ep_title)

    def crawl_episode_content(self, episode_url, ep_folder, ep_no, ep_title):
        # 빠른 접근
        ok = self.bypasser.visit_page(episode_url)
        if not ok:
            print(f"[ERROR] 회차 우회 실패: {episode_url}")
            return
        
        self.check_and_wait_captcha()
        
        html = self.bypasser.get_page_content()
        if not html:
            print(f"[ERROR] 회차 소스 없음: {episode_url}")
            return
        
        soup = BeautifulSoup(html, "html.parser")
        content_div = soup.select_one("div#novel_content")
        if not content_div:
            print("[ERROR] div#novel_content 없음.")
            return
        
        raw_text = content_div.get_text("\n", strip=True)
        text_data = self.format_text_for_readability(raw_text, max_line_length=80)
        
        filename = f"{ep_no}회차.txt"
        safe_filename = self.sanitize_filename(filename)
        full_path = os.path.join(ep_folder, safe_filename)
        
        with open(full_path, "w", encoding="utf-8") as f:
            f.write(text_data)
        
        print(f"[SAVE] {full_path} 저장 완료.")

    def create_epub_from_txt(self):
        if epub is None:
            print("[ERROR] ebooklib 미설치. ePub 기능 사용 시 pip install ebooklib 필요.")
            return
        
        w = self.info.get("writer","NoWriter")
        g = self.info.get("genre","NoGenre")
        t = self.info.get("title","NoTitle")
        
        if not self.base_folder:
            print("[ERROR] base_folder가 없음")
            return
        
        book = epub.EpubBook()
        book.set_identifier('id1234')
        book.set_title(t if t else "제목없음")
        book.set_language('ko')
        book.add_author(w if w else "작가미상")

        spine = ['nav']
        subdirs = sorted(os.listdir(self.base_folder))
        chap_num = 1

        for sub in subdirs:
            sub_path = os.path.join(self.base_folder, sub)
            if not os.path.isdir(sub_path):
                continue
            txt_files = [f for f in os.listdir(sub_path) if f.endswith('.txt')]
            if not txt_files:
                continue
            
            txt_file = txt_files[0]
            txt_path = os.path.join(sub_path, txt_file)
            with open(txt_path, 'r', encoding='utf-8') as f:
                content_text = f.read()
            
            chapter_title = f"{sub}"
            c = epub.EpubHtml(title=chapter_title, file_name=f'chap_{chap_num}.xhtml', lang='ko')
            c.content = f"<h2>{chapter_title}</h2><pre>{content_text}</pre>"
            book.add_item(c)
            spine.append(c)
            chap_num += 1

        book.toc = spine[1:]
        book.spine = spine
        book.add_item(epub.EpubNcx())
        book.add_item(epub.EpubNav())

        epub_name = self.sanitize_filename(f"{self.base_folder}.epub")
        epub_path = os.path.join(self.base_folder, epub_name)
        epub.write_epub(epub_path, book, {})
        print(f"[EPUB] ePub 생성 완료: {epub_path}")

    def run(self):
        if not self.run_main_page():
            return
        
        self.info = self.parse_main_info()
        if not self.info:
            return
        
        self.base_folder = self.make_base_folder(self.info)
        print(f"[FOLDER] {self.base_folder} 생성.")
        
        self.parse_episode_list(self.base_folder)
        print("[DONE] 모든 회차 크롤 완료.")

        self.create_epub_from_txt()
        print("[DONE] ePub 생성까지 완료.")


def main():
    url = input("접속할 URL을 입력하세요: ").strip()
    if not url:
        print("URL이 입력되지 않았습니다. 종료합니다.")
        return
    
    bypasser = CloudflareBypass()
    crawler = BookTokiCrawler(bypasser, url)
    crawler.run()
    
    print("\n[INFO] 작업이 완료되었습니다.")
    bypasser.close()

if __name__ == "__main__":
    main()
