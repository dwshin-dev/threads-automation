import asyncio
import os
import sys
from playwright.async_api import async_playwright

async def main():
    session_dir = os.path.abspath("sessions")
    session_file = os.path.join(session_dir, "2.json")
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(storage_state=session_file)
        page = await context.new_page()
        
        await page.goto("https://www.threads.net/", timeout=45000)
        await asyncio.sleep(5)
        
        # 새로운 스레드 모달 열기
        opened = False
        for selector in ['a[href="/write"]', 'svg[aria-label="새로운 스레드"]', 'svg[aria-label="Write"]', 'div[role="button"]:has-text("새로운 스레드")']:
            try:
                btn = page.locator(selector).first
                if await btn.count() > 0:
                    await btn.click()
                    opened = True
                    break
            except Exception:
                continue
                
        if not opened:
            # 단축키 'c' 시도
            try:
                await page.keyboard.press("c")
                await asyncio.sleep(2)
                opened = True
            except Exception:
                pass
                
        if opened:
            print("Opened Write Modal. Dumping buttons inside it...")
            await asyncio.sleep(2)
            
            # '게시' 단추 후보들
            buttons = page.locator('div[role="button"], button')
            b_count = await buttons.count()
            print(f"Found {b_count} buttons total on page.")
            for i in range(b_count):
                btn = buttons.nth(i)
                text = await btn.inner_text()
                if "게시" in text or "Post" in text or "답글" in text:
                    outer_html = await btn.evaluate("el => el.outerHTML")
                    visible = await btn.is_visible()
                    print(f"Button {i}: text='{text}', visible={visible}")
                    print(f"HTML: {outer_html}")
                    print("-----------------------------")
        else:
            print("Error: Could not open write modal!")
            
        await context.close()
        await browser.close()

if __name__ == "__main__":
    asyncio.run(main())
