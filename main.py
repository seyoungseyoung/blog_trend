import os
import time
import logging
import re # For keyword date filtering
from datetime import date, timedelta, datetime # Import datetime
from dotenv import load_dotenv
import pytz # Import pytz
import shutil
import schedule  # 스케줄 라이브러리 추가

# Import project modules
from naver_poster import NaverBlogPoster
from llm_client import LLMClient
from scraper import get_trending_keywords

# --- Configuration ---
load_dotenv() # Load environment variables from .env file

# Basic logging setup
logging.basicConfig(
    level=logging.INFO, 
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("blog_trend.log", encoding='utf-8'), # Log to file
        logging.StreamHandler() # Log to console
    ]
)

# Get logger for this module
logger = logging.getLogger(__name__)

# Constants
TREND_URL = "https://creator-advisor.naver.com/naver_blog/gongnyangi/trends#trend-by-categories"
# Selector for the keywords container (using a more general selector)
KEYWORDS_CONTAINER_SELECTOR = "#root .u_ni_section_wrap .swiper-wrapper .swiper-slide"
POST_DELAY_SECONDS = 15 # Delay between posts
POSTED_LOG_FILE = "posted_log.txt" # File to log posted keywords
DATE_REGEX = re.compile(r'(\d{1,2})월\s*(\d{1,2})일') # Regex to find MM월 DD일
KST = pytz.timezone('Asia/Seoul') # Define KST timezone
FILTER_KEYWORDS = [
    "자살", "살해", "성폭행", "불법", "마약", "범죄", 
    "성인", "도박", "음란", "포르노", "성매매", 
    "주식 리딩방", "투자 사기", "선물 사기"
] # List of keywords to filter out

# Keywords that should only be posted once per year
ANNUAL_KEYWORDS = [
    "건강보험", "연말정산", "종합소득세", "국민연금", "의료보험", 
    "근로소득세", "퇴직금", "소득공제", "세금", "공제", "세액공제",
    "지급일", "납부일"
]

# --- Helper Functions ---

def load_posted_today(log_file: str, today_str: str) -> set:
    """Loads keywords posted today from the log file."""
    posted_today = set()
    try:
        # Try different encodings if UTF-8 fails
        encodings_to_try = ['utf-8', 'cp949', 'euc-kr']
        
        for encoding in encodings_to_try:
            try:
                with open(log_file, 'r', encoding=encoding) as f:
                    for line in f:
                        line = line.strip()
                        if line.startswith(today_str):
                            try:
                                # Assumes format: YYYY-MM-DD,keyword
                                keyword = line.split(',', 1)[1].strip()
                                posted_today.add(keyword)
                                # Also add a normalized version (remove extra spaces)
                                normalized = ' '.join(keyword.split())
                                if normalized != keyword:
                                    posted_today.add(normalized)
                            except IndexError:
                                logger.warning(f"Skipping malformed line in {log_file}: {line}")
                # If we got here without an exception, we succeeded with this encoding
                logger.info(f"Successfully read log file using {encoding} encoding")
                break
            except UnicodeDecodeError:
                if encoding == encodings_to_try[-1]:
                    # This was the last encoding to try
                    logger.error(f"Failed to decode {log_file} with any of the attempted encodings")
                    raise
                else:
                    # Try the next encoding
                    logger.warning(f"Failed to decode {log_file} with {encoding}, trying next encoding")
                    continue
    except FileNotFoundError:
        logger.info(f"Log file {log_file} not found, assuming no posts yet today.")
    except Exception as e:
        logger.error(f"Error reading log file {log_file}: {e}")
    
    logger.info(f"Loaded {len(posted_today)} keywords already posted today from {log_file}")
    if posted_today:
        logger.info(f"Posted keywords: {posted_today}")
    return posted_today

def load_annual_keywords_posted_this_year(log_file: str, current_year: str) -> set:
    """Loads annual keywords that have been posted in the current year.
    
    Note: This function only checks the current year's posts, so when the year changes,
    the returned set will be empty, automatically allowing annual keywords to be posted again.
    """
    annual_posted_this_year = set()
    try:
        encodings_to_try = ['utf-8', 'cp949', 'euc-kr']
        
        for encoding in encodings_to_try:
            try:
                with open(log_file, 'r', encoding=encoding) as f:
                    for line in f:
                        line = line.strip()
                        # Check if the line is from the current year
                        if line.startswith(current_year):
                            try:
                                # Assumes format: YYYY-MM-DD,keyword
                                keyword = line.split(',', 1)[1].strip()
                                # Check if this keyword is an annual keyword
                                if is_annual_keyword(keyword):
                                    annual_posted_this_year.add(keyword)
                                    # Also add normalized version
                                    normalized = ' '.join(keyword.split())
                                    if normalized != keyword:
                                        annual_posted_this_year.add(normalized)
                            except IndexError:
                                logger.warning(f"Skipping malformed line in {log_file}: {line}")
                # If we got here without an exception, we succeeded with this encoding
                logger.info(f"Successfully read log file for annual keywords using {encoding} encoding")
                break
            except UnicodeDecodeError:
                if encoding == encodings_to_try[-1]:
                    logger.error(f"Failed to decode {log_file} with any of the attempted encodings for annual keywords")
                    raise
                else:
                    continue
    except FileNotFoundError:
        logger.info(f"Log file {log_file} not found, assuming no annual keywords posted this year.")
    except Exception as e:
        logger.error(f"Error reading log file {log_file} for annual keywords: {e}")
    
    logger.info(f"Loaded {len(annual_posted_this_year)} annual keywords already posted this year: {annual_posted_this_year}")
    return annual_posted_this_year

def is_annual_keyword(keyword: str) -> bool:
    """Checks if a keyword is an annual topic that should only be posted once per year."""
    is_annual = any(annual_term in keyword for annual_term in ANNUAL_KEYWORDS)
    if is_annual:
        logger.info(f"Keyword '{keyword}' identified as an annual topic (contains one of {ANNUAL_KEYWORDS})")
    return is_annual

def is_related_stock_keyword(keyword: str) -> bool:
    """Checks if a keyword is related to stocks (관련주) which can be posted daily."""
    return "관련주" in keyword

def is_keyword_already_posted(keyword: str, posted_today_set: set, annual_posted_set: set = None) -> bool:
    """Checks if a keyword has already been posted today or this year (for annual keywords)."""
    # If it's an annual keyword, check if it's been posted this year
    if annual_posted_set is not None and is_annual_keyword(keyword):
        # Check the keyword as-is
        if keyword in annual_posted_set:
            logger.info(f"Annual keyword '{keyword}' already posted this year. Skipping.")
            return True
        
        # Check normalized version (removing extra spaces)
        normalized = ' '.join(keyword.split())
        if normalized in annual_posted_set:
            logger.info(f"Annual keyword '{keyword}' (normalized to '{normalized}') already posted this year. Skipping.")
            return True
        
        # Check without spaces
        no_spaces = keyword.replace(" ", "")
        if any(no_spaces == p.replace(" ", "") for p in annual_posted_set):
            logger.info(f"Annual keyword '{keyword}' (without spaces) already posted this year. Skipping.")
            return True

        # If we got here, this annual keyword hasn't been posted this year
        logger.info(f"Annual keyword '{keyword}' has NOT been posted this year yet. Will process.")
        return False
    
    # For non-annual keywords or if annual_posted_set is None, check if posted today
    if keyword in posted_today_set:
        logger.info(f"Keyword '{keyword}' already posted today. Skipping.")
        return True
    
    # Check normalized version (removing extra spaces)
    normalized = ' '.join(keyword.split())
    if normalized in posted_today_set:
        logger.info(f"Keyword '{keyword}' (normalized to '{normalized}') already posted today. Skipping.")
        return True
    
    # Check without spaces
    no_spaces = keyword.replace(" ", "")
    if any(no_spaces == p.replace(" ", "") for p in posted_today_set):
        logger.info(f"Keyword '{keyword}' (without spaces) already posted today. Skipping.")
        return True
    
    return False

def clean_log_file(log_file: str) -> None:
    """
    Clean the log file to ensure all entries are valid and properly encoded in UTF-8.
    This helps fix any encoding issues that might have occurred.
    
    Valid lines should match the format: YYYY-MM-DD,keyword
    """
    if not os.path.exists(log_file):
        logger.info(f"Log file {log_file} does not exist yet. No cleaning needed.")
        return
    
    # Create a backup of the original file
    backup_file = f"{log_file}.bak"
    shutil.copy2(log_file, backup_file)
    logger.info(f"Created backup of log file at {backup_file}")
    
    valid_lines = []
    date_pattern = re.compile(r'^\d{4}-\d{2}-\d{2},')
    
    # Read with lenient error handling to filter out invalid entries
    try:
        with open(log_file, 'r', encoding='utf-8', errors='ignore') as f:
            for line in f:
                line = line.strip()
                # Keep only valid lines that match the date pattern
                if date_pattern.match(line) and ',' in line:
                    valid_lines.append(line)
    except Exception as e:
        logger.error(f"Error reading log file: {e}")
    
    # Write back only valid entries with proper UTF-8 encoding
    try:
        with open(log_file, 'w', encoding='utf-8') as f:
            for line in valid_lines:
                f.write(f"{line}\n")
        logger.info(f"Cleaned log file. Kept {len(valid_lines)} valid entries.")
    except Exception as e:
        logger.error(f"Error writing cleaned log file: {e}")
        # Restore backup if writing fails
        shutil.copy2(backup_file, log_file)
        logger.info("Restored backup due to error")

def log_posted_keyword(log_file: str, today_str: str, keyword: str) -> None:
    """Log the posted keyword to avoid duplicates"""
    max_retries = 3
    retry_delay = 1  # seconds
    
    for attempt in range(max_retries):
        try:
            # Create directory if it doesn't exist
            os.makedirs(os.path.dirname(log_file), exist_ok=True)
            
            # If file doesn't exist, create it with UTF-8 encoding
            if not os.path.exists(log_file):
                with open(log_file, 'w', encoding='utf-8') as f:
                    pass
            
            # Append with explicit UTF-8 encoding
            with open(log_file, 'a', encoding='utf-8') as f:
                f.write(f"{today_str},{keyword}\n")
                f.flush()  # Ensure data is written to disk
                os.fsync(f.fileno())  # Force OS to write to disk
            
            logger.info(f"Successfully logged posted keyword: {today_str},{keyword}")
            return  # Success, exit function
            
        except Exception as e:
            logger.error(f"Error logging posted keyword (attempt {attempt + 1}/{max_retries}): {e}")
            if attempt < max_retries - 1:  # If not the last attempt
                time.sleep(retry_delay)
            else:
                logger.critical(f"Failed to log keyword after {max_retries} attempts: {today_str},{keyword}")
                raise  # Re-raise the exception after all retries fail

def process_and_deduplicate_keywords(raw_keywords: list, today: date) -> list:
    """Processes keywords: replaces old dates, appends date to '퀴즈', filters specific words, and removes duplicates."""
    processed_keywords_list = []
    today_date_str_md = f"{today.month}월 {today.day}일"
    logger.info(f"Processing keywords for KST date {today.strftime('%Y-%m-%d')} (filtering: {FILTER_KEYWORDS})")

    for keyword in raw_keywords:
        # --- Skip keywords containing words from FILTER_KEYWORDS list --- 
        skip = False
        for filter_word in FILTER_KEYWORDS:
            if filter_word in keyword:
                logger.info(f"Skipping keyword containing filter word '{filter_word}': '{keyword}'")
                skip = True
                break # No need to check other filter words for this keyword
        if skip:
            continue # Skip to the next raw keyword
        # ---------------------------------------------------------------

        processed_keyword = keyword 
        match = DATE_REGEX.search(keyword)
        contains_quiz = "퀴즈" in keyword

        if match:
            # Date found, replace it with today's date string
            old_date_str = match.group(0)
            processed_keyword = keyword.replace(old_date_str, today_date_str_md)
            logger.debug(f"Replaced date in '{keyword}' -> '{processed_keyword}'")
        elif contains_quiz:
            # No date found, but contains "퀴즈", so append today's date
            processed_keyword = f"{keyword} {today_date_str_md}"
            logger.debug(f"Appended date to quiz keyword '{keyword}' -> '{processed_keyword}'")
        
        # Ensure quiz keywords definitely have the date in the desired format even if replaced
        if contains_quiz and match: 
             # Re-check if the replacement was correct, handle potential double spaces etc.
             processed_keyword = re.sub(DATE_REGEX, today_date_str_md, keyword).strip() # More robust replacement
             # If replacing removed the quiz part somehow (unlikely), re-append
             if "퀴즈" not in processed_keyword and "퀴즈" in keyword:
                  processed_keyword = f"{processed_keyword} {today_date_str_md}" # Re-ensure date if needed


        processed_keywords_list.append(processed_keyword)

    # Deduplicate using a set, preserving order is not strictly necessary here
    unique_processed_keywords = list(set(processed_keywords_list))
    logger.info(f"Processed {len(raw_keywords)} raw keywords into {len(unique_processed_keywords)} unique keywords.")
    
    # Sort for consistent logging/processing order (optional)
    unique_processed_keywords.sort() 

    return unique_processed_keywords

def group_similar_keywords(keywords: list) -> list:
    """Groups semantically similar keywords together."""
    if not keywords:
        return []
    
    # 키워드 정규화 함수
    def normalize_keyword(kw: str) -> str:
        # 공백 제거
        kw = kw.replace(" ", "")
        # 특수문자 제거
        kw = re.sub(r'[^\w\s]', '', kw)
        return kw
    
    # 키워드 매핑 딕셔너리
    keyword_groups = {}
    
    # 키워드 정규화 및 그룹화
    for keyword in keywords:
        normalized = normalize_keyword(keyword)
        
        # 이미 그룹화된 키워드인지 확인
        found_group = False
        for group_key in list(keyword_groups.keys()):
            group_normalized = normalize_keyword(group_key)
            
            # 정규화된 키워드가 다른 키워드의 부분 문자열인 경우
            if normalized in group_normalized or group_normalized in normalized:
                keyword_groups[group_key].append(keyword)
                found_group = True
                break
            
            # 공통 단어가 있는 경우 (최소 2글자 이상)
            common_words = set(normalized) & set(group_normalized)
            if len(common_words) >= 2 and len(normalized) >= 3 and len(group_normalized) >= 3:
                keyword_groups[group_key].append(keyword)
                found_group = True
                break
        
        # 새로운 그룹 생성
        if not found_group:
            keyword_groups[keyword] = [keyword]
    
    # 가장 긴 키워드를 대표로 선택
    processed_keywords = []
    for group in keyword_groups.values():
        # 그룹 내에서 가장 긴 키워드를 선택
        representative = max(group, key=len)
        processed_keywords.append(representative)
    
    logger.info(f"Grouped {len(keywords)} keywords into {len(processed_keywords)} unique groups")
    if len(processed_keywords) < len(keywords):
        logger.info(f"Removed {len(keywords) - len(processed_keywords)} duplicate/similar keywords")
    
    return processed_keywords

def determine_target_length(keyword: str) -> int:
    """Determines the target character length for a blog post based on keyword type.
    
    Returns:
        int: Target character length (default: 500)
    """
    # 정치/시사 키워드 (700자로 축소)
    politics_keywords = ['대통령', '후보', '이재명', '윤석열', '정부', '대선', '총선', '선거', 
                         '윤심', '국민의힘', '더불어민주당', '의원', '대통령실', '청와대', '국회', 
                         '관련주', '홍준표', '대변인', '정치', '장관']
    
    # 금융/투자 키워드 (600자로 축소)
    financial_keywords = ['주식', '투자', '금융', '금리', '은행', '배당금', '코스피', '코스닥', 
                          '채권', '펀드', '자산', '부동산', '청년내일저축', '파킹통장', '계좌', 
                          '돈나무', '입출금', 'kb', '하나', '신한', '삼성전자', '증권', '보험']
    
    # 퀴즈/이벤트 키워드 (300자로 유지)
    quiz_keywords = ['퀴즈', '이벤트', '정답', '맞추기', '축구퀴즈', '비트버니']
    
    # 제도/정책 키워드 (700자로 축소)
    policy_keywords = ['정책', '지원', '연말정산', '신청', '세금', '공제', '제도', 
                       '지급일', '실업급여', '국민연금', '건강보험', '지원금', '복지']
    
    # 키워드에 해당 카테고리 키워드가 포함되어 있는지 확인
    if any(word in keyword for word in quiz_keywords):
        target_length = 300  # 기존 유지
        logger.info(f"'{keyword}' classified as QUIZ/EVENT - targeting {target_length} chars")
    elif any(word in keyword for word in policy_keywords):
        target_length = 500  # 700에서 500자로 줄임
        logger.info(f"'{keyword}' classified as POLICY - targeting {target_length} chars")
    elif any(word in keyword for word in politics_keywords):
        target_length = 500  # 700에서 500자로 줄임
        logger.info(f"'{keyword}' classified as POLITICS - targeting {target_length} chars")
    elif any(word in keyword for word in financial_keywords):
        target_length = 450  # 600에서 450자로 줄임
        logger.info(f"'{keyword}' classified as FINANCIAL - targeting {target_length} chars")
    else:
        # 기본값
        target_length = 400  # 500에서 400자로 줄임
        logger.info(f"'{keyword}' not specifically classified - using default {target_length} chars")
    
    return target_length

# --- Main Execution Function ---
def run_trend_blogger():
    """Run the trend blogger bot."""
    logger.info("=== Trend Blogging Bot Started ===")
    
    try:
        # --- 0. Clean log file to ensure proper encoding ---
        clean_log_file(POSTED_LOG_FILE)
        
        # --- 0. Setup KST Date & Load Posted Log --- 
        now_kst = datetime.now(KST)
        today_kst_date = now_kst.date()
        today_kst_str = today_kst_date.strftime("%Y-%m-%d")
        current_year = today_kst_str[:4]  # Get the current year (YYYY from YYYY-MM-DD)
        # Format for title: YYYY년 MM월 DD일
        today_title_str = now_kst.strftime("%Y년 %m월 %d일") 
        logger.info(f"Running for KST date: {today_kst_str}")
        
        # Load already posted keywords for today to avoid duplicates
        posted_today_set = load_posted_today(POSTED_LOG_FILE, today_kst_str)
        
        # Load annual keywords posted this year
        annual_posted_this_year = load_annual_keywords_posted_this_year(POSTED_LOG_FILE, current_year)
        logger.info(f"Annual keywords already posted this year: {annual_posted_this_year}")
        
        # Check if it's early in the new year (January or February)
        is_early_in_year = now_kst.month <= 2
        if is_early_in_year:
            logger.info(f"Currently in month {now_kst.month}, annual topics will be prioritized")

        # --- 1. Initialize Services & Login --- 
        raw_keywords = []
        login_successful = False
        naver_poster = None
        perplexity_client = None
        deepseek_tag_client = None

        try:
            # Initialize LLM clients
            try:
                perplexity_client = LLMClient(env_var_name="PERPLEXITY_API_KEY", api_url="https://api.perplexity.ai/chat/completions")
                deepseek_tag_client = LLMClient(env_var_name="DEEPSEEK_API_KEY", api_url="https://api.deepseek.com/v1/chat/completions")
            except ValueError as e:
                logger.critical(f"Failed to initialize one or more LLMClients: {e}. Check API keys in .env file. Exiting.")
                return
            except Exception as e:
                logger.critical(f"Unexpected error initializing LLMClients: {e}", exc_info=True)
                return

            # Initialize Naver Poster
            try:
                naver_poster = NaverBlogPoster(config={})
            except ValueError as e:
                logger.critical(f"Failed to initialize NaverBlogPoster: {e}. Check Naver credentials in .env file. Exiting.")
                return
            except Exception as e:
                logger.critical(f"Unexpected error initializing NaverBlogPoster: {e}", exc_info=True)
                return

            # Attempt Login using NaverPoster
            logger.info("Attempting Naver login...")
            if not naver_poster.manual_login(): # This sets up the driver and logs in
                logger.error("Naver login failed. Cannot scrape keywords or post.")
                # naver_poster.close() will be called in finally
                return 
            logger.info("Naver login successful.")
            login_successful = True # Mark login as successful

            # --- 2. Scrape Keywords (using the logged-in driver) ---
            if login_successful:
                logger.info("Scraping trending keywords...")
                try:
                    # Pass the driver from the logged-in poster instance
                    raw_keywords = get_trending_keywords(naver_poster.driver, TREND_URL, KEYWORDS_CONTAINER_SELECTOR)
                except Exception as e:
                    logger.error(f"An error occurred during keyword scraping: {e}", exc_info=True)
                    # Decide if you want to continue without keywords or exit
                    logger.warning("Proceeding without scraped keywords due to scraping error.")
                    raw_keywords = [] # Ensure raw_keywords is empty list
            
            # --- 2b. Process & Deduplicate Keywords (NEW LOGIC) --- 
            if raw_keywords: 
                logger.info(f"Raw keywords list ({len(raw_keywords)}): {raw_keywords}") 
                
                # First filter out annual topics that have already been posted this year
                filtered_raw_keywords = []
                for kw in raw_keywords:
                    if is_annual_keyword(kw) and any(annual in kw for annual in annual_posted_this_year):
                        logger.info(f"Filtering out annual keyword '{kw}' that has already been posted this year")
                        continue
                    filtered_raw_keywords.append(kw)
                
                if len(filtered_raw_keywords) < len(raw_keywords):
                    logger.info(f"Filtered out {len(raw_keywords) - len(filtered_raw_keywords)} annual keywords that were already posted this year")
                    raw_keywords = filtered_raw_keywords
                
                # Pass KST date object to the processing function
                processed_keywords = process_and_deduplicate_keywords(raw_keywords, today_kst_date)
                # Group similar keywords
                processed_keywords = group_similar_keywords(processed_keywords)
                
                # Sort keywords to prioritize annual topics at the beginning of the year
                if is_early_in_year:
                    # Create two lists: annual keywords and other keywords
                    annual_keywords = [k for k in processed_keywords if is_annual_keyword(k)]
                    other_keywords = [k for k in processed_keywords if not is_annual_keyword(k)]
                    
                    # Check if we found annual keywords
                    if annual_keywords:
                        logger.info(f"Prioritizing {len(annual_keywords)} annual keywords: {annual_keywords}")
                        # Combine lists with annual keywords first
                        processed_keywords = annual_keywords + other_keywords
            else:
                processed_keywords = []
                logger.warning("No raw keywords were extracted or scraping failed.")

            if not processed_keywords:
                logger.warning("No keywords left after processing and deduplication. No posts will be generated.")
                # return # Or let it continue to finally
            else:
                logger.info(f"Processed unique keywords to handle ({len(processed_keywords)}): {processed_keywords}")

            # --- 3. Process Each Keyword and Post ---
            posted_count = 0
            if login_successful and processed_keywords:
                # Final filtering pass for annual keywords already posted
                final_keywords = []
                for keyword in processed_keywords:
                    # Do an exact string match check with annual_posted_this_year
                    if is_annual_keyword(keyword) and any(keyword.lower().strip() == annual.lower().strip() for annual in annual_posted_this_year):
                        logger.info(f"Final filter: Skipping annual keyword '{keyword}' - exact match found in posted list")
                        continue
                    # Check if the keyword contains any annual keyword from the posted list
                    if is_annual_keyword(keyword) and any(annual.lower() in keyword.lower() for annual in annual_posted_this_year):
                        logger.info(f"Final filter: Skipping annual keyword '{keyword}' - contains a posted annual topic")
                        continue
                    final_keywords.append(keyword)
                
                if len(final_keywords) < len(processed_keywords):
                    logger.info(f"Final filtering removed {len(processed_keywords) - len(final_keywords)} annual keywords that were already posted")
                    processed_keywords = final_keywords
                
                for i, keyword in enumerate(processed_keywords):
                    # Check if the keyword is an annual topic that's already been posted this year
                    if is_annual_keyword(keyword):
                        logger.info(f"Keyword '{keyword}' is an annual topic.")
                    
                    # --- 3a. Check if already posted (with exceptions for certain types) ---
                    is_related_stock = is_related_stock_keyword(keyword)
                    
                    if is_keyword_already_posted(keyword, posted_today_set, annual_posted_this_year) and not is_related_stock:
                        # Skip non-related-stock keywords that have been posted today or (if annual) this year
                        logger.info(f"Skipping keyword '{keyword}' - already posted today or (if annual) this year")
                        continue  # Move to the next keyword
                    elif is_keyword_already_posted(keyword, posted_today_set) and is_related_stock:
                        # Log that we are allowing re-post for related stock keyword
                        logger.info(f"Keyword '{keyword}' already posted today, but allowing re-post because it contains '관련주'.")
                    # --- If not skipped, proceed below ---

                    logger.info(f"--- Processing Keyword {i+1}/{len(processed_keywords)}: {keyword} ---")
                    
                    # 키워드 유형에 따른 글자 수 결정
                    target_length = determine_target_length(keyword)
                    
                    # 3b. Generate BODY using Perplexity
                    # generate_post_content now returns only the content string or None
                    post_content = perplexity_client.generate_post_content(keyword, today_title_str, target_length)
                    
                    generated_tags = [] # Initialize tags list
                    # Check if content generation was successful
                    if post_content:
                        # Generate placeholder title here if content is available
                        placeholder_title = f"{keyword} 최신 동향 ({today_title_str})"
                        logger.info(f"Successfully generated content for '{keyword}'. Length: {len(post_content)}")
                        logger.info(f"Generated Post Title (Placeholder): {placeholder_title}")
                        logger.debug(f"Generated Post Content (excerpt):\n{post_content[:100]}...")

                        # --- 3c. Generate TAGS using DeepSeek based on Perplexity content ---
                        logger.info("Attempting to generate tags using DeepSeek...")
                        generated_tags = deepseek_tag_client.generate_tags_from_content(post_content)
                        
                        # Fallback to original keyword if tag generation fails
                        if not generated_tags: 
                            logger.warning(f"DeepSeek tag generation failed or returned empty for '{keyword}'. Using keyword as fallback tag.")
                            tags_to_use = [keyword.replace(" ", "")]
                        else:
                            tags_to_use = generated_tags
                        
                        logger.info(f"Using tags: {tags_to_use}")

                        # --- 3d. Construct Final Title & Post --- 
                        final_title = placeholder_title # Use the generated placeholder title
                        logger.info(f"Attempting to post '{final_title}' to Naver Blog...")
                        success = naver_poster.create_post(final_title, post_content, tags_to_use)
                        
                        if success:
                            posted_count += 1
                            logger.info(f"Successfully posted for keyword: {keyword}")
                            # --- 3d. Log successful post --- 
                            log_posted_keyword(POSTED_LOG_FILE, today_kst_str, keyword)
                            posted_today_set.add(keyword) # Update in-memory set as well
                            
                            # If it's an annual keyword, also add to the annual posted set
                            if is_annual_keyword(keyword):
                                annual_posted_this_year.add(keyword)
                        else:
                            logger.warning(f"Failed to post for keyword: '{keyword}'. Check naver_poster logs for details.") 
                        
                        # 3e. Delay between posts
                        # (Find the correct index in the *processed* list for delay logic)
                        current_index_in_processed = processed_keywords.index(keyword) 
                        if current_index_in_processed < len(processed_keywords) - 1:
                            logger.info(f"Waiting for {POST_DELAY_SECONDS} seconds before next post...")
                            time.sleep(POST_DELAY_SECONDS)
                    else:
                        logger.warning(f"Skipping keyword '{keyword}' due to failure in Perplexity content generation.")
            else:
                if not login_successful:
                    logger.info("Skipping post generation because login failed.")
                if not processed_keywords:
                    logger.info("Skipping post generation because no keywords were found.")

        except KeyboardInterrupt:
            logger.warning("Keyboard interrupt detected. Stopping processing.")
        except Exception as e:
            logger.error(f"An unexpected error occurred in the main execution block: {e}", exc_info=True)
        finally:
            # Ensure the Naver poster's driver is closed if it was initialized and login was attempted
            if naver_poster:
                logger.info("Closing Naver WebDriver (if active)...")
                naver_poster.close() 
            
            logger.info(f"=== Trend Blogging Bot Finished ===")
            if login_successful and processed_keywords:
                logger.info(f"Processed {len(processed_keywords)} unique keywords. Successfully posted {posted_count}.")
            elif not login_successful:
                logger.info("Bot finished without attempting posts due to login failure.")
            else: # Login was ok, but no keywords
                logger.info("Bot finished without attempting posts because no keywords were found.")
    except Exception as e:
        logger.error(f"Error in run_trend_blogger: {e}")
    finally:
        logger.info("=== Trend Blogging Bot Finished ===")

def schedule_job():
    """Schedule the trend blogger to run daily at 1 AM."""
    # KST 시간대 설정
    kst = pytz.timezone('Asia/Seoul')
    
    # 매일 1시에 실행
    schedule.every().day.at("01:00").do(run_trend_blogger)
    
    logger.info("Scheduler started. Will run daily at 1 AM KST.")
    
    while True:
        try:
            # 스케줄 실행
            schedule.run_pending()
            
            # 1분마다 체크 (로그 없이)
            time.sleep(60)
            
        except Exception as e:
            logger.error(f"Error in scheduler: {e}")
            time.sleep(60)  # 에러 발생 시 1분 후 재시도

if __name__ == "__main__":
    # 스케줄러 시작
    schedule_job() 