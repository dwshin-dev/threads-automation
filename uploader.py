import os
import re
import json
import random
import asyncio
import hashlib
import logging
import openai
import pandas as pd
import google.generativeai as genai
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeoutError

logger = logging.getLogger("threads_pro_uploader")

def safe_session_name(username):
    """세션 파일명에 쓸 안전한 이름을 생성.

    영문/숫자/밑줄 이외 문자를 제거하되, 제거로 인해 서로 다른 닉네임이
    같은 파일명으로 뭉개지지 않도록 원본 닉네임의 해시를 덧붙인다.
    (순수 영문/숫자 닉네임은 기존 파일명이 그대로 유지됨)
    """
    username = username or ""
    stripped = re.sub(r"[^a-zA-Z0-9_]", "", username)
    if stripped == username and stripped:
        return stripped
    suffix = hashlib.md5(username.encode("utf-8")).hexdigest()[:8]
    return f"{stripped}_{suffix}" if stripped else f"u_{suffix}"

def rewrite_content(text, provider, api_key, system_prompt):
    """지정한 AI 엔진을 사용해 스레드 본문을 변환(Rewriting)"""
    if not text or not api_key or provider in ('OFF', 'Free'):
        return text
        
    try:
        if provider == 'GPT':
            logger.info("GPT AI 리라이팅 시작...")
            client = openai.OpenAI(api_key=api_key)
            response = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": text}
                ],
                max_tokens=400,
                temperature=0.7
            )
            rewritten = response.choices[0].message.content.strip()
            logger.info("GPT AI 리라이팅 성공.")
            return rewritten
            
        elif provider == 'Gemini':
            logger.info("Gemini AI 리라이팅 시작...")
            genai.configure(api_key=api_key)
            
            model_candidates = ["gemini-2.5-flash", "gemini-2.0-flash", "gemini-flash-latest"]
            success = False
            rewritten = text
            last_err = None
            
            for m_name in model_candidates:
                try:
                    actual_model_name = f"models/{m_name}" if not m_name.startswith("models/") else m_name
                    model = genai.GenerativeModel(
                        model_name=actual_model_name,
                        system_instruction=system_prompt
                    )
                    response = model.generate_content(text)
                    rewritten = response.text.strip()
                    logger.info(f"Gemini AI 리라이팅 성공 (사용 모델: {actual_model_name}).")
                    success = True
                    break
                except Exception as e:
                    last_err = e
                    logger.warning(f"Gemini 모델 {m_name} 호출 실패: {e}")
                    continue
            
            if not success:
                raise last_err if last_err else Exception("모든 Gemini 모델 호출에 실패했습니다.")
                
            return rewritten
            
    except Exception as e:
        logger.error(f"AI 리라이팅 오류 ({provider}): {e}")
        
    return text

class ThreadsProUploader:
    def __init__(self, session_dir, log_callback=None):
        self.session_dir = os.path.abspath(session_dir)
        self.log_callback = log_callback
        os.makedirs(self.session_dir, exist_ok=True)

    def log(self, message):
        logger.info(message)
        if self.log_callback:
            self.log_callback(message)

    async def human_move_and_click(self, page, target, name="요소"):
        """마우스를 사람처럼 S자 곡선(Cubic Bezier)으로 이동시킨 후 신뢰성 높은 CDP 클릭을 수행"""
        try:
            await target.scroll_into_view_if_needed()
            box = await target.bounding_box()
            if not box:
                return False
                
            # 현재 마우스 가상 좌표가 없으면 랜덤 영역에서 시작하도록 설정
            if not hasattr(self, 'mouse_x') or not hasattr(self, 'mouse_y'):
                self.mouse_x = random.uniform(100, 500)
                self.mouse_y = random.uniform(100, 500)
                await page.mouse.move(self.mouse_x, self.mouse_y)
                
            # 타겟 내부에 미세한 임의의 타겟 점 생성 (정중앙이 아닌 인간적인 오차 범위 부여)
            target_x = box['x'] + box['width'] / 2 + random.uniform(-box['width'] * 0.1, box['width'] * 0.1)
            target_y = box['y'] + box['height'] / 2 + random.uniform(-box['height'] * 0.1, box['height'] * 0.1)
            
            # Bezier 곡선 생성을 위한 제어점 계산 (S자 형태로 흔들리도록 구성)
            c1_x = self.mouse_x + (target_x - self.mouse_x) * 0.25 + random.uniform(-100, 100)
            c1_y = self.mouse_y + (target_y - self.mouse_y) * 0.25 + random.uniform(-100, 100)
            c2_x = self.mouse_x + (target_x - self.mouse_x) * 0.75 + random.uniform(-100, 100)
            c2_y = self.mouse_y + (target_y - self.mouse_y) * 0.75 + random.uniform(-100, 100)
            
            # 15 ~ 25단계의 미세 프레임으로 쪼개서 이동
            steps = random.randint(15, 25)
            for i in range(steps + 1):
                t = i / steps
                # 3차 베지에 공식 보간
                x = (1-t)**3 * self.mouse_x + 3*(1-t)**2 * t * c1_x + 3*(1-t)*t**2 * c2_x + t**3 * target_x
                y = (1-t)**3 * self.mouse_y + 3*(1-t)**2 * t * c1_y + 3*(1-t)*t**2 * c2_y + t**3 * target_y
                await page.mouse.move(x, y)
                await asyncio.sleep(random.uniform(0.005, 0.015))
                
            # 좌표 최종 갱신
            self.mouse_x = target_x
            self.mouse_y = target_y
            
            # 미세 대기 후 Playwright 내장 고신뢰성 CDP 클릭 수행 (백그라운드/헤드리스 안정성 확보)
            await asyncio.sleep(random.uniform(0.1, 0.2))
            await target.click(timeout=3000)
            return True
        except Exception as e:
            self.log(f"[{name}] 마우스 S자 이동 및 클릭 실패: {e}")
            return False

    async def human_scroll(self, page, delta_y):
        """마우스 휠(wheel) 이벤트를 연속적으로 가감속 분할하여 사람처럼 휠을 굴리는 자연스러운 스크롤 모션 재현"""
        try:
            # delta_y를 여러 단계의 휠 이벤트로 분할 (가속/감속 효과)
            steps = random.randint(8, 15)
            # 가상 시작 위치로 마우스 커서 사전 이동 (드래그가 아니므로 text highlight 원천 방지)
            start_x = random.uniform(300, 700)
            start_y = random.uniform(200, 600)
            await page.mouse.move(start_x, start_y)
            
            for i in range(steps + 1):
                t = i / steps
                # 가감속 (Ease-In-Out) 수식으로 매 단계 휠 양 계산
                current_scroll = delta_y * (3 * t**2 - 2 * t**3)
                if i > 0:
                    prev_scroll = delta_y * (3 * ( (i-1)/steps )**2 - 2 * ( (i-1)/steps )**3)
                    step_delta = current_scroll - prev_scroll
                    await page.mouse.wheel(0, step_delta)
                await asyncio.sleep(random.uniform(0.02, 0.05))
            return True
        except Exception:
            try:
                # 백업: 일괄 휠 스크롤
                await page.mouse.wheel(0, delta_y)
                return True
            except Exception:
                return False

    async def click_element(self, page, selector_or_locator, name="요소", timeout=3000):
        """다양한 클릭 방식으로 요소를 확실하게 클릭하는 헬퍼 함수"""
        if isinstance(selector_or_locator, str):
            if selector_or_locator.startswith("xpath=") or selector_or_locator.startswith("//"):
                loc = page.locator(selector_or_locator)
            else:
                loc = page.locator(selector_or_locator).filter(visible=True)
                if await loc.count() == 0:
                    loc = page.locator(selector_or_locator)
        else:
            loc = selector_or_locator

        count = await loc.count()
        if count == 0:
            return False

        for i in range(count):
            el = loc.nth(i)
            try:
                if not await el.is_visible():
                    continue

                target = el
                try:
                    ancestor = el.locator('xpath=./ancestor::*[self::button or self::a or @role="button"]').first
                    if await ancestor.count() > 0 and await ancestor.is_visible():
                        target = ancestor
                except Exception:
                    pass

                # 0단계: 인간 마우스 S자 이동 및 물리적 클릭 시도 (생체 감지 통과)
                try:
                    success = await self.human_move_and_click(page, target, name)
                    if success:
                        return True
                except Exception:
                    pass

                # 1단계: 일반 클릭
                try:
                    await target.click(timeout=timeout)
                    return True
                except Exception:
                    pass

                # 2단계: 강제 클릭 (인터셉트 우회)
                try:
                    await target.click(force=True, timeout=timeout)
                    return True
                except Exception:
                    pass

                # 3단계: JS DOM 클릭
                try:
                    await target.evaluate("el => (el.closest('button, [role=\"button\"], a') || el).click()")
                    return True
                except Exception:
                    pass
            except Exception as e:
                self.log(f"[Click] {name} (index: {i}) 클릭 시도 중 에러: {e}")
                continue

        return False

    async def run_manual_login(self, username):
        """특정 계정으로 로그인 창을 띄워 세션 쿠키를 sessions/ 폴더에 영구 보관"""
        safe_username = safe_session_name(username)
        session_file = os.path.join(self.session_dir, f"{safe_username}.json")
        profile_dir = os.path.join(self.session_dir, f"profile_{safe_username}")
        
        # SingletonLock 등 크롬 잠금 파일 제거 (비정상 종료 대비)
        for lock_name in ["SingletonLock", "SingletonSocket", "SingletonCookie"]:
            lock_path = os.path.join(profile_dir, lock_name)
            if os.path.exists(lock_path) or os.path.islink(lock_path):
                try:
                    os.unlink(lock_path)
                    self.log(f"[{username}] 브라우저 잠금 파일({lock_name})을 정리했습니다.")
                except Exception as e:
                    self.log(f"[{username}] 브라우저 잠금 파일 정리 중 예외 발생: {e}")

        self.log(f"[{username}] 계정 수동 로그인 브라우저 구동 중...")
        
        async with async_playwright() as p:
            # Persistent Context를 띄워 자동 로그인 쿠키 획득 보장
            # user_agent를 생략하여 headful 크롬 본연의 정상적인 User-Agent와 API 일치도를 높임
            context = await p.chromium.launch_persistent_context(
                user_data_dir=profile_dir,
                headless=False,
                locale="ko-KR",
                args=["--disable-blink-features=AutomationControlled", "--window-size=1024,860"],
                viewport={"width": 1024, "height": 860}
            )
            
            page = context.pages[0] if context.pages else await context.new_page()
            await page.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
            
            # 인스타그램 로그인 페이지로 선 진입하여 안전하게 로그인 세션 확보
            await page.goto("https://www.instagram.com/accounts/login/")
            self.log("안전한 연동을 위해 인스타그램 로그인 페이지로 접속했습니다. 브라우저 창에서 인스타그램 로그인을 먼저 완료해 주세요.")
            
            # 로그인 성공 여부를 주기적으로 체크
            logged_in = False
            last_url = ""
            redirected_to_threads = False
            
            while True:
                # 사용자가 창을 강제로 닫았는지 확인
                if page.is_closed() or context.pages == []:
                    break
                
                current_url = page.url
                if current_url != last_url:
                    self.log(f"[{username}] 브라우저 주소 변경: {current_url}")
                    last_url = current_url
                
                # 1. 인스타그램 로그인 성공 여부 검사 (쿠키 확인)
                if not redirected_to_threads:
                    try:
                        cookies = await context.cookies()
                        is_ig_logged_in = any(c['name'] in ['ds_user_id', 'sessionid'] and 'instagram.com' in c['domain'] for c in cookies)
                        if is_ig_logged_in:
                            self.log(f"[{username}] 인스타그램 로그인 완료가 감지되었습니다! 스레드로 이동하여 연동을 진행합니다...")
                            await page.goto("https://www.threads.net/login")
                            redirected_to_threads = True
                            await asyncio.sleep(3)
                            continue
                    except Exception:
                        pass
                
                # 404 에러 페이지 감지 시 self-healing 리다이렉트 수행
                try:
                    page_html = await page.content()
                    is_404 = "길을 잃었습니다" in page_html or "방황하는 모든 자가" in page_html
                    if is_404:
                        self.log(f"[{username}] 로그인 404 오류 화면이 감지되었습니다. 메인 홈으로 강제 이동합니다...")
                        await page.goto("https://www.threads.net/")
                        await asyncio.sleep(4)  # 로딩 대기
                        continue
                except Exception:
                    pass
                
                # 로그인 완료 판단 조건: URL이 threads.net 이나 threads.com 이고 login을 포함하지 않음
                if ("threads.net" in current_url or "threads.com" in current_url) and "login" not in current_url:
                    try:
                        # 로그인 성공 시 노출되는 주요 요소들 목록
                        selectors = [
                            'a[href="/write"]',
                            'svg[aria-label="새로운 스레드"]',
                            'svg[aria-label="Write"]',
                            'svg[aria-label="홈"]',
                            'svg[aria-label="Home"]',
                            'svg[aria-label="검색"]',
                            'svg[aria-label="Search"]',
                            'svg[aria-label="활동"]',
                            'svg[aria-label="Activity"]',
                            'svg[aria-label="프로필"]',
                            'svg[aria-label="Profile"]',
                            'a[href^="/@"]'
                        ]
                        
                        is_verified = False
                        for sel in selectors:
                            if await page.locator(sel).count() > 0:
                                is_verified = True
                                break
                                
                        if is_verified:
                            logged_in = True
                            break
                    except Exception:
                        pass
                
                await asyncio.sleep(1)
                
            if logged_in:
                self.log("로그인 성공이 감지되었습니다! 세션 상태를 저장하는 중...")
                await asyncio.sleep(3)  # 쿠키 안정화 대기
                storage_state = await context.storage_state()
                
                # 실제 로그인한 스레드 핸들(아이디) 추출 시도
                actual_username = None
                try:
                    profile_btn = page.locator('a[href^="/@"]').first
                    if await profile_btn.count() > 0:
                        href = await profile_btn.get_attribute("href")
                        if href:
                            actual_username = href.strip("/").replace("@", "")
                except Exception as e:
                    self.log(f"실제 계정 아이디 추출 중 오류: {e}")
                    
                if actual_username:
                    self.log(f"[{username}] 실제 로그인된 아이디 확인됨: @{actual_username}")
                    # config.json 업데이트
                    try:
                        config_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")
                        if os.path.exists(config_path):
                            with open(config_path, 'r', encoding='utf-8') as f:
                                config = json.load(f)
                            if "account_handles" not in config:
                                config["account_handles"] = {}
                            config["account_handles"][username] = actual_username
                            with open(config_path, 'w', encoding='utf-8') as f:
                                json.dump(config, f, ensure_ascii=False, indent=2)
                    except Exception as e:
                        self.log(f"설정 파일 저장 중 예외 발생: {e}")
                
                with open(session_file, 'w', encoding='utf-8') as f:
                    json.dump(storage_state, f, ensure_ascii=False, indent=2)
                self.log(f"[{username}] 로그인 세션이 '{safe_username}.json'에 성공적으로 저장되었습니다.")
            else:
                self.log("경고: 로그인이 완료되지 않은 상태에서 브라우저가 종료되었습니다.")
                
            await context.close()
            return logged_in

    async def post_to_threads(self, username, headless, content, media_paths, comment_text, topic_text="", publish_delay=10):
        """Playwright 세션을 이용하여 본문 게시 및 첫 댓글(쿠팡 파자너스 등) 자동화 수행"""
        safe_username = safe_session_name(username)
        session_file = os.path.join(self.session_dir, f"{safe_username}.json")
        user_profile_dir = os.path.join(self.session_dir, f"profile_{safe_username}")
        
        if not os.path.exists(session_file):
            self.log(f"[{username}] 오류: 저장된 로그인 세션이 없습니다. 먼저 설정을 완료해주세요.")
            return False

        self.log(f"[{username}] 포스팅 프로세스 개시...")
        
        async with async_playwright() as p:
            # 표준 브라우저 기동 및 저장된 세션 파일 주입
            launch_args = ["--disable-blink-features=AutomationControlled"]
            if not headless:
                launch_args.append("--window-size=1024,860")

            browser = await p.chromium.launch(
                headless=headless,
                args=launch_args
            )
            
            context_kwargs = {
                "storage_state": session_file,
                "user_agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "locale": "ko-KR"
            }
            if not headless:
                context_kwargs["viewport"] = {"width": 1024, "height": 860}
            else:
                context_kwargs["viewport"] = {"width": 1280, "height": 800}
                
            context = await browser.new_context(**context_kwargs)
            
            page = await context.new_page()
            await page.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
            
            try:
                await page.goto("https://www.threads.net/", timeout=45000)
                # Threads 홈은 피드를 계속 불러와 networkidle에 도달하지 못하는 경우가 많으므로
                # 짧게만 기다리고 실패해도 그대로 진행한다 (간헐적 타임아웃 실패 방지)
                try:
                    await page.wait_for_load_state("networkidle", timeout=10000)
                except Exception:
                    pass
                await asyncio.sleep(2)
                
                # 로그인 상태 또는 로그아웃 상태 감지 대기 (최대 10초)
                self.log(f"[{username}] 로그인 세션 상태 검증 중...")
                is_logged_in = False
                for _ in range(100):
                    logged_in_selectors = [
                        'a[href="/write"]',
                        'svg[aria-label="새로운 스레드"]',
                        'svg[aria-label="Write"]',
                        'div[role="button"]:has-text("새로운 스레드")',
                        'div[role="button"]:has-text("New thread")'
                    ]
                    logged_out_selectors = [
                        'text="Instagram으로 계속"',
                        'text="Continue with Instagram"',
                        'text="Instagram으로 로그인"',
                        'text="Log in with Instagram"',
                        'text="사용자 이름으로 로그인"',
                        'text="Log in with username"',
                        'button:has-text("로그인")',
                        'button:has-text("Log in")'
                    ]
                    
                    found_logged_out = False
                    for sel in logged_out_selectors:
                        if await page.locator(sel).filter(visible=True).count() > 0:
                            found_logged_out = True
                            break
                            
                    if found_logged_out:
                        is_logged_in = False
                        break
                        
                    found_logged_in = False
                    for sel in logged_in_selectors:
                        if await page.locator(sel).filter(visible=True).count() > 0:
                            found_logged_in = True
                            break
                            
                    if found_logged_in:
                        is_logged_in = True
                        break
                        
                    await asyncio.sleep(0.1)
                    
                if not is_logged_in:
                    self.log(f"[{username}] 오류: 로그인 세션이 만료되었거나 비활성 상태입니다. 수동 로그인을 다시 완료해 주세요.")
                    await context.close()
                    await browser.close()
                    return False
                    
                self.log(f"[{username}] 로그인 상태가 확인되었습니다.")
                
                # 0. Anti-bot Warmup (피드 스크롤 및 무작위 좋아요)
                self.log(f"[{username}] 봇 감지 우회를 위한 사전 워밍업(피드 스크롤 및 무작위 좋아요) 시작...")
                try:
                    # 3~5회 스크롤 다운 수행
                    scroll_steps = random.randint(3, 5)
                    for step in range(scroll_steps):
                        scroll_y = random.randint(300, 700)
                        await self.human_scroll(page, scroll_y)
                        self.log(f"[{username}] 피드 스크롤 중... ({step + 1}/{scroll_steps})")
                        await asyncio.sleep(random.uniform(1.5, 3.0))
                except Exception as warm_err:
                    self.log(f"[{username}] 경고: 워밍업 진행 중 오류 발생 (계속 진행): {warm_err}")
                 # 1. 새 글 작성 모달 열기
                editor_selectors = [
                    'div[role="textbox"]',
                    'div[contenteditable="true"]',
                    '[contenteditable="true"]',
                    'div[data-lexical-editor="true"]',
                    '[role="textbox"]',
                    'textarea'
                ]
                
                opened = False
                write_selectors = [
                    'a[href="/compose"]',
                    'div[role="button"]:has-text("새로운 스레드")',
                    'div[role="button"]:has-text("New thread")',
                    'div[role="button"]:has-text("Write")',
                    'svg[aria-label="새로운 스레드"]',
                    'svg[aria-label="Write"]',
                    'svg[aria-label="New thread"]'
                ]
                
                for selector in write_selectors:
                    if await self.click_element(page, selector, f"작성 창 열기 ({selector})"):
                        # 실제로 에디터 창이 나타났는지 대기 검증 (최대 2.5초)
                        for _ in range(25):
                            for ed_sel in editor_selectors:
                                try:
                                    if await page.locator(ed_sel).first.is_visible():
                                        opened = True
                                        break
                                except Exception:
                                    pass
                            if opened:
                                break
                            await asyncio.sleep(0.1)
                        if opened:
                            break
                        
                if not opened:
                    # 단축키 'c' 시도
                    self.log(f"[{username}] 경고: 클릭으로 작성 창을 열지 못했습니다. 단축키 'c'를 시도합니다.")
                    try:
                        await page.keyboard.press("c")
                        # 실제로 에디터 창이 나타났는지 대기 검증 (최대 3초)
                        for _ in range(30):
                            for ed_sel in editor_selectors:
                                try:
                                    if await page.locator(ed_sel).first.is_visible():
                                        opened = True
                                        break
                                except Exception:
                                    pass
                            if opened:
                                self.log(f"[{username}] 단축키 'c'로 작성 창 열기 성공")
                                break
                            await asyncio.sleep(0.1)
                    except Exception as e:
                        self.log(f"[{username}] 단축키 'c' 시도 실패: {e}")
                        
                if not opened:
                    self.log(f"[{username}] 오류: 작성 창을 열지 못했습니다.")
                    await context.close()
                    await browser.close()
                    return False
                
                # 1-2. 작성 다이얼로그 컨테이너 감지
                dialog = page
                dialog_selectors = [
                    'div[role="dialog"]',
                    'div:has(span:has-text("취소"))',
                    'div:has(span:has-text("Cancel"))',
                    'div:has(div:has-text("취소"))',
                    'div:has(div:has-text("Cancel"))',
                    'div:has(div[role="button"]:has-text("게시"))',
                    'div:has(div[role="button"]:has-text("Post"))'
                ]
                for sel in dialog_selectors:
                    try:
                        loc = page.locator(sel).first
                        if await loc.count() > 0 and await loc.is_visible():
                            dialog = loc
                            self.log(f"[{username}] 다이얼로그 컨테이너 감지 성공 (선택기: {sel})")
                            break
                    except Exception:
                        continue

                # 2. 에디터 텍스트 주입
                await asyncio.sleep(1)
                
                editor = None
                for selector in editor_selectors:
                    try:
                        loc = dialog.locator(selector).first
                        await loc.wait_for(state="visible", timeout=3000)
                        editor = loc
                        break
                    except Exception:
                        continue
                        
                if not editor:
                    screenshot_path = os.path.join(self.session_dir, f"error_editor_{username}.png")
                    await page.screenshot(path=screenshot_path)
                    self.log(f"[{username}] 오류: 에디터를 찾지 못했습니다. (스크린샷: {screenshot_path})")
                    await context.close()
                    return False
                    
                await editor.focus()
                await page.keyboard.type(content)
                await asyncio.sleep(2)
                
                # 2-2. 주제(Topic) 설정
                # (주제는 app.py에서 해시태그 형식으로 본문에 자동 병합되므로 추가 UI 조작을 생략합니다)
                await asyncio.sleep(1)
                
                # 3. 미디어 파일 첨부 (카드뉴스)
                if media_paths:
                    self.log(f"[{username}] 미디어 파일 첨부 중... ({len(media_paths)}개)")
                    
                    # 파일 경로 정상화 (NFC/NFD 호환성 보장)
                    import unicodedata
                    normalized_paths = []
                    for path in media_paths:
                        nfc_path = unicodedata.normalize('NFC', path)
                        nfd_path = unicodedata.normalize('NFD', path)
                        if os.path.exists(nfd_path):
                            normalized_paths.append(nfd_path)
                        elif os.path.exists(nfc_path):
                            normalized_paths.append(nfc_path)
                        else:
                            normalized_paths.append(path)
                            
                    # 영상(mp4/mov)은 img가 아닌 video 태그로 프리뷰가 생기므로 둘 다 센다
                    initial_img_count = await dialog.locator('img, video').count()
                    
                    # 1) Native input[type="file"] 요소를 통해 직접 파일 주입 시도 (FileChooser 대기 생략으로 타임아웃 원천 방지)
                    uploaded_via_input = False
                    try:
                        file_input = dialog.locator('input[type="file"]')
                        if await file_input.count() > 0:
                            await file_input.first.set_input_files(normalized_paths)
                            uploaded_via_input = True
                    except Exception as input_err:
                        self.log(f"[{username}] 직접 파일 주입 실패, 기존 방식(FileChooser)으로 재시도합니다: {input_err}")
                        
                    # 2) 직접 주입 실패 시 기존 FileChooser 이벤트 클릭 방식 수행
                    if not uploaded_via_input:
                        attach_btn_selectors = [
                            'svg[aria-label="미디어 첨부"]',
                            'svg[aria-label="Attach media"]'
                        ]
                        attach_btn = None
                        for sel in attach_btn_selectors:
                            loc = dialog.locator(sel).filter(visible=True)
                            if await loc.count() > 0:
                                attach_btn = loc.first
                                break
                                
                        if attach_btn:
                            try:
                                async with page.expect_file_chooser() as fc_info:
                                    clicked = await self.click_element(page, attach_btn, "미디어 첨부 버튼")
                                    if not clicked:
                                        raise Exception("미디어 첨부 버튼 클릭 실패")
                                file_chooser = await fc_info.value
                                await file_chooser.set_files(normalized_paths)
                            except Exception as upload_err:
                                self.log(f"[{username}] 미디어 업로드 중 에러 발생: {upload_err}")
                        else:
                            self.log(f"[{username}] 경고: 파일 첨부 버튼을 찾지 못해 본문만 게시합니다.")
                            
                    # 업로드 완료 대기 (최대 10초, 100ms 단위 반응형 폴링)
                    self.log(f"[{username}] 미디어 업로드 및 프리뷰 생성 대기 중 (최대 10초)...")
                    uploaded_successfully = False
                    for _ in range(100):
                        current_img_count = await dialog.locator('img, video').count()
                        if current_img_count >= initial_img_count + len(normalized_paths):
                            uploaded_successfully = True
                            break
                        await asyncio.sleep(0.1)
                        
                    if uploaded_successfully:
                        self.log(f"[{username}] 미디어 업로드 완료 확인 (이미지 {len(normalized_paths)}개 추가됨)")
                    else:
                        self.log(f"[{username}] 경고: 10초 내에 미디어 프리뷰가 완전히 생성되지 않았습니다. 현재 상태로 포스팅을 진행합니다.")
                
                # 4. 스레드 추가 (댓글/링크용 2/2 포스트 영역 생성 및 기입)
                if comment_text:
                    self.log(f"[{username}] 스레드 추가(2/2) 작성 프로세스 시작...")
                    
                    add_btn_selectors = [
                        'span:has-text("스레드에 추가")',
                        'span:has-text("Add to thread")',
                        ':text("스레드에 추가")',
                        ':text("Add to thread")',
                        'xpath=//*[(self::div or self::span or self::button) and not(*) and (normalize-space()="스레드에 추가" or contains(text(), "스레드에 추가") or normalize-space()="Add to thread" or contains(text(), "Add to thread"))]',
                    ]
                    
                    clicked_add = False
                    for sel in add_btn_selectors:
                        if await self.click_element(page, dialog.locator(sel), "'스레드에 추가' 버튼"):
                            clicked_add = True
                            break
                            
                    if clicked_add:
                        await asyncio.sleep(1.5)
                        
                        editors = dialog.locator('div[role="textbox"], [contenteditable="true"]')
                        for _ in range(50):
                            if await editors.count() >= 2:
                                break
                            await asyncio.sleep(0.1)
                            
                        if await editors.count() >= 2:
                            comment_editor = editors.nth(1)
                            await comment_editor.focus()
                            await page.keyboard.type(comment_text)
                            self.log(f"[{username}] 두 번째 스레드 칸에 댓글 텍스트 입력 완료.")
                            await asyncio.sleep(0.5)
                            
                            # 두 번째 작성 창 영역 내 링크 카드 감지 및 제거
                            if "http" in comment_text or "www." in comment_text:
                                self.log(f"[{username}] 링크 감지됨. 미리보기 카드 제거 대기 중...")
                                
                                second_post_container = comment_editor.locator("xpath=./ancestor::div[4]")
                                close_btn = second_post_container.locator('[aria-label="삭제"], [aria-label="제거"], [aria-label="Dismiss"], [aria-label="Remove"]')
                                
                                try:
                                    # Wait for link preview card close button to load and become visible
                                    await close_btn.first.wait_for(state="visible", timeout=8000)
                                    self.log(f"[{username}] 링크 프리뷰 삭제 버튼이 감지되었습니다.")
                                except Exception as e:
                                    self.log(f"[{username}] 경고: 링크 프리뷰 삭제 버튼 대기 중 타임아웃 혹은 에러: {e}")
                                    
                                removed = False
                                count = await close_btn.count()
                                for i in range(count):
                                    btn = close_btn.nth(i)
                                    if await self.click_element(page, btn, "링크 미리보기 제거 버튼"):
                                        removed = True
                                        await asyncio.sleep(1)
                                        break
                        else:
                            self.log(f"[{username}] 오류: 스레드 추가 입력 칸(2/2)을 찾지 못했습니다.")
                            await context.close()
                            await browser.close()
                            return False
                    else:
                        self.log(f"[{username}] 오류: '스레드에 추가' 버튼을 찾지 못해 본문만 게시합니다.")
                
                # 5. 최종 발행하기 (일괄 업로드)
                self.log(f"[{username}] 스레드 일괄 발행 중...")
                posted = False
                
                # API 네트워크 통신 모니터링 로그 등록 (서버 응답 확인용)
                async def handle_response(res):
                    try:
                        req = res.request
                        if req.method == "POST":
                            post_data = req.post_data
                            response_text = await res.text()
                            self.log(f"[Network Log] POST {res.url} (Status: {res.status})")
                            if post_data:
                                self.log(f"[Network Log] Request: {post_data[:300]}")
                            self.log(f"[Network Log] Response: {response_text[:400]}")
                    except Exception:
                        pass
                page.on("response", handle_response)
                
                selectors = [
                    'div[role="button"]:text-is("게시")',
                    'div[role="button"]:text-is("Post")',
                    'button:text-is("게시")',
                    'button:text-is("Post")',
                    'xpath=//*[(self::div or self::button or self::span or @role="button") and not(self::svg) and (normalize-space(text())="게시" or normalize-space(text())="Post" or normalize-space(text())="답글" or normalize-space(text())="Reply" or @aria-label="게시" or @aria-label="Post" or @aria-label="답글" or @aria-label="Reply")]',
                    'div[role="button"].x1i10hfl',
                    'button.x1i10hfl'
                ]
                
                # 5-2. 게시 버튼이 활성화(enabled)될 때까지 대기 및 클릭 시도 (최대 5초)
                btn_found = False
                for attempt in range(1, 4):
                    post_btn = None
                    for _ in range(25):
                        for selector in selectors:
                            try:
                                loc = dialog.locator(selector)
                                count = await loc.count()
                                for i in range(count):
                                    el = loc.nth(i)
                                    if await el.is_visible():
                                        aria_disabled = await el.get_attribute("aria-disabled")
                                        is_native_disabled = await el.get_attribute("disabled")
                                        if aria_disabled != "true" and is_native_disabled is None:
                                            post_btn = el
                                            break
                                if post_btn:
                                    break
                            except Exception:
                                continue
                        if post_btn:
                            break
                        await asyncio.sleep(0.2)
                        
                    if post_btn:
                        # click_element 헬퍼를 활용해 마우스 S자 이동 및 물리적 클릭으로 확실하게 처리
                        if await self.click_element(page, post_btn, "게시 버튼"):
                            btn_found = True
                            self.log(f"[{username}] 게시 버튼 클릭 완료 (시도: {attempt})")
                    else:
                        self.log(f"[{username}] 경고: 활성화된 게시 버튼을 찾지 못했습니다. {attempt}번째 시도 실패.")
                        await asyncio.sleep(1)
                            
                    # 작성 창이 닫혔는지 대기 검증 (최대 10초)
                    editor_still_visible = False
                    cancel_btn = page.locator('xpath=//*[(self::div or self::button or self::span or self::a) and (normalize-space()="취소" or normalize-space()="Cancel")]')
                    try:
                        await cancel_btn.first.wait_for(state="hidden", timeout=10000)
                    except Exception:
                        try:
                            if await cancel_btn.first.is_visible():
                                editor_still_visible = True
                        except Exception:
                            editor_still_visible = False
                            
                    if not editor_still_visible:
                        posted = True
                        break
                    else:
                        self.log(f"[{username}] 경고: 게시 버튼을 클릭했으나 작성 창이 여전히 열려 있습니다. {attempt}번째 재시도 중...")
                        await asyncio.sleep(0.5)
                        
                if not posted:
                    self.log(f"[{username}] 오류: 게시 버튼 클릭 시도 후에도 작성 창이 닫히지 않았습니다.")
                    await context.close()
                    await browser.close()
                    return False
                    
                # 최종 안전 확인
                editor_still_visible = False
                for sel in editor_selectors:
                    try:
                        if await page.locator(sel).first.is_visible():
                            editor_still_visible = True
                            break
                    except Exception:
                        pass
                        
                if editor_still_visible:
                    screenshot_path = os.path.join(self.session_dir, f"error_post_{username}.png")
                    try:
                        await page.screenshot(path=screenshot_path)
                        self.log(f"[{username}] 오류: 작성 모달이 닫히지 않아 실패 처리됨. 스크린샷 저장됨: {screenshot_path}")
                    except Exception:
                        pass
                    await context.close()
                    await browser.close()
                    return False
                    
                try:
                    wait_secs = max(1, int(publish_delay))
                except (TypeError, ValueError):
                    wait_secs = 5
                self.log(f"[{username}] 스레드 본문 및 댓글 일괄 발행 성공! 네트워크 요청 완료를 위해 {wait_secs}초 대기합니다.")
                await asyncio.sleep(wait_secs)
                await context.close()
                await browser.close()
                return True
            except PlaywrightTimeoutError:
                self.log(f"[{username}] 오류: 스레드 페이지 응답 속도 지연 초과.")
            except Exception as e:
                self.log(f"[{username}] 오류: 상세 에러: {e}")
                
            try:
                await context.close()
            except Exception:
                pass
            try:
                await browser.close()
            except Exception:
                pass
            return False

class ThreadsUploader:
    def __init__(self, user_data_dir, work_dir, username, log_callback=None):
        self.user_data_dir = os.path.abspath(user_data_dir)
        self.work_dir = os.path.abspath(work_dir)
        self.username = username
        self.log_callback = log_callback
        self._stop_flag = False
        
        # 계정 ID별 안전한 폴더명 가공 및 서브디렉토리 지정
        safe_username = safe_session_name(username) if username else "default"
        # We pass this subfolder to ThreadsProUploader
        self.session_subfolder = os.path.join(self.user_data_dir, f"threads_session_{safe_username}")
        os.makedirs(self.session_subfolder, exist_ok=True)
        
        self.pro_uploader = ThreadsProUploader(
            session_dir=self.session_subfolder,
            log_callback=self.log_callback
        )

    def log(self, message):
        logger.info(message)
        if self.log_callback:
            self.log_callback(message)

    def stop(self):
        self._stop_flag = True
        self.log("정지 요청이 접수되었습니다. 현재 진행 중인 작업 완료 후 정지합니다.")

    async def open_login_session(self):
        self.log("로그인 세션 브라우저를 실행합니다...")
        await self.pro_uploader.run_manual_login(self.username)

    def get_upload_folders(self):
        """작업 디렉토리 내에서 처리할 업로드 폴더 목록을 정렬하여 반환"""
        if not os.path.exists(self.work_dir):
            self.log(f"오류: 작업 디렉토리가 존재하지 않습니다: {self.work_dir}")
            return []

        folders = []
        for name in os.listdir(self.work_dir):
            full_path = os.path.join(self.work_dir, name)
            if not os.path.isdir(full_path):
                continue
            
            # '[완료]'가 붙어있지 않고, 숫자로 시작하는 폴더 탐색
            if not name.startswith("[완료]") and re.match(r"^\d+", name):
                folders.append((name, full_path))

        # 폴더명 맨 앞의 숫자를 기준으로 정렬 (예: 1_일본양말 -> 1, 10_코 미백 -> 10)
        def get_folder_num(item):
            match = re.match(r"^(\d+)", item[0])
            return int(match.group(1)) if match else 999999

        folders.sort(key=get_folder_num)
        return folders

    def parse_folder_contents(self, folder_path):
        """폴더 내부의 이미지/동영상 파일 목록과 본문 텍스트를 파싱"""
        media_files = []
        post_content = ""
        
        # 허용할 미디어 확장자
        media_extensions = ('.jpg', '.jpeg', '.png', '.webp', '.mp4', '.mov')
        
        # 파일 목록 탐색
        files = sorted(os.listdir(folder_path))
        
        for file in files:
            file_path = os.path.join(folder_path, file)
            if os.path.isdir(file_path):
                continue
                
            ext = os.path.splitext(file.lower())[1]
            
            # 텍스트 파일 (.txt)
            if ext == '.txt':
                try:
                    with open(file_path, 'r', encoding='utf-8') as f:
                        post_content = f.read().strip()
                except Exception as e:
                    self.log(f"텍스트 파일 읽기 오류 ({file}): {e}")
            
            # 미디어 파일
            elif ext in media_extensions:
                media_files.append(file_path)

        # 본문 내용이 없을 경우 폴더명에서 숫자를 뺀 이름을 기본 내용으로 설정
        if not post_content:
            folder_name = os.path.basename(folder_path)
            clean_name = re.sub(r"^\d+_", "", folder_name)
            post_content = clean_name
            self.log(f"안내: {folder_name} 폴더 내 텍스트 파일(.txt)이 없어 폴더명({clean_name})을 본문으로 사용합니다.")

        # 숫자 순서대로 정렬하기 위해 미디어 파일 정렬 (파일명 기준 정렬)
        # 예: 1.jpg, 2.mp4, 3.jpg ...
        def get_file_num(path):
            name = os.path.basename(path)
            match = re.search(r"^(\d+)", name)
            return int(match.group(1)) if match else 999999
            
        media_files.sort(key=get_file_num)

        return post_content, media_files

    def load_excel_data(self, excel_path):
        """엑셀 또는 CSV 파일을 로드하여 Pandas DataFrame으로 반환하고 열 매핑 수행"""
        if not os.path.exists(excel_path):
            raise FileNotFoundError(f"엑셀 파일이 존재하지 않습니다: {excel_path}")
            
        ext = os.path.splitext(excel_path.lower())[1]
        if ext in ('.xlsx', '.xls'):
            df = pd.read_excel(excel_path, keep_default_na=False)
        elif ext == '.csv':
            # 따옴표 내부의 줄바꿈이 행 분리로 이어지지 않도록 파싱 로직 정밀 적용
            df = pd.read_csv(excel_path, keep_default_na=False, encoding='utf-8-sig', lineterminator=None, quotechar='"')
        else:
            raise ValueError("지원하지 않는 파일 형식입니다. (.xlsx, .xls, .csv 중 하나를 선택하세요)")
            
        # 컬럼 매핑 분석
        folder_col = None
        text_col = None
        comment_col = None
        
        folder_candidates = ['폴더명', '폴더', 'folder', 'foldername', 'dir', 'directory', '번호']
        text_candidates = ['본문', '텍스트', 'text', 'content', '글', '내용', '상세설명']
        comment_candidates = ['댓글', '첫댓글', 'comment', 'ad', '광고']
        
        for col in df.columns:
            col_str = str(col).strip().lower()
            if col_str in folder_candidates and folder_col is None:
                folder_col = col
            elif col_str in text_candidates and text_col is None:
                text_col = col
            elif col_str in comment_candidates and comment_col is None:
                comment_col = col
                
        # 매핑 실패 시 대체 규칙 적용
        if folder_col is None or text_col is None:
            if len(df.columns) >= 2:
                folder_col = df.columns[0]
                text_col = df.columns[1]
                self.log(f"안내: 열 이름을 자동으로 찾지 못해 첫 번째 열({folder_col})을 폴더명으로, 두 번째 열({text_col})을 본문으로 지정합니다.")
            else:
                raise ValueError("엑셀 파일에 열이 부족합니다. 최소 2개의 열이 있어야 합니다.")
                
        return df, folder_col, text_col, comment_col

    async def start_upload_process(self, excel_path, delay_minutes, is_headless=True):
        """전체 자동화 업로드 루프 시작"""
        self._stop_flag = False
        self.log("=" * 40)
        self.log("스레드 자동 업로드 프로세스를 시작합니다. (GUI/Excel 모드)")
        self.log(f"딜레이 설정: {delay_minutes}분")
        self.log(f"작업 디렉토리: {self.work_dir}")
        self.log(f"브라우저 모드: {'화면 숨김(Headless)' if is_headless else '화면 표시(Headful)'}")
        self.log("=" * 40)

        # 1. 엑셀 데이터 로드
        try:
            df, folder_col, text_col, comment_col = self.load_excel_data(excel_path)
            self.log(f"엑셀 데이터가 성공적으로 로드되었습니다. (총 {len(df)}개 행)")
        except Exception as e:
            self.log(f"오류: 엑셀 파일 로드 중 실패: {e}")
            return

        # 2. 업로드할 폴더 목록 획득
        upload_folders = self.get_upload_folders()
        if not upload_folders:
            self.log("안내: 업로드할 대기 폴더가 없습니다. 작업을 종료합니다.")
            return

        self.log(f"발견된 로컬 대기 작업 폴더: {len(upload_folders)}개")
        
        # config.json 로드하여 공통 설정 및 API 키 획득
        config_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")
        openai_key = ""
        gemini_key = ""
        system_prompt = ""
        publish_delay = 10
        
        if os.path.exists(config_path):
            try:
                with open(config_path, "r", encoding="utf-8") as f:
                    config = json.load(f)
                    openai_key = config.get("openai_api_key", "")
                    gemini_key = config.get("gemini_api_key", "")
                    system_prompt = config.get("system_prompt", "")
                    publish_delay = config.get("publish_delay", 10)
            except Exception:
                pass

        # 엑셀의 각 행을 순회하면서 폴더 매칭 및 업로드 수행
        uploaded_count = 0
        
        for idx, row in df.iterrows():
            if self._stop_flag:
                self.log("정지 플래그가 활성화되어 작업을 중단합니다.")
                break
                
            folder_val = str(row[folder_col]).strip()
            # 비었거나 숫자가 아니면 패스
            if not folder_val:
                continue
                
            # 폴더명 매칭 시도
            # ex) folder_val = "1" -> "1_일본양말"
            matched_folder_path = None
            matched_folder_name = None
            
            for f_name, f_path in upload_folders:
                # 정확히 같거나, 숫자로 시작하며 언더스코어 등으로 구분되는 경우
                if f_name == folder_val or f_name.startswith(f"{folder_val}_") or re.match(rf"^{folder_val}\D", f_name):
                    matched_folder_path = f_path
                    matched_folder_name = f_name
                    break
                    
            if not matched_folder_path:
                # fallback: 그냥 숫자가 정확히 일치하는지 다시 확인
                for f_name, f_path in upload_folders:
                    prefix_match = re.match(r"^(\d+)", f_name)
                    if prefix_match and prefix_match.group(1) == folder_val:
                        matched_folder_path = f_path
                        matched_folder_name = f_name
                        break
                        
            if not matched_folder_path:
                self.log(f"안내: 엑셀 행 {idx+1} (폴더 ID: {folder_val})에 매칭되는 로컬 대기 폴더를 찾지 못했습니다. 건너뜁니다.")
                continue

            self.log(f"\n[작업 시작] (매칭 폴더: {matched_folder_name})")
            
            # 폴더 콘텐츠 파싱 (텍스트/이미지들)
            folder_content, media_files = self.parse_folder_contents(matched_folder_path)
            
            # 본문 텍스트: 엑셀 본문 컬럼 우선, 없으면 폴더 내 텍스트 파일 사용
            row_content = str(row[text_col]).strip() if pd.notna(row[text_col]) else ""
            post_content = row_content if row_content else folder_content
            
            # 댓글 텍스트: 엑셀 댓글 컬럼
            comment_text = ""
            if comment_col and pd.notna(row[comment_col]):
                comment_text = str(row[comment_col]).strip()

            # AI rewriting 적용 설정 확인
            ai_option = "OFF"
            if "ai" in row and pd.notna(row["ai"]):
                ai_option = str(row["ai"]).strip()
            elif openai_key or gemini_key:
                pass
                
            api_key = openai_key if ai_option == "GPT" else gemini_key
            final_content = rewrite_content(post_content, ai_option, api_key, system_prompt)

            self.log(f" - 최종 본문 글자수: {len(final_content)}자")
            self.log(f" - 첨부 미디어 개수: {len(media_files)}개")
            if comment_text:
                self.log(f" - 첫 댓글 설정됨 (글자수: {len(comment_text)}자)")

            # ThreadsProUploader의 post_to_threads 메소드를 호출하여 업로드 실행!
            success = await self.pro_uploader.post_to_threads(
                username=self.username,
                headless=is_headless,
                content=final_content,
                media_paths=media_files,
                comment_text=comment_text,
                publish_delay=publish_delay
            )

            if success:
                # 업로드 성공 시 폴더명 변경 (접두사 [완료] 추가)
                new_folder_name = f"[완료] {matched_folder_name}"
                new_folder_path = os.path.join(self.work_dir, new_folder_name)
                try:
                    os.rename(matched_folder_path, new_folder_path)
                    self.log(f" - 폴더명 변경 완료: {matched_folder_name} -> {new_folder_name}")
                except Exception as e:
                    self.log(f" - 폴더명 변경 실패: {e}")
                uploaded_count += 1
            else:
                self.log(f" - 실패: '{matched_folder_name}' 폴더 업로드에 실패했습니다. 다음 주기에 재시도합니다.")
                
            # 마지막 작업이 아니라면 대기 실행
            if idx < len(df) - 1 and not self._stop_flag:
                self.log(f"{delay_minutes}분 대기 후 다음 포스팅을 진행합니다...")
                total_wait_seconds = int(delay_minutes * 60)
                waited = 0
                while waited < total_wait_seconds:
                    if self._stop_flag:
                        break
                    await asyncio.sleep(10)
                    waited += 10

        self.log(f"모든 작업이 종료되었습니다. (총 {uploaded_count}개 완료)")
