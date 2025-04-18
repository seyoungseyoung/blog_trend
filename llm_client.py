import os
import logging
import re
import requests
from dotenv import load_dotenv
from datetime import datetime
import pytz
from openai import OpenAI

load_dotenv()

# Renamed class from DeepSeekClient to LLMClient
class LLMClient:
    def __init__(self, env_var_name: str, api_url: str):
        self.api_key = os.getenv(env_var_name)
        self.api_url = api_url
        self.logger = logging.getLogger(env_var_name)
        if not self.api_key:
            self.logger.critical(f"API key not found in environment variable: {env_var_name}")
            raise ValueError(f"API key for {env_var_name} not found.")

        # Initialize OpenAI client specifically for Perplexity
        self.openai_client = None
        if "api.perplexity.ai" in self.api_url:
            try:
                # Correct base_url: remove the endpoint path
                base_url_for_openai = self.api_url.replace("/chat/completions", "")
                self.openai_client = OpenAI(api_key=self.api_key, base_url=base_url_for_openai)
                self.logger.info(f"OpenAI client initialized for Perplexity with base URL: {base_url_for_openai}")
            except Exception as e:
                self.logger.error(f"Failed to initialize OpenAI client for Perplexity: {e}")
                # Fallback or raise error depending on desired behavior
                # For now, we'll let it proceed, _call_llm_api will handle None client

    def _call_llm_api(self, model: str, messages: list, max_tokens: int | None = None, temperature: float | None = None) -> dict | None:
        """Generic method to call the LLM API."""
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        
        # Create the basic payload that works for both client types
        payload = {
            "model": model,
            "messages": messages,
        }
        
        # Add optional parameters if provided
        if max_tokens is not None:
            payload["max_tokens"] = max_tokens
        if temperature is not None:
            payload["temperature"] = temperature
        
        # Add additional Perplexity-specific parameters for Sonar model (only for direct requests)
        perplexity_specific_params = {}
        if model == "sonar":
            perplexity_specific_params = {
                "top_p": 0.9,
                "search_domain_filter": ["<any>"],
                "return_images": False,
                "return_related_questions": False,
                "web_search_options": {"search_context_size": "high"}
            }

        try:
            # Use OpenAI client if initialized (i.e., for Perplexity)
            if self.openai_client:
                self.logger.info(f"Calling Perplexity API via OpenAI client with payload: {payload}")
                # Do NOT include the Perplexity-specific parameters when using OpenAI client
                openai_safe_payload = payload.copy()
                # Add only the parameters that are supported by the OpenAI client
                if model == "sonar" and "top_p" in perplexity_specific_params:
                    openai_safe_payload["top_p"] = perplexity_specific_params["top_p"]
                
                response = self.openai_client.chat.completions.create(**openai_safe_payload)
                # Convert the response object to a dictionary format similar to requests response
                return response.model_dump() # Convert Pydantic model to dict
            # Use requests for other APIs (DeepSeek) or direct Perplexity API calls
            else:
                # For direct requests, add the Perplexity-specific parameters if applicable
                if model == "sonar":
                    payload.update(perplexity_specific_params)
                
                self.logger.info(f"Calling API ({self.api_url}) via requests with payload: {payload}")
                response = requests.post(self.api_url, headers=headers, json=payload)
                response.raise_for_status()
                return response.json()

        except requests.exceptions.RequestException as e:
            self.logger.error(f"Error calling LLM API ({self.api_url}): {e}")
            # Log response body if available for debugging 4xx errors
            if e.response is not None:
                 self.logger.error(f"Response status: {e.response.status_code}")
                 try:
                     self.logger.error(f"Response body: {e.response.json()}")
                 except ValueError:
                     self.logger.error(f"Response body: {e.response.text}")
            return None
        except Exception as e: # Catch potential OpenAI client errors too
            self.logger.error(f"Unexpected error during LLM API call ({self.api_url}): {e}")
            # Log details if it's an OpenAI API error, structure might differ
            if hasattr(e, 'response'):
                self.logger.error(f"Response details: {e.response}")
            if hasattr(e, 'status_code'):
                self.logger.error(f"Status code: {e.status_code}")
            if hasattr(e, 'body'):
                self.logger.error(f"Error body: {e.body}")
            if hasattr(e, 'message'):
                self.logger.error(f"Error message: {e.message}")
            return None

    def generate_tags_from_content(self, content: str) -> list[str]:
        """Generate tags from the blog post content using Perplexity API."""
        try:
            # 태그 생성 프롬프트
            prompt = f"""다음 블로그 글 내용을 분석하여 관련 태그를 생성해주세요.
            
            태그 생성 규칙:
            1. 태그는 5-10개 정도 생성
            2. 각 태그는 2-15자 이내로 생성
            3. 태그는 콤마(,)로 구분
            4. 태그에는 특수문자, 공백, 하이프(-), 앰퍼샌드(&), 슬래시(/) 등을 포함하지 않음
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
            response = self._call_llm_api(model="sonar", messages=[{"role": "user", "content": prompt}])
            
            if response and 'choices' in response and len(response['choices']) > 0:
                # 태그 추출 및 정규화
                raw_tags = response['choices'][0]['message']['content'].strip()
                # 콤마로 분리하고 각 태그 정규화
                tags = []
                for tag in raw_tags.split(','):
                    # 태그 정규화: 소문자로 변환, 특수문자 제거, 공백 제거
                    normalized_tag = tag.strip().lower()
                    # 모든 특수문자 제거 (한글, 영문, 숫자만 허용)
                    normalized_tag = re.sub(r'[^가-힣a-z0-9]', '', normalized_tag)
                    # 공백 제거
                    normalized_tag = normalized_tag.replace(' ', '')
                    if normalized_tag:  # 빈 태그는 제외
                        tags.append(normalized_tag)
                
                self.logger.info(f"Generated tags: {tags}")
                return tags
            else:
                self.logger.warning("Failed to generate tags: Empty or invalid API response")
                return []
            
        except Exception as e:
            self.logger.error(f"Error generating tags: {e}")
            return []

    def generate_post_content(self, keyword: str, today_date: str, target_length: int = 700) -> str | None:
        """Generates detailed blog post content using the specified LLM.
        
        Args:
            keyword: The keyword to generate content for
            today_date: The current date in string format
            target_length: Target character length for the post (default: 700)
        
        Returns:
            The generated content or None if generation failed
        """
        # Perplexity Model: Updated based on official example
        # Using "sonar" as the model name with enhanced web search options
        model = "sonar"
        
        # 목표 길이 조정: 참고문헌이 약 300자 정도 차지한다고 가정하고 약간 여유를 둠
        adjusted_target_length = max(target_length - 150, 300)  # 참고문헌 공간 확보 (증가)
        
        prompt = f"""
참고로 오늘은 **{today_date}** 입니다.

**[지시사항 1: 최신 정보 심층 검색 및 분석]**
'{keyword}'에 대한 **최근 48시간 이내의 최신 정보**를 웹에서 심층적으로 조사하고 분석하세요. 반드시 지난 48시간 이내에 작성된 신뢰할 수 있는 출처를 바탕으로, 정보들 사이의 공통점, 차이점, 그리고 가장 중요하거나 빈번하게 언급되는 핵심 트렌드/논점을 **객관적으로 분석하고 종합**하세요. 여러 출처에서 교차 확인되는 내용을 중심으로 정리해야 합니다.

**[지시사항 2: 블로그 본문과 참고문헌 작성]**
위 [지시사항 1]에서 **종합된 내용만을 바탕**으로, **본문 부분은 정확히 {adjusted_target_length}자(±10%)** 분량의 **간결하고 핵심적인** 블로그 게시물을 작성하세요. 글자 수 제한을 엄격하게 지키는 것이 매우 중요합니다. 서론, 본론(검색된 최신 동향 상세 분석, 주요 영향/이슈, 전망 등), 결론의 구조를 갖추는 것이 좋습니다.

**[출처 표기에 관한 중요 지침]**
본문 내용에서 특정 정보나 주장을 언급할 때는 반드시 해당 내용의 출처를 다음과 같이 명시하세요:
1. 본문에서는 번호 형식으로 출처를 표시하세요. 예: [1], [2], [3]
2. 출처 번호는 문장 끝이나 단락 끝 등 적절한 위치에 배치하세요.
3. **반드시 48시간 이내에 발행된 출처만 사용**하세요. 가능한 많은 출처를 사용하되, 5개 미만이어도 괜찮습니다.
4. 본문과 참고문헌 사이에 빈 줄을 두 개 넣으세요.
5. 본문 마지막에 "참고문헌"이라는 제목을 넣고, 그 다음 줄부터 출처 목록을 번호 순서대로 나열하세요.
6. 각 출처는 다음 형식으로 표기하세요: [번호] 출처명, "제목", URL (날짜)
   예시:
   참고문헌
   [1] 건강보험공단, "2025년 건강보험 연말정산 안내", https://www.nhis.or.kr/example (2025.04.19)
   [2] 경제신문, "건강보험 연말정산 간소화된다", https://www.example.com/news/12345 (2025.04.19)

**[매우 중요한 제약 조건]**
- **절대로 검색 결과에 없는 정보를 추측하거나 꾸며내지 마세요 (No Hallucination!).**
- 모든 내용은 반드시 단계 1에서 검색된 실제 최신 정보와 그 출처에 근거해야 합니다.
- **반드시 최근 48시간 이내({today_date} 기준)에 작성된 출처만 사용하세요.**
- 본문 내에 반드시 **실제 출처명**을 포함시켜야 합니다.
- 짧거나 피상적인 요약, 단순 정보 나열은 절대 금지합니다.
- 응답은 오직 생성된 **본문 내용**과 **참고문헌**만 포함해야 합니다. (제목, 태그, 서론/본론 구분자 등 불필요)
- 참고문헌은 절대 중간에 끊기면 안 됩니다. 모든 번호가 본문에 인용된 경우 반드시 해당 참고문헌을 완전히 제공해야 합니다.
"""
        system_message = f"당신은 주어진 키워드와 오늘 날짜를 참고하여 **최근 48시간 이내**의 웹 정보를 깊이 있게 검색/분석하고, 여러 소스에서 확인된 사실과 맥락을 바탕으로 가장 중요하거나 지배적인 narrative/트렌드를 문맥적으로 종합하는 AI 분석가입니다. 반드시 검색된 정보에만 기반하여 답변해야 하며, 절대 정보를 꾸며내서는 안 됩니다. 이 종합된 통찰력을 바탕으로, 구체적인 구조를 갖춘 **정확히 {adjusted_target_length}자(±10%)** 분량의 간결하고 핵심적인 블로그 글 '본문'과 별도의 '참고문헌' 섹션을 생성하며, 본문에는 반드시 사용된 정보의 구체적인 출처명을 명시해야 합니다. 글자 수 제한을 반드시 준수하세요."

        messages = [
            {"role": "system", "content": system_message},
            {"role": "user", "content": prompt}
        ]

        self.logger.info(f"Generating CONTENT for keyword: '{keyword}' using {model}... (Today: {today_date}, Targeting ~{adjusted_target_length} chars for main content)")
        
        # 글자 수에 맞게 max_tokens 값 조정 (한국어는 문자당 약 0.5-0.7 토큰으로 계산)
        # 한 번에 충분한 내용 생성을 위해 큰 max_tokens 설정 (실제 과금은 사용된 토큰만큼만 됨)
        max_tokens = 4000  # 충분히 큰 값으로 설정 (출처까지 완전히 가져올 수 있도록)
        
        # API 호출
        response_data = self._call_llm_api(model=model, messages=messages, max_tokens=max_tokens, temperature=0.7)

        if response_data:
            try:
                # Get content from response based on client type
                if self.openai_client:
                    content = response_data['choices'][0]['message']['content'].strip()
                else:
                    content = response_data['choices'][0]['message']['content'].strip()
                
                # 본문과 참고문헌 분리 (정규식을 개선하여 다양한 형태의 "참고문헌" 제목을 인식)
                parts = re.split(r'참고문헌[\s]*|references[\s]*', content, flags=re.IGNORECASE)
                
                if len(parts) > 1:
                    # 본문과 참고문헌이 제대로 분리됨
                    main_content = parts[0].strip()
                    references = parts[1].strip()
                    
                    # 본문에서 언급된 참고문헌 번호 추출
                    main_reference_mentions = re.findall(r'\[(\d+)\]', main_content)
                    mentioned_refs = set([int(num) for num in main_reference_mentions if num.isdigit()])
                    self.logger.info(f"References mentioned in content: {sorted(list(mentioned_refs))}")
                    
                    # 참고문헌에서 실제 포함된 번호 추출
                    reference_lines = references.strip().split('\n')
                    reference_numbers = []
                    for line in reference_lines:
                        match = re.match(r'^\s*\[(\d+)\]', line)
                        if match:
                            reference_numbers.append(int(match.group(1)))
                    
                    # 참고문헌이 제대로 포함되었는지 확인
                    missing_refs = mentioned_refs - set(reference_numbers)
                    if missing_refs:
                        self.logger.warning(f"Missing references: {missing_refs}. Reference section might be incomplete.")
                        # 일반적으로 퍼플렉시티가 가져온 참고문헌은 완전할 가능성이 높기 때문에 그대로 사용
                        
                    # 본문 길이 확인 및 조정
                    main_content_length = len(main_content)
                    ref_content_length = len(references)
                    self.logger.info(f"Main content length: {main_content_length} chars, References length: {ref_content_length} chars")
                    
                    if abs(main_content_length - adjusted_target_length) > adjusted_target_length * 0.2:
                        self.logger.warning(f"Main content length ({main_content_length}) differs significantly from adjusted target ({adjusted_target_length})")
                    
                    # 본문과 참고문헌 결합하여 반환
                    final_content = main_content.rstrip() + "\n\n참고문헌\n" + references
                    self.logger.info(f"Successfully processed content - Total length: {len(final_content)} chars")
                    return final_content
                else:
                    # 참고문헌 섹션이 명확하게 구분되지 않은 경우
                    self.logger.warning("No clear references section found in the generated content")
                    
                    # 본문에서 참고문헌 형식이 포함되었는지 확인
                    # 예: 마지막 부분이 [1] 출처명, "제목", URL (날짜) 형식인지 확인
                    matches = re.findall(r'\[\d+\]\s+[\w\s]+,\s+"[^"]+",\s+https?://[^\s]+', content)
                    
                    if matches:
                        # 참고문헌 형식의 내용이 있지만 "참고문헌" 제목이 없는 경우
                        # 마지막 [숫자] 인용 위치를 찾아 해당 위치 이후를 참고문헌으로 처리
                        citation_indexes = [(m.start(), m.group(0)) for m in re.finditer(r'\[\d+\]', content)]
                        if citation_indexes:
                            # 본문의 마지막 인용 이후 위치를 찾음
                            main_content_end = 0
                            # 역순으로 검색하여 [숫자] 형태의 첫 참고문헌 시작점 찾기
                            for i in range(len(citation_indexes)-1, -1, -1):
                                pos, citation = citation_indexes[i]
                                if pos > 0 and content[pos-1] not in ['[', ']', '(', ')', ',', '.', ':', ';']:
                                    # 본문 내 인용이 아닌 첫 번째 [숫자] 형태 찾음
                                    main_content_end = pos
                                    break
                            
                            if main_content_end > 0:
                                # 본문과 참고문헌 분리
                                main_content = content[:main_content_end].strip()
                                references = content[main_content_end:].strip()
                                
                                final_content = main_content + "\n\n참고문헌\n" + references
                                self.logger.info(f"Manually extracted references from content - Total length: {len(final_content)} chars")
                                return final_content
                    
                    # 그 외의 경우, 원본 그대로 반환
                    self.logger.info(f"Returning unmodified content - Length: {len(content)} chars")
                    return content
                
            except (KeyError, IndexError, TypeError) as e:
                self.logger.warning(f"Unexpected {model} API response structure: {e}")
                return content  # 오류 발생 시 원본 내용 반환
        else:
            self.logger.warning(f"Failed to get content from {model}.")
            return None 