from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
import logging
import os
import time
import pickle
from pathlib import Path
from typing import List
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager
from selenium.common.exceptions import TimeoutException, NoSuchElementException, WebDriverException
from datetime import datetime
from selenium.webdriver.common.action_chains import ActionChains
import re

class NaverBlogPoster:
    def __init__(self, config: dict):
        self.config = config
        self.logger = logging.getLogger(__name__)
        self.username = os.getenv('NAVER_USERNAME')
        self.password = os.getenv('NAVER_PASSWORD')
        self.driver = None
        self.cookies_file = Path(__file__).parent.parent / 'config' / 'naver_cookies.pkl'
        
        if not self.username or not self.password:
            self.logger.error("Naver credentials not found in environment variables")
            raise ValueError("네이버 로그인 정보가 환경변수에 설정되지 않았습니다.")

    def setup_driver(self):
        """Selenium WebDriver를 초기화합니다."""
        try:
            options = webdriver.ChromeOptions()
            options.add_argument('--no-sandbox')
            options.add_argument('--start-maximized')
            options.add_argument('--disable-dev-shm-usage')
            options.add_argument('--disable-blink-features=AutomationControlled')
            options.add_experimental_option("excludeSwitches", ["enable-automation"])
            options.add_experimental_option('useAutomationExtension', False)
            
            # User-Agent 설정
            options.add_argument('--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/92.0.4515.159 Safari/537.36')
            
            # ChromeDriver 경로 직접 지정 (이 경로는 실제 환경에 맞게 조정 필요)
            # 사용자의 원래 코드에서는 __file__ 기준이었으나, 메인 스크립트 위치에 따라 달라질 수 있음.
            # 일단 원래 코드를 유지하되, 실행 시 경로 문제가 발생할 수 있음을 인지해야 함.
            chromedriver_path = Path(__file__).parent / 'chromedriver' / 'chromedriver-win64' / 'chromedriver.exe' 
            if not chromedriver_path.exists():
                print(f"✗ ChromeDriver를 다음 경로에서 찾을 수 없습니다: {chromedriver_path}")
                print("! webdriver-manager를 사용하여 자동으로 다운로드/설치합니다.")
                try:
                    service = Service(ChromeDriverManager().install())
                except Exception as dm_e:
                    print(f"✗ webdriver-manager 실행 중 오류: {dm_e}")
                    print("✗ ChromeDriver 자동 설치 실패. 수동 설치 또는 경로 확인이 필요합니다.")
                    return False
            else:
                 service = Service(executable_path=str(chromedriver_path))
                 
            self.driver = webdriver.Chrome(service=service, options=options)
            self.driver.set_page_load_timeout(60) # 시간 약간 늘림
            
            # JavaScript 코드 실행하여 웹드라이버 감지 방지
            self.driver.execute_cdp_cmd('Page.addScriptToEvaluateOnNewDocument', {
                'source': '''
                    Object.defineProperty(navigator, 'webdriver', {
                        get: () => undefined
                    })
                '''
            })
            
            print("✓ 웹드라이버 설정 완료")
            return True
        except Exception as e:
            self.logger.error(f"Failed to setup WebDriver: {e}", exc_info=True)
            print(f"✗ 웹드라이버 설정 실패: {str(e)}")
            return False

    def login(self):
        """네이버에 로그인합니다."""
        try:
            # 네이버 로그인 페이지로 이동
            print("- 네이버 로그인 페이지로 이동 중...")
            self.driver.get('https://nid.naver.com/nidlogin.login')
            WebDriverWait(self.driver, 10).until(
                EC.presence_of_element_located((By.ID, 'id'))
            )
            time.sleep(1)
            
            # JavaScript를 통한 로그인 정보 입력
            print("- 로그인 정보 입력 중...")
            self.driver.execute_script(
                f"document.getElementById('id').value='{self.username}'"
            )
            time.sleep(0.5)
            
            self.driver.execute_script(
                f"document.getElementById('pw').value='{self.password}'"
            )
            time.sleep(0.5)
            
            # 로그인 버튼 클릭
            print("- 로그인 버튼 클릭 중...")
            login_button = WebDriverWait(self.driver, 10).until(
                EC.element_to_be_clickable((By.ID, 'log.login')) # ID가 log.login 인 경우가 많음
            )
            login_button.click()
            
            # 로그인 성공 확인 (URL 변경 또는 특정 요소 확인)
            try:
                print("- 로그인 성공 확인 중...")
                WebDriverWait(self.driver, 15).until(
                    lambda d: 'nid.naver.com/nidlogin.login' not in d.current_url or 
                              d.find_elements(By.CSS_SELECTOR, "a[href*='logout']") # 로그아웃 링크 확인
                )
                # 2단계 인증 확인
                current_url = self.driver.current_url
                if "auth" in current_url or "device" in current_url:
                    print("! 2단계 인증 또는 새 기기 등록 페이지로 이동되었습니다.")
                    print("? 브라우저에서 직접 인증을 완료하고 Enter 키를 눌러주세요...")
                    input("  인증 완료 후 여기에서 Enter를 누르세요: ") # 사용자 대기
                    # 다시 로그인 상태 확인
                    if not self.check_login_status():
                         print("✗ 2단계 인증 후에도 로그인이 확인되지 않습니다.")
                         return False
                     
                print("✓ 네이버 로그인 성공")
                return True
            except TimeoutException:
                print("✗ 로그인 실패: 아이디/비밀번호 오류 또는 페이지 로딩 시간 초과.")
                # 오류 메시지 확인 시도
                try:
                    error_msg = self.driver.find_element(By.CSS_SELECTOR, ".error_message, .error_text").text
                    print(f"  오류 메시지: {error_msg}")
                except NoSuchElementException:
                    pass 
                return False
                
        except Exception as e:
            self.logger.error(f"Login failed: {e}", exc_info=True)
            print(f"✗ 로그인 중 예외 발생: {str(e)}")
            return False

    def check_login_status(self):
        """현재 로그인 상태를 확인합니다."""
        try:
            print("- 로그인 상태 확인 중...")
            # 네이버 메인 또는 블로그 홈 같이 로그인 상태 확인 용이한 곳으로 이동
            self.driver.get('https://www.naver.com') 
            time.sleep(2)
            
            # 로그인 여부 확인 (로그아웃 버튼 또는 사용자 이름 요소 등)
            try:
                # Case 1: 로그아웃 링크 확인 (일반적인 네이버 페이지)
                 logout_link = self.driver.find_element(By.CSS_SELECTOR, "a[href*='nid.naver.com/nidlogin.logout']")
                 if logout_link:
                     print("- 로그아웃 링크 확인됨 (로그인 상태)")
                     return True
            except NoSuchElementException:
                 pass # 다음 케이스 시도
                 
            try:
                # Case 2: 블로그 홈에서 프로필 영역 확인
                self.driver.get('https://blog.naver.com/gongnyangi')
                time.sleep(2)
                profile_area = self.driver.find_element(By.ID, 'blog-profile') # ID는 실제 블로그 구조에 따라 다를 수 있음
                if profile_area:
                    print("- 블로그 프로필 영역 확인됨 (로그인 상태)")
                    return True
            except NoSuchElementException:
                 pass

            print("- 로그인 상태 아님")
            return False
            
        except Exception as e:
            self.logger.warning(f"Login status check failed: {e}", exc_info=True)
            print(f"⚠ 로그인 상태 확인 중 오류: {e}")
            return False # 오류 발생 시 로그인 안된 것으로 간주
            
    def create_post(self, title: str, content: str, tags: List[str]) -> bool:
        """네이버 블로그에 글을 포스팅합니다. (사용자 초기 제공 코드 기반 + 카테고리 ID 21 수정)"""
        if not self.driver:
            self.logger.error("WebDriver가 초기화되지 않았습니다.")
            print("✗ 포스팅 시작 불가: 웹드라이버 없음")
            return False

        if not self.check_login_status():
            print("✗ 포스팅 시작 불가: 로그인 상태 아님. 재로그인 시도...")
            if not self.login():
                print("✗ 재로그인 실패. 포스팅을 진행할 수 없습니다.")
                return False
            print("✓ 재로그인 성공. 포스팅 계속 진행.")
            time.sleep(3)

        try:
            # 글쓰기 페이지로 이동 (Use the original URL approach)
            print("- 글쓰기 페이지로 이동 중 (postwrite)...")
            self.driver.get("https://blog.naver.com/gongnyangi/postwrite")
            print("- 페이지 로딩 대기 (10초)...") # Increased wait slightly
            time.sleep(10)
            print(f"현재 URL: {self.driver.current_url}")

            # 이전 글 작성 확인 팝업 처리 (Original code style)
            try:
                print("- 이전 글 팝업 확인 중...")
                WebDriverWait(self.driver, 5).until(
                     EC.presence_of_element_located((By.CLASS_NAME, 'se-popup-button-text')) # Original selector
                )
                cancel_buttons = self.driver.find_elements(By.CLASS_NAME, 'se-popup-button-text')
                if cancel_buttons:
                    for button in cancel_buttons:
                        if button.text == '취소':
                            button.click()
                            time.sleep(3)
                            print("- 이전 글 '취소' 처리 완료")
                            break
            except TimeoutException:
                 print("- 이전 글 팝업 없음 - 계속 진행")
            except Exception as e:
                print(f"- 이전 글 팝업 처리 중 오류 (무시하고 계속): {e}")

            # 도움말 닫기 버튼 처리 (Original code style)
            time.sleep(2)
            try:
                print("- 도움말 팝업 확인 중...")
                help_buttons = self.driver.find_elements(By.TAG_NAME, 'button')
                for button in help_buttons:
                     try:
                         # Using a more flexible check for close buttons
                         button_class = button.get_attribute('class') or ''
                         button_text = button.text
                         if ('닫기' in button_class or 'close' in button_class.lower() or '닫기' in button_text) and button.is_displayed() and button.is_enabled():
                             button.click()
                             time.sleep(2)
                             print("- 도움말 닫기 완료")
                             break
                     except Exception: # Catch potential StaleElementReferenceException etc.
                         continue
            except Exception as e:
                print(f"- 도움말 팝업 처리 중 오류 (무시하고 계속): {e}")

            # 제목 입력 (Original code style with ActionChains)
            try:
                print("- 제목 영역 찾는 중 (Original Placeholder Selector)...")
                # Using the original placeholder selector approach
                title_placeholder_selector = 'span.se-placeholder.__se_placeholder'
                title_area = WebDriverWait(self.driver, 10).until( # Increased wait
                    EC.element_to_be_clickable((By.CSS_SELECTOR, title_placeholder_selector))
                )
                print("- 제목 영역 찾음 (Placeholder)")
                title_area.click()
                time.sleep(1)
                print("- 제목 입력 중 (ActionChains)...")
                actions = ActionChains(self.driver)
                actions.send_keys(title).perform()
                print("- 제목 입력 완료")
                time.sleep(1)
                print("- Enter 키 입력 (본문 이동)")
                actions.send_keys(Keys.ENTER).perform()
                time.sleep(3) # 본문 영역 활성화 대기
            except Exception as e:
                print(f"✗ 제목 입력 실패: {e}")
                # Fallback: Try direct input if placeholder fails
                try:
                     print("- 제목 입력 Fallback 시도 (직접 입력)...")
                     title_input_selector = '.se-title-input .se-text-paragraph' # More direct selector
                     title_actual_input = WebDriverWait(self.driver, 5).until(
                         EC.element_to_be_clickable((By.CSS_SELECTOR, title_input_selector))
                     )
                     title_actual_input.click() # Ensure focus
                     time.sleep(0.5)
                     title_actual_input.send_keys(title)
                     print("- 제목 입력 Fallback 성공")
                     time.sleep(1)
                     # Enter to move to body
                     ActionChains(self.driver).send_keys(Keys.ENTER).perform()
                     time.sleep(3)
                except Exception as e_fallback:
                     print(f"✗ 제목 입력 최종 실패: {e_fallback}")
                     return False

            # 본문 입력 (Original code style with ActionChains and small delay)
            try:
                print("- 본문 문자 단위 입력 시작 (ActionChains)...")
                # Using original selector
                editor_body_selector = 'div.se-component-content p.se-text-paragraph'
                try:
                    # Ensure focus on the body
                    editor_element = WebDriverWait(self.driver, 10).until(
                        EC.element_to_be_clickable((By.CSS_SELECTOR, editor_body_selector))
                    )
                    # Use JS click for potentially obscured elements
                    self.driver.execute_script("arguments[0].click();", editor_element) 
                    print("- 본문 영역 포커스 확보 완료")
                    time.sleep(1)
                except Exception as focus_e:
                    print(f"- 본문 영역 포커스 실패 (무시하고 입력 시도): {focus_e}")

                actions = ActionChains(self.driver)
                cleaned_content = content.strip()
                total_chars = len(cleaned_content)
                print(f"- 총 {total_chars} 문자 입력 예정")
                
                # Use the character-by-character input from original code
                for i, char in enumerate(cleaned_content):
                    if char == '\n':
                        actions.send_keys(Keys.ENTER)
                    else:
                        actions.send_keys(char)
                    
                    actions.perform()
                    time.sleep(0.01) # Original small delay
                    
                    if (i + 1) % 100 == 0 or (i + 1) == total_chars:
                        print(f"  ... {i+1}/{total_chars} 문자 입력 완료")
                        
                print("- 모든 본문 문자 입력 완료.")
                time.sleep(3)

            except Exception as e:
                print(f"✗ 본문 입력 중 오류 발생: {e}")
                return False

            # 첫 번째 발행 버튼 클릭 (Original code style - JS with fallback)
            time.sleep(3)
            try:
                print("- 첫 번째 발행 버튼 클릭 시도 (JavaScript - Original Selector)...")
                # Original JS selector attempt
                publish_script = """
                    var publishBtn = document.querySelector('button.publish_btn__m9KHH');
                    if (publishBtn) {
                        publishBtn.click();
                        return true;
                    } else {
                        // Try data-testid as fallback within JS
                        publishBtn = document.querySelector('button[data-testid="publishButton"]');
                        if (publishBtn) {
                           publishBtn.click();
                           return true;
                        }
                        console.error('Publish button not found!');
                        return false;
                    }
                """
                if self.driver.execute_script(publish_script):
                    print("- 첫 번째 발행 버튼 클릭 완료 (JS). 발행 설정 창 대기 (5초)...")
                    time.sleep(5)
                else:
                    print("✗ 첫 번째 발행 버튼을 JavaScript로 찾거나 클릭할 수 없습니다. Selenium 시도...")
                    # Fallback to Selenium click using data-testid (more reliable)
                    try:
                         publish_button_selector = 'button[data-testid="publishButton"]'
                         publish_button = WebDriverWait(self.driver, 5).until(
                             EC.element_to_be_clickable((By.CSS_SELECTOR, publish_button_selector))
                         )
                         publish_button.click()
                         print("- 첫 번째 발행 버튼 클릭 완료 (Selenium). 발행 설정 창 대기 (5초)...")
                         time.sleep(5)
                    except Exception as e_fallback:
                         print(f"✗ 첫 번째 발행 버튼 클릭 최종 실패: {e_fallback}")
                         return False

            except Exception as e:
                print(f"✗ 첫 번째 발행 버튼 처리 중 오류: {e}")
                return False

            # --- 발행 설정 (카테고리 ID 21, 태그 등 - Original Style) ---
            try:
                print("- 발행 설정 창 로딩 확인 (기존 data-testid 사용)...")
                WebDriverWait(self.driver, 10).until(
                    EC.visibility_of_element_located((By.CSS_SELECTOR, 'button[data-testid="seOnePublishBtn"]'))
                )
                print("- 발행 설정 창 로딩 완료.")
                time.sleep(1)

                # --- 카테고리 선택 (Reverted to name-based selection) ---
                try:
                    category_target_label = '네이버트렌드' # <<< 확인 및 수정 필요 (원하는 카테고리 이름)
                    print(f"- 카테고리 선택 시도 (이름: '{category_target_label}')...")
                    
                    # 1. Click dropdown
                    try:
                        category_button_selector = 'button.selectbox_button__jb1Dt' # Original selector attempt
                        category_button = WebDriverWait(self.driver, 10).until(
                            EC.element_to_be_clickable((By.CSS_SELECTOR, category_button_selector))
                        )
                    except TimeoutException:
                        print(f"- 카테고리 버튼 원본 선택자 실패, data-testid 시도...")
                        category_button_selector = 'button[data-testid="categoryButton"]' # Fallback
                        category_button = WebDriverWait(self.driver, 10).until(
                            EC.element_to_be_clickable((By.CSS_SELECTOR, category_button_selector))
                        )
                    self.driver.execute_script("arguments[0].click();", category_button)
                    time.sleep(2)

                    # 2. Click the label containing the target name
                    # Using XPath to find a label whose text *contains* the target name
                    category_label_selector = f'//div[contains(@class, "option_list")]//label[contains(., "{category_target_label}")]' 
                    category_label = WebDriverWait(self.driver, 10).until(
                        EC.element_to_be_clickable((By.XPATH, category_label_selector))
                    )
                    print(f"- 카테고리 '{category_target_label}' 찾음 (XPath 사용)")
                    self.driver.execute_script("arguments[0].click();", category_label)
                    print(f"- 카테고리 '{category_target_label}' 선택 완료")
                    time.sleep(2)
                except Exception as cat_e:
                    # Log the error using self.logger to avoid NameError
                    self.logger.warning(f"카테고리 '{category_target_label}' 선택 실패 (무시하고 진행): {cat_e}")
                    print(f"⚠ 카테고리 '{category_target_label}' 선택 실패 (무시하고 진행): {cat_e}")
                
                # --- 태그 입력 (Original code style) ---
                if tags:
                    try:
                        print("- 태그 입력 시작 (Original Selector)...")
                        tag_input_selector = 'input#tag-input.tag_input__rvUB5' # Original selector
                        tag_input = WebDriverWait(self.driver, 10).until(
                            EC.presence_of_element_located((By.CSS_SELECTOR, tag_input_selector))
                        )
                        for tag in tags:
                            tag_input.clear() # Clear before sending keys
                            tag_input.send_keys(tag)
                            time.sleep(0.7)
                            tag_input.send_keys(Keys.ENTER)
                            time.sleep(1.5)
                            print(f"  ... 태그 '{tag}' 추가")
                        print("- 모든 태그 입력 완료")
                        time.sleep(2)
                    except Exception as tag_e:
                        # Fallback: Try data-testid if original fails
                        try:
                            print(f"- 태그 입력 원본 선택자({tag_input_selector}) 실패, data-testid 시도...")
                            tag_input_selector = 'input[data-testid="tagInput"]'
                            tag_input = WebDriverWait(self.driver, 5).until(
                                EC.presence_of_element_located((By.CSS_SELECTOR, tag_input_selector))
                            )
                            for tag in tags:
                                tag_input.send_keys(tag)
                                time.sleep(0.5)
                                tag_input.send_keys(Keys.ENTER)
                                time.sleep(1)
                                print(f"  ... 태그 '{tag}' 추가 (Fallback)")
                            print("- 모든 태그 입력 완료 (Fallback)")
                            time.sleep(1)
                        except Exception as tag_e_fallback:
                             print(f"⚠ 태그 입력 최종 실패 (무시): {tag_e_fallback}")
                else:
                    print("- 입력할 태그 없음")

            except Exception as e_publish_settings:
                 print(f"⚠ 발행 설정(카테고리/태그) 중 오류 발생 (무시하고 최종 발행 시도): {e_publish_settings}")
            
            # --- 최종 발행 버튼 클릭 (Original Code Style - JS with fallback) ---
            try:
                print("- 최종 발행 버튼 클릭 시도 (JavaScript - Original Selector)...")
                # Original JS selector attempt
                final_publish_script = """
                    var finalBtn = document.querySelector('button.confirm_btn__WEaBq[data-testid="seOnePublishBtn"]');
                    if (finalBtn) {
                        finalBtn.click();
                        return true;
                    } else {
                         console.error('Final publish button not found!');
                         return false;
                    }
                """
                if self.driver.execute_script(final_publish_script):
                    print("- 최종 발행 버튼 클릭 완료 (JS). 포스팅 완료 대기 (10초)...") # Increased wait
                    time.sleep(10)
                else:
                    print("✗ 최종 발행 버튼을 JavaScript로 찾거나 클릭할 수 없습니다. Selenium 시도...")
                    # Fallback to Selenium click (data-testid)
                    try:
                         final_publish_button_selector = 'button[data-testid="seOnePublishBtn"]'
                         final_publish_button = WebDriverWait(self.driver, 5).until(
                              EC.element_to_be_clickable((By.CSS_SELECTOR, final_publish_button_selector))
                         )
                         final_publish_button.click()
                         print("- 최종 발행 버튼 클릭 완료 (Selenium). 포스팅 완료 대기 (10초)...")
                         time.sleep(10)
                    except Exception as e_final_fallback:
                         print(f"✗ 최종 발행 버튼 클릭 최종 실패: {e_final_fallback}")
                         return False

                # 발행 후 URL 확인 (기존 로직 유지)
                if "postwrite" not in self.driver.current_url:
                     print("\n✓ 블로그 포스팅 성공!")
                     print(f"  발행된 글 URL: {self.driver.current_url}")
                     return True
                else:
                     print(f"✗ 포스팅 실패 또는 확인 불가: 현재 URL이 여전히 postwrite 페이지입니다 ({self.driver.current_url})")
                     return False

            except Exception as e:
                print(f"✗ 최종 발행 버튼 처리 중 오류: {e}")
                return False

        except (TimeoutException, NoSuchElementException, WebDriverException) as e:
            self.logger.error(f"포스팅 중 Selenium 관련 오류 발생: {e}", exc_info=True)
            print(f"✗ 포스팅 실패 (Selenium 오류): {e}")
            # Consider adding screenshot on error here from original code
            # self.driver.save_screenshot(f"error_screenshot_{datetime.now():%Y%m%d_%H%M%S}.png")
            return False
        except Exception as e:
            self.logger.error(f"포스팅 중 예상치 못한 오류 발생: {e}", exc_info=True)
            print(f"✗ 예상치 못한 포스팅 오류: {e}")
            return False
        finally:
            # Original code didn't have explicit iframe handling here, so keeping it commented
            # try: self.driver.switch_to.default_content() except: pass
            print("- 포스팅 함수 종료")

    def manual_login(self) -> bool:
        """자동으로 로그인을 진행합니다."""
        print("! 자동 로그인을 시도합니다...")
        if self.setup_driver():
            if self.login():
                 # 로그인 성공 후 쿠키 저장 시도 (선택적)
                 # self.save_cookies()
                 return True
            else:
                print("✗ 자동 로그인 실패.")
                self.close()
                return False
        else:
            print("✗ 웹 드라이버 설정 실패로 로그인 불가.")
            return False

    # 쿠키 저장/로드 기능 추가 (선택적)
    def save_cookies(self):
        if self.driver:
            try:
                self.cookies_file.parent.mkdir(parents=True, exist_ok=True)
                with open(self.cookies_file, 'wb') as f:
                    pickle.dump(self.driver.get_cookies(), f)
                print(f"✓ 로그인 쿠키 저장 완료: {self.cookies_file}")
            except Exception as e:
                print(f"⚠ 쿠키 저장 실패: {e}")

    def load_cookies(self):
        if self.cookies_file.exists():
            try:
                with open(self.cookies_file, 'rb') as f:
                    cookies = pickle.load(f)
                
                # 쿠키를 적용하기 위해 기본 페이지로 이동 (도메인 필요)
                self.driver.get("https://www.naver.com") # 네이버 도메인으로 이동
                time.sleep(1)
                for cookie in cookies:
                    # SameSite 속성 처리 (None인 경우 Secure 필요)
                    if 'sameSite' in cookie and cookie['sameSite'] == 'None':
                         cookie['secure'] = True
                    # 만료일(expiry)이 과거면 추가하지 않음 (선택적)
                    # if 'expiry' in cookie and cookie['expiry'] < time.time():
                    #    continue
                    try:
                        self.driver.add_cookie(cookie)
                    except Exception as cookie_e:
                         # 특정 쿠키 추가 오류는 무시하고 계속 진행
                         print(f"  ⚠ 쿠키 추가 오류 (무시): {cookie['name']} - {cookie_e}")
                         
                print("✓ 저장된 로그인 쿠키 로드 완료")
                self.driver.refresh() # 쿠키 적용 위해 새로고침
                time.sleep(2)
                return True
            except Exception as e:
                print(f"⚠ 쿠키 로드 실패: {e}")
                # 쿠키 파일 손상 가능성, 삭제 고려
                # self.cookies_file.unlink(missing_ok=True)
                return False
        else:
            print("- 저장된 쿠키 파일 없음")
            return False

    def close(self):
        """WebDriver를 종료합니다."""
        if self.driver:
            try:
                self.driver.quit()
                self.driver = None # 드라이버 객체 참조 제거
                print("- 웹드라이버 종료 완료")
            except Exception as e:
                self.logger.warning(f"WebDriver close error: {e}")
                print(f"⚠ 웹드라이버 종료 중 오류: {e}")
