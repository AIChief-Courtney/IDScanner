import asyncio
from playwright.async_api import async_playwright
import os
import re

async def upscale_image(image_path):
    async with async_playwright() as p:
        # Launch browser in HEADLESS mode
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            accept_downloads=True,
            viewport={'width': 1200, 'height': 800}
        )
        page = await context.new_page()
        page.set_default_timeout(180000)

        try:
            # 1. Navigate to the upscaler website
            print("✅ Image Upscaler Started")
            await page.goto('https://photiu.ai/image-upscaler', wait_until='networkidle')
            
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
            
            # 3. Find and click the upload button
            # print("� Looking for upload button...")
            upload_button = await page.query_selector('#uploadPhoto-btn')
            
            if not upload_button:
                print("❌ No upload button found")
                await page.screenshot(path='debug_no_upload_button.png')
                return None
            
            # 4. Find the hidden file input (usually associated with upload buttons)
            # print("� Looking for file input element...")
            file_input = await page.query_selector('input[type="file"]')
            
            if not file_input:
                print("❌ No file input found")
                await page.screenshot(path='debug_no_file_input.png')
                return None
            
            # 5. Upload file
            # print("� Uploading file...")
            absolute_path = os.path.abspath(image_path)
            await file_input.set_input_files(absolute_path)
            # print(f"✅ File set: {absolute_path}")
            
            # 7. Wait for processing to complete - monitor the before/after dimensions
            # print("⚙️ Waiting for processing to complete...")
            # print("� Monitoring dimensions...")
            
            # Wait for dimensions to change from 0x0 to actual dimensions
            await page.wait_for_function("""
                () => {
                    // Find all divs and look for the one with the After dimensions
                    const allDivs = document.querySelectorAll('div');
                    for (const div of allDivs) {
                        const text = div.textContent || '';
                        if (text.includes('After:') && text.includes('px')) {
                            const match = text.match(/After: (\\d+) × (\\d+) px/);
                            if (match && match[1] !== '0' && match[2] !== '0') {
                                return true;
                            }
                        }
                    }
                    return false;
                }
            """, timeout=180000)
            
            print("✅ Processing complete! Dimensions updated.")
            
            # 8. Get the actual dimensions for verification
            dimensions_text = await page.evaluate("""
                () => {
                    // Find all divs and look for the one with the After dimensions
                    const allDivs = document.querySelectorAll('div');
                    for (const div of allDivs) {
                        const text = div.textContent || '';
                        if (text.includes('After:') && text.includes('px')) {
                            return text.trim();
                        }
                    }
                    return null;
                }
            """)
            
            # print(f"� Final dimensions: {dimensions_text}")
            
            # 9. Wait a bit more to ensure everything is ready
            # print("⏳ Finalizing...")
            await asyncio.sleep(1)
            
            # 10. Ensure download button is enabled
            download_button = await page.query_selector('#Download\\ HD\\ free')
            if not download_button:
                print("❌ Download button not found")
                await page.screenshot(path='download_button_missing.png')
                return None
                
            is_disabled = await download_button.get_attribute('disabled')
            if is_disabled:
                print("❌ Download button is disabled")
                await page.screenshot(path='download_disabled.png')
                return None
            
            # print("✅ Download button is enabled")
            
            # 11. Set up download handling
            # print("⬇️ Clicking download button...")
            
            # Use page.expect_download() correctly
            async with page.expect_download() as download_info:
                await download_button.click()
            
            download = await download_info.value
            
            # Create output filename
            suggested_name = download.suggested_filename
            if suggested_name and suggested_name != 'image.png':
                output_name = f"{os.path.splitext(image_path)[0]}_upscaled{os.path.splitext(suggested_name)[1]}"
            else:
                output_name = f"{os.path.splitext(image_path)[0]}_upscaled.png"
            
            # Save the download
            await download.save_as(output_name)
            print(f"✅ Download successful! File saved as: {output_name}")
            
            # Verify file was saved
            if os.path.exists(output_name):
                file_size = os.path.getsize(output_name)
                # print(f"� File size: {file_size} bytes")
                return output_name
            else:
                # print("❌ Downloaded file doesn't exist")
                return None
            
        except Exception as e:
            print(f"❌ Error: {e}")
            await page.screenshot(path='debug_error.png')
            print("Screenshot saved to debug_error.png")
            return None
            
        finally:
            await browser.close()

async def main():
    image_file = "1.jpg"  # Change this to your image path
    
    if not os.path.exists(image_file):
        print(f"❌ Image file not found: {image_file}")
        return
    
    print(f"�️ Starting image upscaling for: {image_file}")
    result_file = await upscale_image(image_file)
    
    if result_file:
        print(f"✅ Success! Output file: {result_file}")
    else:
        print("❌ Image upscaling failed")

if __name__ == "__main__":
    asyncio.run(main())
