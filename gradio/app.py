import sys
sys.path.append('.')
import asyncio
from playwright.async_api import async_playwright
import os
import re

import uuid
import base64
import json
import numpy as np
import tempfile
import queue
import threading
from pathlib import Path
from invoice_ocr import extract_invoice, InvoiceOCRError, ALLOWED_EXTENSIONS, MAX_FILE_SIZE
from flask import Flask, request, jsonify, Response
from flask_cors import CORS

licenseKeyPath = "license.txt"
license = os.environ.get("LICENSE_KEY")
# license = 'https://bitmind.ai/detect'
if license is None:
    try:
        with open(licenseKeyPath, 'r') as file:
            license = file.read().strip()
    except IOError as exc:
        print("failed to open license.txt: ", exc.errno)
    print("License Key: ", license)

app = Flask(__name__) 
CORS(app)

async def deepfake_image(image_path):
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
            print("✅ Deepfake Detection Started")
            await page.goto(license, wait_until='networkidle')
            
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
            confidence = await page.locator(
                "span.text-5xl.font-bold"
            ).first.text_content()

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

            # print(result)
            return result      
            
        except Exception as e:
            print(f"❌ Error: {e}")
            await page.screenshot(path='debug_error.png')
            print("Screenshot saved to debug_error.png")
            return None
            
        finally:
            await browser.close()

# Helper function to run async functions in sync context
def run_async(coro):
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()

@app.route('/deepfake_image', methods=['POST'])
def process_image():
    file = request.files['image']
    # Save uploaded file temporarily
    unique_filename = str(uuid.uuid4())
    if not os.path.exists('static'):
        os.makedirs('static')
    
    input_path = os.path.join('static', f'{unique_filename}_input.jpg')
    file.save(input_path)
    
    print(f"�️ Starting deepfake detection for: {input_path}")
    
    # Run the async upscale function
    result = run_async(deepfake_image(input_path))
    os.remove(input_path)

    if result is None:
        result = "Failed to process image"
        response = jsonify({"resultCode": "Error", "result": result})

        response.status_code = 201
        response.headers["Content-Type"] = "application/json; charset=utf-8"
        return response
    else:
        response = jsonify({"resultCode": "Ok", "result": result})

        response.status_code = 200
        response.headers["Content-Type"] = "application/json; charset=utf-8"
        return response

async def main():
    image_file = "test.jpg"  # Change this to your image path
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

@app.route('/invoice_ocr', methods=['POST'])
def process_invoice():
    file = request.files.get('file')
    if file is None or not file.filename:
        return jsonify(resultCode="Error", result="Upload an invoice using the 'file' field."), 400
    suffix = Path(file.filename).suffix.lower()
    if suffix not in ALLOWED_EXTENSIONS:
        return jsonify(resultCode="Error", result="Unsupported invoice file format."), 400
    # Read one byte past the limit instead of saving arbitrarily large uploads.
    contents = file.stream.read(MAX_FILE_SIZE + 1)
    if not contents or len(contents) > MAX_FILE_SIZE:
        return jsonify(resultCode="Error", result="Invoice must be nonempty and no larger than 10 MB."), 400
    if not any(request.form.get(key, 'false').lower() == 'true' for key in ('processing_requested', 'user_confirmed')):
        return jsonify(resultCode="Error", error_code="processing_request_required",
                       result="Explicitly request invoice processing before starting the job."), 428
    show_browser = request.form.get('show_browser', 'true').lower() == 'true'
    engine = request.form.get('engine', 'camoufox')
    if engine not in {'camoufox', 'chromium'}:
        return jsonify(resultCode="Error", result="Choose Camoufox or Chromium."), 400
    auto_verify = request.form.get('auto_verify', 'true').lower() == 'true'
    if request.form.get('stream') == 'true':
        events = queue.Queue()
        def worker():
            try:
                with tempfile.TemporaryDirectory(prefix="invoice-ocr-") as folder:
                    path = Path(folder) / ("invoice" + suffix)
                    path.write_bytes(contents)
                    result = run_async(extract_invoice(
                        path, headless=not show_browser, engine=engine, auto_verify=auto_verify,
                        progress=lambda message: events.put(
                            {"type": "progress", **message} if isinstance(message, dict)
                            else {"type": "progress", "message": message}
                        )
                    ))
                events.put({"type": "result", "resultCode": "Ok", "result": result})
            except InvoiceOCRError as exc:
                events.put({"type": "result", "resultCode": "Error", "result": str(exc), "error_code": exc.code})
            except Exception:
                app.logger.exception("Invoice OCR failed")
                events.put({"type": "result", "resultCode": "Error", "result": "Invoice OCR failed. Check the backend log."})
        def generate():
            threading.Thread(target=worker, daemon=True).start()
            while True:
                try:
                    event = events.get(timeout=5)
                except queue.Empty:
                    yield json.dumps({"type": "heartbeat"}) + "\n"
                    continue
                yield json.dumps(event) + "\n"
                if event['type'] == 'result':
                    break
        return Response(generate(), mimetype="application/x-ndjson", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
    try:
        with tempfile.TemporaryDirectory(prefix="invoice-ocr-") as folder:
            path = Path(folder) / ("invoice" + suffix)
            path.write_bytes(contents)
            result = run_async(extract_invoice(
                path, headless=not show_browser, engine=engine, auto_verify=auto_verify
            ))
        return jsonify(resultCode="Ok", result=result)
    except InvoiceOCRError as exc:
        status = 429 if exc.code == "usage_limit" else 502
        return jsonify(resultCode="Error", result=str(exc), error_code=exc.code), status
    except Exception:
        app.logger.exception("Invoice OCR failed")
        return jsonify(resultCode="Error", result="Invoice OCR failed. Check the backend log for details."), 500


if __name__ == "__main__":
    # asyncio.run(main())
    port = int(os.environ.get("PORT", 9000))
    app.run(host='0.0.0.0', port=port)
