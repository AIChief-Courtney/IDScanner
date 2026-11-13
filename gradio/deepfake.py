import asyncio
from playwright.async_api import async_playwright
import os
import re

async def deepfake_image(image_path):
    async with async_playwright() as p:
        # Launch browser in HEADLESS mode
        browser = await p.chromium.launch(headless=False)
        context = await browser.new_context(
            accept_downloads=True,
            viewport={'width': 1200, 'height': 800}
        )
        page = await context.new_page()
        page.set_default_timeout(180000)

        try:
            # 1. Navigate to the upscaler website
            print("✅ Deepfake Detection Started")
            await page.goto('https://bitmind.ai/detect', wait_until='networkidle')
            
            # 2. Handle cookie consent banner if it appears
            # print("� Handling cookie consent...")
            try:
                # Try to find and click "Deny" or similar button
                deny_button = await page.wait_for_selector(
                    'button:has-text("Deny"), button:has-text("Reject"), button:has-text("Essential")',
                    timeout=5000
                )
                if deny_button:
                    await deny_button.click()
                    print("✅ Cookie consent handled")
                    await asyncio.sleep(1)
            except:
                print("ℹ️ No cookie banner found or already handled")
            
            # 3. Find the file input (usually associated with upload buttons)
            # print("� Looking for file input element...")
            file_input = await page.query_selector('input[type="file"][accept="image/*"]')
            if not file_input:
                print("❌ No file input found")
                await page.screenshot(path='debug_no_file_input.png')
                return None
            
            # 4. Upload file
            # print("� Uploading file...")
            absolute_path = os.path.abspath(image_path)
            await file_input.set_input_files(absolute_path)
            # print(f"✅ File set: {absolute_path}")
            
            # 5. Find and click the Analyze Image button
            print("� Looking for Analyze Image button...")
            button = page.get_by_role("button", name="Analyze Image")
            if not button:
                print("❌ No Analyze Image found")
                await page.screenshot(path='debug_no_analyze_image_button.png')
                return None
            await button.click()


            # Wait until the result appears
            await page.wait_for_selector("text=confidence", timeout=30000)

            # Find the percentage value just before the "%" span
            # confidence = await page.locator(
            #     "span.text-5xl.font-bold"
            # ).first.text_content()

            # print("\nconfidence: ", confidence)

            # Wait until analysis completes
            await page.wait_for_selector("text=Analysis Complete", timeout=30000)

            result = {}

            # AI status
            status = await page.locator(
                "span.font-display.text-sm.font-medium"
            ).text_content()

            result["status"] = status.strip()

            # Real / Fake
            result["prediction"] = (
                await page.locator("span:text-is('confidence')")
                    .locator("xpath=preceding-sibling::span[2]")
                    .text_content()
            ).strip()

            # Confidence
            confidence_text = (
                await page.locator("span:text-is('confidence')")
                    .locator("xpath=preceding-sibling::span[1]")
                    .text_content()
            )

            result["confidence"] = float(re.search(r"[\d.]+", confidence_text).group())

            # Similarity
            similarity_text = (
                await page.locator("p:text-is('Similarity')")
                    .locator("xpath=following-sibling::p[1]")
                    .text_content()
            )

            result["similarity"] = float(re.search(r"[\d.]+", similarity_text).group())

            # Media Type
            result["media_type"] = (
                await page.locator("p:text-is('Media Type')")
                    .locator("xpath=following-sibling::p[1]")
                    .text_content()
            ).strip()

            print(result)      
            
        except Exception as e:
            print(f"❌ Error: {e}")
            await page.screenshot(path='debug_error.png')
            print("Screenshot saved to debug_error.png")
            return None
            
        finally:
            await browser.close()

async def main():
    image_file = "examples/2.jpg"  # Change this to your image path
    video_file = "test.mp4" #MP4, WebM
    
    if not os.path.exists(image_file):
        print(f"❌ Image file not found: {image_file}")
        return
    
    print(f"�️ Starting deepfake detection for: {image_file}")
    result_file = await deepfake_image(image_file)
    
    if result_file:
        print(f"✅ Success! Output file: {result_file}")
    else:
        print("❌ Deepfake detection failed")

if __name__ == "__main__":
    asyncio.run(main())
