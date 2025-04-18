import os
import logging
import re # For parsing tags
import requests
from dotenv import load_dotenv

load_dotenv()

class DeepSeekClient:
    def __init__(self, api_key: str = None, api_url: str = "https://api.deepseek.com/v1/chat/completions", timeout: int = 180):
        self.api_key = api_key or os.getenv("DEEPSEEK_API_KEY")
        self.api_url = api_url
        self.timeout = timeout
        self.logger = logging.getLogger(__name__)

        if not self.api_key:
            self.logger.error("DeepSeek API key not found. Please provide it or set DEEPSEEK_API_KEY environment variable.")
            raise ValueError("DeepSeek API key is missing.")

    def _make_api_request(self, prompt: str, model: str = "deepseek-chat", max_tokens: int = 1000, temperature: float = 0.5) -> dict:
        """Make API request to DeepSeek with proper error handling."""
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        
        payload = {
            "model": model,
            "messages": [
                {"role": "user", "content": prompt}
            ],
            "max_tokens": max_tokens,
            "temperature": temperature
        }

        try:
            response = requests.post(self.api_url, headers=headers, json=payload, timeout=self.timeout)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.Timeout:
            self.logger.error(f"API request timed out after {self.timeout} seconds")
            raise
        except requests.exceptions.RequestException as e:
            self.logger.error(f"API request failed: {str(e)}")
            raise
        except Exception as e:
            self.logger.error(f"Unexpected error during API request: {str(e)}")
            raise

    def _normalize_tag(self, tag: str) -> str:
        """Normalize a tag by removing special characters and spaces."""
        # Convert to lowercase and remove spaces
        normalized = tag.strip().lower()
        # Remove all special characters (only allow Korean, English, numbers)
        normalized = re.sub(r'[^가-힣a-z0-9]', '', normalized)
        return normalized

    def generate_tags_from_content(self, content: str) -> list:
        """Generate tags from the blog post content using DeepSeek API."""
        try:
            # 태그 생성 프롬프트
            prompt = f"""다음 블로그 글 내용을 분석하여 관련 태그를 생성해주세요.
            
            태그 생성 규칙:
            1. 태그는 5-10개 정도 생성
            2. 각 태그는 2-15자 이내로 생성
            3. 태그는 콤마(,)로 구분
            4. 태그에는 특수문자, 공백, 하이픈(-), 앰퍼샌드(&), 슬래시(/) 등을 포함하지 않음
            5. 태그는 모두 한글 또는 영문으로만 구성
            6. 태그는 모두 소문자로 통일
            7. 태그는 모두 연속된 문자열로 작성 (공백 없음)
            
            예시:
            - "김현승 전무" -> "김현승전무"
            - "M&A 시장" -> "ma시장"
            - "AI/ML 기술" -> "aiml기술"
            
            블로그 내용:
            {content}
            """
            
            # API 호출
            response = self._make_api_request(prompt)
            
            if response and 'choices' in response and len(response['choices']) > 0:
                # 태그 추출 및 정규화
                raw_tags = response['choices'][0]['message']['content'].strip()
                # 콤마로 분리하고 각 태그 정규화
                tags = []
                for tag in raw_tags.split(','):
                    normalized_tag = self._normalize_tag(tag)
                    if normalized_tag:  # 빈 태그는 제외
                        tags.append(normalized_tag)
                
                self.logger.info(f"Generated tags: {tags}")
                return tags
            else:
                self.logger.warning("Failed to generate tags: Empty or invalid API response")
                return []
            
        except Exception as e:
            self.logger.error(f"Error generating tags: {str(e)}", exc_info=True)
            return []

    def generate_post_content(self, keyword: str, today_date_str: str, model: str = "deepseek-chat", max_tokens: int = 1000, temperature: float = 0.7):
        """Generates detailed body, placeholder title, and content-based tags, providing today's date context."""
        self.logger.info(f"Generating DETAILED BODY content for keyword: '{keyword}'... (Today: {today_date_str}, Targeting ~800+ chars)")
        
        # Enhanced Prompt: Force web search basis, forbid hallucination
        prompt = (
            f"참고로 오늘은 **{today_date_str}** 입니다.\n\n"
            f"**[지시사항 1: 최신 정보 심층 검색]**\n"
            f"'{keyword}'에 대한 **가장 최신 정보** (최근 1-2개월 중심)를 **Google 검색 결과 우선 활용**하여 심층적으로 조사하세요. 최소 5개 이상의 신뢰할 수 있는 출처(뉴스 기사, 공식 발표 등)를 찾아 각 내용의 핵심 주장, 맥락, 중요도를 파악하세요.\n\n"
            f"**[지시사항 2: 검색 결과 종합 및 분석]**\n"
            f"위 [지시사항 1]에서 찾은 **실제 검색 결과만을 근거**로, 정보들 사이의 공통점, 차이점, 그리고 가장 중요하거나 빈번하게 언급되는 핵심 트렌드/논점을 **객관적으로 분석하고 종합**하세요. 여러 출처에서 교차 확인되는 내용을 중심으로 정리해야 합니다.\n\n"
            f"**[지시사항 3: 블로그 본문 작성 (검색 기반)]**\n"
            f"위 [지시사항 2]에서 **종합된 내용만을 바탕**으로, **최소 800자 이상**의 **매우 상세하고 구체적인** 블로그 게시물 **본문**을 작성하세요. 서론, 본론(검색된 최신 동향 상세 분석, 주요 영향/이슈, 전망 등), 결론의 구조를 갖추는 것이 좋습니다. **본문 내용 중 특정 정보나 주장을 언급할 때는 반드시 해당 내용의 출처(예: [출처: OOO뉴스])를 문장 끝이나 적절한 위치에 명시하세요.**\n"
            f"**[매우 중요한 제약 조건]**\n"
            f"- **절대로 검색 결과에 없는 정보를 추측하거나 꾸며내지 마세요 (No Hallucination!).**\n"
            f"- 모든 내용은 반드시 단계 1에서 검색된 실제 최신 정보와 그 출처에 근거해야 합니다.\n"
            f"- 본문 내에 반드시 **출처**를 포함시켜야 합니다.\n"
            f"- 짧거나 피상적인 요약, 단순 정보 나열은 절대 금지합니다.\n"
            f"- 응답은 오직 생성된 **본문 내용만** 포함해야 합니다. (제목, 태그, 서론/본론 구분자 등 불필요)"
        )
        
        try:
            # --- Generate Body --- 
            response = self._make_api_request(prompt, model, max_tokens, temperature)
            
            generated_body = ""
            placeholder_title = f"{keyword} 최신 동향 분석" # Default title
            generated_tags = [] # Default tags

            if response.get("choices") and len(response["choices"]) > 0:
                generated_body = response["choices"][0].get("message", {}).get("content")
                if generated_body:
                    generated_body = generated_body.strip()
                    self.logger.info(f"Successfully received body from DeepSeek for '{keyword}' (Length: {len(generated_body)}).")
                    self.logger.debug(f"Raw Body:\n{generated_body[:500]}...") # Log excerpt

                    # --- Generate Tags based on the generated body --- 
                    generated_tags = self.generate_tags_from_content(generated_body)
                    # Fallback if tag generation fails
                    if not generated_tags:
                        self.logger.warning("Tag generation failed or returned empty. Using keyword as fallback tag.")
                        generated_tags = [self._normalize_tag(keyword)]
                else:
                    self.logger.warning(f"DeepSeek API response for body was empty.")
                    generated_body = "본문 생성 실패"
                    generated_tags = [self._normalize_tag(keyword)]
            else:
                self.logger.warning(f"Unexpected DeepSeek API response structure for body.")
                self.logger.debug(f"DeepSeek Response: {response}")
                generated_body = "본문 생성 실패"
                generated_tags = [self._normalize_tag(keyword)]

            # Return placeholder title, generated body, and generated/fallback tags
            self.logger.debug(f"Returning - Title: '{placeholder_title}', Body Length: {len(generated_body)}, Tags: {generated_tags}")
            return placeholder_title, generated_body, generated_tags

        except requests.exceptions.RequestException as e:
            self.logger.error(f"Error calling DeepSeek API for body generation: {str(e)}")
            return f"{keyword} 정보 없음", "본문 생성 실패", [self._normalize_tag(keyword)]
        except Exception as e:
            self.logger.error(f"Unexpected error during body generation: {str(e)}", exc_info=True)
            return f"{keyword} 정보 없음", "본문 생성 실패", [self._normalize_tag(keyword)] 