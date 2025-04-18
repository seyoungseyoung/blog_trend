import time
import logging
import re
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException

def get_trending_keywords(driver, url, selector):
    """Navigates to the URL and extracts keywords using the CSS selector.
    
    Assumes the provided driver is already logged in if required by the URL.
    Targets the specific keyword span first, with fallbacks.
    """
    keywords = []
    from_previous_date = False  # Flag to track if we've moved to a previous date
    
    # List of invalid keywords that indicate extraction didn't work properly
    invalid_keywords = [
        "검색 유입 트렌드",
        "메인 유입 트렌드",
        "주제별 비교",
        "주제별 트렌드",
        "주제별 인기유입검색어",
        "성별,연령별 인기유입검색어",
        "성별, 연령별 인기유입검색어"  # With space variant
    ]
    
    min_keywords_required = 20  # Minimum number of keywords required
    max_attempts = 1  # Maximum number of attempts to find keywords by clicking previous (changed from 3 to 1)
    attempts = 0
    
    try:
        logging.info(f"Navigating to {url} for scraping keywords...")
        driver.get(url)
        
        # Increase timeout and wait for any swiper-slide to appear
        wait_timeout = 30  # Increased from 20 to 30 seconds
        WebDriverWait(driver, wait_timeout).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, ".swiper-slide"))
        )
        logging.info("Found swiper slides. Looking for keyword container...")
        time.sleep(7)  # Increased from 5 to 7 seconds to allow dynamic content to fully load

        # Initial extraction
        keywords = extract_keywords_from_slides(driver)
        
        # Filter keywords
        filtered_keywords = filter_keywords(keywords, invalid_keywords)
        
        # Check if we need to look at a previous date (only click previous once)
        if (len(filtered_keywords) < min_keywords_required or 
            any(any(invalid_k in k for invalid_k in invalid_keywords) for k in keywords)):
            
            reason = []
            if len(filtered_keywords) < min_keywords_required:
                reason.append(f"only {len(filtered_keywords)} valid keywords found (need {min_keywords_required})")
            if any(any(invalid_k in k for invalid_k in invalid_keywords) for k in keywords):
                reason.append("invalid category headers found")
            
            logging.info(f"Need to look at previous date because: {', '.join(reason)}. "
                         f"Clicking the previous button once...")
            
            # Try clicking previous and extracting again
            if try_click_previous_and_extract(driver, keywords):
                # If we get here, we've successfully navigated to a previous date
                from_previous_date = True
                
                # Re-filter the keywords
                filtered_keywords = filter_keywords(keywords, invalid_keywords)
                
                logging.info(f"After clicking previous: Found {len(filtered_keywords)}/{len(keywords)} valid keywords")
            else:
                logging.warning("Failed to click previous button. Using current keywords.")

    except TimeoutException:
        logging.error(f"Timeout waiting for any swiper-slide at {url} after {wait_timeout} seconds")
    except NoSuchElementException:
        logging.error(f"Could not find any swiper-slide elements at {url}")
    except Exception as e:
        logging.error(f"Error extracting keywords from {url}: {e}", exc_info=True)
    
    # Final filtering before returning
    # If we moved to a previous date, keep date and quiz keywords
    if from_previous_date:
        logging.info("Processing keywords from previous date - keeping quiz and date-related keywords")
        filtered_keywords = filter_keywords_for_previous_date(keywords, invalid_keywords)
    else:
        filtered_keywords = filter_keywords(keywords, invalid_keywords)
        
    logging.info(f"Final result: Extracted {len(filtered_keywords)} unique valid keywords from {url}.")
    return filtered_keywords

def is_korean_consonants_only(text):
    """Check if a string contains only Korean consonants (초성)."""
    korean_consonants = 'ㄱㄲㄴㄷㄸㄹㅁㅂㅃㅅㅆㅇㅈㅉㅊㅋㅌㅍㅎ'
    for char in text:
        if char not in korean_consonants:
            return False
    return True

def filter_keywords(keywords, invalid_keywords):
    """Filter out invalid keywords, duplicates, short keywords, and other unwanted items."""
    # Remove duplicates
    unique_keywords = list(set(keywords))
    
    # Log excluded short keywords
    short_keywords = [k for k in unique_keywords if len(k) <= 3]
    if short_keywords:
        logging.info(f"Excluding {len(short_keywords)} short keywords (3 chars or fewer): {short_keywords}")
    
    # Label Korean consonants-only keywords as quiz-related
    consonants_only_keywords = [k for k in unique_keywords if is_korean_consonants_only(k)]
    if consonants_only_keywords:
        logging.info(f"Found {len(consonants_only_keywords)} quiz-related consonants-only keywords: {consonants_only_keywords}")
    
    # Filter out keywords with 3 or fewer characters, non-keyword items, invalid keywords,
    # and keywords that only contain Korean consonants
    filtered_keywords = [k for k in unique_keywords if len(k) > 3 and 
                         not k.startswith('#') and 
                         not k.isdigit() and 
                         not any(invalid_k in k for invalid_k in invalid_keywords) and
                         not is_korean_consonants_only(k)]
    
    return filtered_keywords

def try_click_previous_and_extract(driver, keywords_list):
    """Try to click the previous button and extract keywords.
    Returns True if successful, False otherwise.
    """
    try:
        # Try clicking the previous button (navigate to previous day or slide)
        prev_button_selector = "#root > div > div > div.u_ni_container.container_wrapper > div.u_ni_section_wrap > div > div.u_ni_section_unit.menu-sub-menu-tabs.show-sub-menu > div.u_ni_range_component.u_ni_add_bottom_line > div > div > div.u_ni_btn_prev.u_ni_ico_prev"
        
        # First try the specific selector
        prev_button = None
        try:
            prev_button = WebDriverWait(driver, 5).until(
                EC.element_to_be_clickable((By.CSS_SELECTOR, prev_button_selector))
            )
        except:
            # If specific selector fails, try a more general one
            logging.info("Specific prev button selector failed, trying more general selectors...")
            for general_selector in [
                ".u_ni_btn_prev", 
                ".u_ni_ico_prev", 
                "[class*='prev']", 
                "button:contains('이전')"
            ]:
                try:
                    prev_buttons = driver.find_elements(By.CSS_SELECTOR, general_selector)
                    if prev_buttons:
                        logging.info(f"Found {len(prev_buttons)} previous buttons with selector '{general_selector}'")
                        prev_button = prev_buttons[0]
                        break
                except:
                    continue
        
        if not prev_button:
            logging.error("Could not find previous button with any selector")
            return False
        
        logging.info("Previous button found. Clicking it...")
        driver.execute_script("arguments[0].scrollIntoView(true);", prev_button)
        time.sleep(1)
        driver.execute_script("arguments[0].click();", prev_button)
        logging.info("Clicked previous button. Waiting for page to update...")
        time.sleep(7)  # Increased wait time to ensure the page fully updates
        
        # After clicking previous, use the EXACT selector provided for extraction
        logging.info("Extracting keywords using the exact specified selector after navigation...")
        new_keywords = extract_keywords_after_navigation(driver)
        
        # If we found new keywords after clicking, log success and update keywords_list
        if new_keywords:
            logging.info(f"Found {len(new_keywords)} keywords after clicking previous button.")
            keywords_list.clear()  # Clear the original list
            keywords_list.extend(new_keywords)  # Add the new keywords
            return True
        else:
            logging.warning("Failed to find any keywords after clicking previous button.")
            return False
    except Exception as e:
        logging.error(f"Failed to click previous button: {e}")
        return False

def extract_keywords_after_navigation(driver):
    """Extract keywords using the exact specific selector after navigation."""
    keywords = []
    try:
        # Wait for the page to fully load
        time.sleep(5)
        
        # The base selector for the container with keywords
        base_selector = "#root > div > div > div.u_ni_container.calendar-sub-menu-header-fixed.container_wrapper > div.u_ni_section_wrap > div > div:nth-child(2) > div > div:nth-child(2) > div:nth-child(1) > div > div > div.swiper-slide.swiper-slide-next"
        
        # First try to find the container
        try:
            logging.info(f"Looking for keyword container with selector: {base_selector}")
            container = WebDriverWait(driver, 10).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, base_selector))
            )
            logging.info("Found keyword container!")
            
            # Find all list items within the container that might contain keywords
            list_items = container.find_elements(By.CSS_SELECTOR, "li")
            logging.info(f"Found {len(list_items)} list items within container")
            
            # Extract text from each list item
            for i, item in enumerate(list_items):
                try:
                    keyword = item.text.strip()
                    if keyword and len(keyword) >= 2:
                        logging.info(f"Extracted keyword {i+1}: '{keyword}'")
                        keywords.append(keyword)
                except Exception as e:
                    logging.warning(f"Error extracting text from list item {i+1}: {e}")
                    
            if not keywords:
                logging.warning("No keywords found in list items, trying text spans...")
                # Try looking for spans within the list items
                spans = container.find_elements(By.CSS_SELECTOR, "span.u_ni_trend_text")
                logging.info(f"Found {len(spans)} text spans")
                
                for i, span in enumerate(spans):
                    try:
                        keyword = span.text.strip()
                        if keyword and len(keyword) >= 2:
                            logging.info(f"Extracted keyword from span {i+1}: '{keyword}'")
                            keywords.append(keyword)
                    except Exception as e:
                        logging.warning(f"Error extracting text from span {i+1}: {e}")
                        
        except Exception as e:
            logging.error(f"Error finding keyword container: {e}")
            
        # If still no keywords, try direct parent selectors of list items
        if not keywords:
            logging.warning("Container selector failed. Trying direct parent selectors of list items...")
            try:
                # Try a more focused selector to get directly to the list items
                list_selector = f"{base_selector} > div > div > ul > div > div > li"
                list_items = driver.find_elements(By.CSS_SELECTOR, list_selector)
                logging.info(f"Found {len(list_items)} list items with direct selector")
                
                for i, item in enumerate(list_items):
                    try:
                        keyword = item.text.strip()
                        if keyword and len(keyword) >= 2:
                            logging.info(f"Extracted keyword from direct selector {i+1}: '{keyword}'")
                            keywords.append(keyword)
                    except Exception as e:
                        logging.warning(f"Error extracting text from direct list item {i+1}: {e}")
            except Exception as e:
                logging.error(f"Error with direct list selector: {e}")
        
        # If all above methods fail, use JavaScript to extract keywords
        if not keywords:
            logging.warning("All selector methods failed. Trying JavaScript extraction...")
            try:
                # Use JavaScript to find elements and extract text
                js_script = """
                    var container = document.querySelector("#root > div > div > div.u_ni_container.calendar-sub-menu-header-fixed.container_wrapper > div.u_ni_section_wrap > div > div:nth-child(2) > div > div:nth-child(2) > div:nth-child(1) > div > div > div.swiper-slide.swiper-slide-next");
                    if (!container) return [];
                    var items = container.querySelectorAll("li");
                    var texts = [];
                    for (var i = 0; i < items.length; i++) {
                        var text = items[i].textContent.trim();
                        if (text && text.length >= 2) texts.push(text);
                    }
                    return texts;
                """
                js_keywords = driver.execute_script(js_script)
                logging.info(f"Extracted {len(js_keywords)} keywords via JavaScript")
                keywords.extend(js_keywords)
            except Exception as e:
                logging.error(f"Error with JavaScript extraction: {e}")
    
    except Exception as e:
        logging.error(f"Error in extract_keywords_after_navigation: {e}")
        
    return keywords

def extract_keywords_from_slides(driver):
    """Extract keywords from all slides in the current view."""
    keywords = []
    
    # Wait for page to fully load after any navigation
    time.sleep(3)
    
    try:
        # FIRST APPROACH: Try the most reliable selectors that we know work consistently
        logging.info("Attempting to extract keywords using reliable selectors first...")
        
        # These selectors directly target the keyword items based on their typical structure
        reliable_selectors = [
            ".u_ni_keyword_item",  # Keyword items by class
            ".u_ni_rel_keyword_item",  # Related keyword items
            ".u_ni_trend_text",  # Trend text items
            ".u_ni_section_unit li a"  # List items within section units
        ]
        
        for selector in reliable_selectors:
            elements = driver.find_elements(By.CSS_SELECTOR, selector)
            if elements:
                logging.info(f"Found {len(elements)} elements with reliable selector '{selector}'")
                for element in elements:
                    keyword = element.text.strip()
                    if keyword and len(keyword) >= 2:
                        logging.debug(f"  Extracted keyword: '{keyword}'")
                        keywords.append(keyword)
                
                if keywords:
                    logging.info(f"Successfully extracted {len(keywords)} keywords using reliable selector '{selector}'")
                    break  # Stop if we found keywords
    
        # SECOND APPROACH: Check all swiper slides individually if reliable selectors didn't work
        if not keywords:
            logging.info("Reliable selectors didn't yield keywords. Checking all swiper slides...")
            all_slides = driver.find_elements(By.CSS_SELECTOR, ".swiper-slide")
            logging.info(f"Found {len(all_slides)} total swiper slides.")
            
            # Try each slide to find keywords
            for slide_index, slide in enumerate(all_slides):
                logging.info(f"Checking slide {slide_index+1}/{len(all_slides)} for keywords...")
                
                # Take a screenshot of current slide for debugging (optional)
                # try:
                #     slide.screenshot(f"slide_{slide_index+1}.png")
                #     logging.info(f"Saved screenshot of slide {slide_index+1}")
                # except Exception as e:
                #     logging.warning(f"Could not save screenshot: {e}")
                
                # Try different selectors directly within this slide
                selectors_to_try = [
                    "li a span.u_ni_trend_text",  # Most specific
                    "li a",                        # Links
                    "li",                          # List items
                    "span",                        # Any spans
                    "div"                          # Any divs (last resort)
                ]
                
                for selector_suffix in selectors_to_try:
                    try:
                        # Construct a selector that targets elements within this specific slide
                        current_selector = f".swiper-slide:nth-child({slide_index+1}) {selector_suffix}"
                        logging.info(f"Trying selector: '{current_selector}'")
                        
                        elements = driver.find_elements(By.CSS_SELECTOR, current_selector)
                        if elements:
                            logging.info(f"Found {len(elements)} elements with selector '{current_selector}'")
                            slide_keywords = []
                            
                            for element in elements:
                                keyword = element.text.strip()
                                if keyword:
                                    logging.debug(f"  Extracted keyword: '{keyword}'")
                                    slide_keywords.append(keyword)
                            
                            if slide_keywords:
                                logging.info(f"Successfully extracted {len(slide_keywords)} keywords from slide {slide_index+1}")
                                keywords.extend(slide_keywords)
                                break  # Found keywords in this slide, no need to try more selectors
                    except Exception as e:
                        logging.warning(f"Error trying selector '{current_selector}': {e}")
                        continue
        
        # THIRD APPROACH: Last resort - get all text from body
        if not keywords:
            logging.warning("No keywords found with specific selectors. Trying to extract all text from page...")
            try:
                # Get all text from the body
                body_text = driver.find_element(By.TAG_NAME, "body").text
                if body_text:
                    # Split by newlines and filter
                    lines = [line.strip() for line in body_text.split('\n') if line.strip() and len(line.strip()) >= 2]
                    logging.info(f"Extracted {len(lines)} text lines from body")
                    keywords.extend(lines)
            except Exception as e:
                logging.warning(f"Error extracting text from body: {e}")
        
    except Exception as e:
        logging.error(f"Error in extract_keywords_from_slides: {e}")
    
    # Log the raw extracted keywords for debugging
    if keywords:
        logging.info(f"Raw keywords extracted (first 10): {keywords[:10]}")
        if len(keywords) > 10:
            logging.info(f"...and {len(keywords)-10} more")
    else:
        logging.warning("No keywords extracted from slides")
    
    return keywords 

def filter_keywords_for_previous_date(keywords, invalid_keywords):
    """Filter keywords from previous date, excluding quiz keywords and date-specific keywords as they won't work at midnight."""
    # Remove duplicates
    unique_keywords = list(set(keywords))
    
    # Special keywords to explicitly filter out when from previous date
    explicit_filter_terms = ["건강보험", "소득세", "국민연금", "의료보험", 
                            "근로소득세", "퇴직금", "소득공제", "세금", "공제", "세액공제",
                            "지급일", "납부일"]
    
    excluded_special_keywords = [k for k in unique_keywords if any(term in k for term in explicit_filter_terms)]
    if excluded_special_keywords:
        logging.info(f"Explicitly excluding {len(excluded_special_keywords)} annual topic keywords when moving to previous date: {excluded_special_keywords}")
    
    # Filter out keywords with 3 or fewer characters, invalid keywords, quiz keywords, 
    # date-specific keywords, Korean consonants-only keywords, and explicit annual topic keywords
    filtered_keywords = [k for k in unique_keywords if 
                        (len(k) > 3 and 
                         not k.startswith('#') and 
                         not k.isdigit() and 
                         not any(invalid_k in k for invalid_k in invalid_keywords) and
                         "퀴즈" not in k and
                         not any(f"{month}월" in k for month in range(1, 13)) and
                         not any(f"{day}일" in k for day in range(1, 32)) and
                         not is_korean_consonants_only(k) and
                         not any(term in k for term in explicit_filter_terms))]
    
    # Log excluded short keywords
    short_keywords = [k for k in unique_keywords if len(k) <= 3]
    if short_keywords:
        logging.info(f"Excluding {len(short_keywords)} short keywords (3 chars or fewer) when moving to previous date: {short_keywords}")
    
    # Log excluded quiz-related Korean consonants-only keywords
    consonants_only_keywords = [k for k in unique_keywords if is_korean_consonants_only(k)]
    if consonants_only_keywords:
        logging.info(f"Excluding {len(consonants_only_keywords)} quiz-related consonants-only keywords when moving to previous date: {consonants_only_keywords}")
    
    # Log excluded date-specific keywords 
    date_keywords = [k for k in unique_keywords if 
                    any(f"{month}월" in k for month in range(1, 13)) and 
                    any(f"{day}일" in k for day in range(1, 32))]
    if date_keywords:
        logging.info(f"Excluding {len(date_keywords)} date-specific keywords when moving to previous date: {date_keywords}")
    
    # Log excluded explicit quiz keywords
    excluded_quiz_keywords = [k for k in unique_keywords if "퀴즈" in k]
    if excluded_quiz_keywords:
        logging.info(f"Excluding {len(excluded_quiz_keywords)} explicit quiz keywords when moving to previous date: {excluded_quiz_keywords}")
    
    return filtered_keywords 