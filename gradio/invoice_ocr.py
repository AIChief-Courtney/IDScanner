"""Extract invoice data through CardScanner's normal browser upload workflow."""

import argparse
import asyncio
import json
import os
import base64
import tempfile
from pathlib import Path
from contextlib import asynccontextmanager
from proxy_settings import load_proxy_settings

from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeoutError, Error as PlaywrightError


INVOICE_URL = "https://www.cardscanner.co/invoice-ocr"
ALLOWED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".bmp", ".gif", ".webp", ".pdf"}
MAX_FILE_SIZE = 10 * 1024 * 1024

# Keep browser installation inside the project when available (Windows/Linux).
LOCAL_BROWSERS = Path(__file__).resolve().parent.parent / ".playwright"
if LOCAL_BROWSERS.is_dir():
    os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", str(LOCAL_BROWSERS))


class InvoiceOCRError(Exception):
    """An actionable upload, verification, or conversion error."""

    def __init__(self, message, code="upstream_error"):
        super().__init__(message)
        self.code = code


@asynccontextmanager
async def launch_invoice_browser(playwright, *, engine, headless, progress=None):
    if engine not in {'camoufox', 'chromium'}:
        raise InvoiceOCRError("Choose Camoufox or Chromium.", "browser_setup")
    try:
        proxy = load_proxy_settings()
    except (ValueError, KeyError, OSError) as exc:
        raise InvoiceOCRError('Proxy configuration is invalid. Check the private server settings.', 'proxy_setup') from exc
    if proxy and progress:
        progress('Using the configured server-side proxy. Authentication is not shown in the interface.')
    proxy_options = {'proxy': proxy} if proxy else {}
    if engine == "camoufox":
        try:
            from camoufox.async_api import AsyncCamoufox
        except ImportError as exc:
            raise InvoiceOCRError("Install invoice dependencies and run python -m camoufox fetch first.", "browser_setup") from exc
        profiles = Path(__file__).resolve().parent.parent / '.local' / 'browser-profiles'
        profiles.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=profiles, prefix='invoice-') as profile:
            manager = AsyncCamoufox(
                headless=headless, humanize=True, os="windows", no_viewport=True,
                # Avoid the auxiliary GPU-probe browser which crashes on this host.
                canvas_noise=True,
                persistent_context=True, user_data_dir=profile, timeout=30000,
                **proxy_options,
            )
            try:
                context = await manager.__aenter__()
            except PlaywrightError as exc:
                if 'SpawnTarget' in str(exc):
                    raise InvoiceOCRError(
                        "Windows blocked Camoufox tab subprocesses in the restricted execution environment. "
                        "Start the backend from a normal PowerShell terminal as described in README.md. "
                        "No other browser was used.", "browser_startup"
                    ) from exc
                raise InvoiceOCRError(
                    "Camoufox could not start: " + str(exc).splitlines()[0] +
                    ". No other browser was used.", "browser_startup"
                ) from exc
            else:
                try:
                    yield context
                finally:
                    await manager.__aexit__(None, None, None)
                return
    browser = await playwright.chromium.launch(headless=headless, **proxy_options)
    try:
        context = await browser.new_context(viewport={"width": 1280, "height": 900})
        yield context
    finally:
        await browser.close()


async def attempt_verification(page):
    """Click only after the verification frame has loaded and become visible."""
    widget = page.locator('.cf-turnstile').first
    if not await widget.is_visible():
        return False
    await widget.scroll_into_view_if_needed()
    # Accessible widgets can expose the checkbox directly (also used by local
    # workflow tests). Turnstile normally puts it in a closed shadow iframe.
    checkbox = widget.locator('input[type="checkbox"]').first
    if await checkbox.is_visible() and await checkbox.is_enabled():
        await checkbox.click(timeout=2000)
        return True
    for frame in page.frames:
        if 'challenges.cloudflare.com' not in frame.url:
            continue
        try:
            if await frame.evaluate('document.readyState') != 'complete':
                continue
            host = await frame.frame_element()
            if not await host.is_visible():
                continue
            await host.scroll_into_view_if_needed()
            # Frame load precedes the widget's final paint/interaction handlers.
            await asyncio.sleep(1)
            box = await host.bounding_box()
            if not box or box['width'] < 100 or box['height'] < 30:
                continue
            token = page.locator('[name="cf-turnstile-response"]').first
            if await token.count() and await token.input_value():
                return False
            await page.mouse.click(box['x'] + 22, box['y'] + box['height'] / 2)
            return True
        except PlaywrightError:
            # Cloudflare can replace a frame while it is being inspected.
            continue
    return False


async def site_error(page):
    # Only inspect visible notices: the page contains hidden quota-dialog templates.
    text = await page.locator(".modal.show, .toast:visible, .jq-toast-single:visible").all_inner_texts()
    for notice in text:
        lowered = notice.lower()
        if "daily limit reached" in lowered or "free daily conversions" in lowered:
            raise InvoiceOCRError(
                "CardScanner displayed: Daily Limit Reached. You've reached your 2 free daily conversions. "
                "The guest conversion cannot continue in this browser session right now.", "usage_limit"
            )
        if "upload failed" in lowered or "corrupt" in lowered or "password-protected" in lowered:
            raise InvoiceOCRError("CardScanner: " + notice[:500], "upload_rejected")


async def wait_for_response(page, responses, endpoint, timeout, progress=None):
    started = asyncio.get_running_loop().time()
    next_update = started + 5
    deadline = asyncio.get_running_loop().time() + timeout / 1000
    while asyncio.get_running_loop().time() < deadline:
        if page.is_closed():
            raise InvoiceOCRError("The CardScanner browser was closed before conversion finished.")
        await site_error(page)
        now = asyncio.get_running_loop().time()
        if progress and now >= next_update:
            progress(f"Waiting for CardScanner {'conversion' if endpoint == '/ocrtools' else 'upload'} response: {int(now - started)}s elapsed.")
            next_update = now + 5
        try:
            return await asyncio.wait_for(responses[endpoint].get(), timeout=0.25)
        except asyncio.TimeoutError:
            continue
    raise InvoiceOCRError(
        "CardScanner did not complete the " + endpoint.strip('/') +
        " step. Check the opened browser for verification or an upload error.", "timeout"
    )


async def _extract_invoice(file_path, *, headless=False, timeout=180000, progress=None, verification_timeout=60000, engine="camoufox", auto_verify=True):
    stage = 'browser startup'
    def report(message):
        nonlocal stage
        stage = message
        if progress:
            progress(message)
    async def snapshot(page):
        if progress:
            try:
                picture = await page.screenshot(type="jpeg", quality=65, timeout=5000)
                progress({"message": "Browser view updated.", "image": "data:image/jpeg;base64," + base64.b64encode(picture).decode('ascii')})
            except Exception:
                pass  # A preview failure must not interrupt the OCR request.
    path = Path(file_path).resolve()
    if not path.is_file():
        raise InvoiceOCRError("Invoice file not found.")
    if path.suffix.lower() not in ALLOWED_EXTENSIONS:
        raise InvoiceOCRError("Upload a JPG, PNG, BMP, GIF, WebP, or PDF invoice.")
    if not 0 < path.stat().st_size <= MAX_FILE_SIZE:
        raise InvoiceOCRError("The invoice must be nonempty and no larger than 10 MB.")

    async with async_playwright() as p:
        report(f"Opening CardScanner with {engine}...")
        async with launch_invoice_browser(p, engine=engine, headless=headless, progress=report) as context:
            page = None
            try:
                # Firefox persistent contexts start with a page already open.
                # Reuse it rather than creating a second initial window.
                page = context.pages[0] if engine == 'camoufox' and context.pages else await context.new_page()
                def failed(request):
                    if 'challenges.cloudflare.com' in request.url:
                        failure = request.failure or 'unknown network error'
                        # Turnstile replaces frames during normal operation; an
                        # aborted old frame is not evidence of a network block.
                        if 'ERR_ABORTED' not in failure:
                            report(f"Verification request failed: {failure}. Check the Cloudflare widget in the browser.")
                page.on('requestfailed', failed)
                page.set_default_timeout(timeout)
                if not headless:
                    await page.bring_to_front()
                report("Loading the invoice upload page...")
                # Advertising and analytics can delay the full load event substantially.
                await page.goto(INVOICE_URL, wait_until="domcontentloaded", timeout=min(timeout, 45000))
                # Camoufox evaluates in an isolated world: page-private functions
                # are intentionally invisible there. DOMContentLoaded has already
                # run the synchronous page scripts; wait for the actual input.
                await page.locator('#clickupload').wait_for(state='attached', timeout=min(timeout, 30000))
                # Capture normal page requests; do not infer eligibility from internal credits variables.
                responses = {"/uploadImage": asyncio.Queue(), "/ocrtools": asyncio.Queue()}
                def capture(response):
                    endpoint = "/" + response.url.split("?")[0].rstrip("/").rsplit("/", 1)[-1]
                    if response.request.method == "POST" and endpoint in responses:
                        responses[endpoint].put_nowait(response)
                page.on("response", capture)
                report("Uploading your invoice to CardScanner...")
                await page.locator("#clickupload").set_input_files(str(path))
                upload_response = await wait_for_response(page, responses, "/uploadImage", min(timeout, 45000), report)
                if not upload_response.ok:
                    raise InvoiceOCRError(f"CardScanner upload failed (HTTP {upload_response.status}).")
                upload_data = await upload_response.json()
                if upload_data.get("error"):
                    raise InvoiceOCRError(f"CardScanner rejected the upload: {upload_data.get('message') or upload_data['error']}")

                report(f"Upload accepted by CardScanner (HTTP {upload_response.status}).")
                widget = page.locator('.cf-turnstile').first
                if await widget.is_visible():
                    await widget.scroll_into_view_if_needed()
                    if not headless:
                        await page.bring_to_front()
                await snapshot(page)
                report("Checking the uploaded file and Convert button...")
                started = asyncio.get_running_loop().time()
                deadline = started + verification_timeout / 1000
                next_update = started
                verification_announced = False
                verification_attempts = 0
                next_attempt_at = started
                while responses["/ocrtools"].empty():
                    if page.is_closed():
                        raise InvoiceOCRError("The CardScanner browser was closed before conversion finished.")
                    await site_error(page)
                    button = page.locator(".convert_button")
                    ready = await button.evaluate(
                        "e => !e.disabled && !e.classList.contains('disabled')"
                    )
                    if ready:
                        report("Convert is enabled. Verification and upload checks passed.")
                        report("Clicking Convert. CardScanner is processing your invoice...")
                        await button.click()
                        break
                    now = asyncio.get_running_loop().time()
                    if now >= next_update:
                        state = await page.evaluate("""() => ({
                            uploading: document.querySelectorAll('.uploaded_item.is_uploading').length,
                            uploaded: document.querySelectorAll('.uploaded_item:not(.is_uploading)').length,
                            verification: !!document.querySelector('.cf-turnstile') &&
                              !document.querySelector('[name="cf-turnstile-response"]')?.value
                        })""")
                        if state['verification']:
                            if auto_verify and verification_attempts < 2 and now >= next_attempt_at:
                                report("Checking whether the Cloudflare verification frame is ready...")
                                clicked = await attempt_verification(page)
                                if clicked:
                                    verification_attempts += 1
                                    report(f"Verification click {verification_attempts}/2 delivered to the loaded widget. Waiting for acceptance...")
                                    next_attempt_at = asyncio.get_running_loop().time() + 12
                                else:
                                    report("Verification widget is not ready to click yet. No attempt was counted.")
                                    next_attempt_at = asyncio.get_running_loop().time() + 2
                                await snapshot(page)
                                # Read a fresh button/token state after the click.
                                next_update = asyncio.get_running_loop().time() + 1
                                continue
                            if headless and not auto_verify:
                                raise InvoiceOCRError("CardScanner requires the Verify you are human checkbox. Enable Show CardScanner browser and complete it in that window.", "verification_required")
                            if not verification_announced:
                                if auto_verify:
                                    report("Automatic verification is pending. No manual click is requested; waiting for Cloudflare to enable Convert.")
                                else:
                                    report("Manual diagnostic mode: complete verification in the browser.")
                                verification_announced = True
                            report(f"Waiting for verification: {int(now - started)}s elapsed, {max(0, int(deadline - now))}s remaining. Uploaded files: {state['uploaded']}; uploading: {state['uploading']}; Convert: disabled.")
                        else:
                            report(f"Waiting for CardScanner: {int(now - started)}s elapsed. Uploaded files: {state['uploaded']}; uploading: {state['uploading']}; Convert: disabled.")
                        await snapshot(page)
                        next_update = now + (1 if auto_verify and verification_attempts < 2 else 5)
                    if now >= deadline:
                        raise InvoiceOCRError(
                            f"Cloudflare verification did not complete within {verification_timeout / 1000:g} seconds. CardScanner kept Convert disabled; no invoice data was returned.",
                            "verification_required"
                        )
                    await asyncio.sleep(0.25)
                response = await wait_for_response(page, responses, "/ocrtools", min(timeout, 120000), report)
                if not response.ok:
                    raise InvoiceOCRError(f"CardScanner conversion failed (HTTP {response.status}).")
                data = await response.json()
                if data.get("error"):
                    raise InvoiceOCRError(f"CardScanner conversion error: {data.get('message') or data['error']}")
                if not isinstance(data.get("json"), (dict, list)) or not data["json"]:
                    raise InvoiceOCRError("CardScanner returned no structured invoice data.")
                report("Conversion complete. Reading the extracted invoice data...")
                return {
                    "data": data["json"],
                    "filename": data.get("filename"),
                    "download_url": data.get("fileUrl"),
                }
            except PlaywrightTimeoutError as exc:
                if page is not None:
                    await snapshot(page)
                raise InvoiceOCRError(f"CardScanner timed out during: {stage}. Check the browser preview for the last page state.", "timeout") from exc

async def extract_invoice(file_path, **options):
    try:
        return await _extract_invoice(file_path, **options)
    except PlaywrightError as exc:
        detail = str(exc).splitlines()[0]
        raise InvoiceOCRError(
            f"{options.get('engine', 'camoufox')} browser failed: {detail}. "
            "See the activity log for the selected browser's startup details.",
            "browser_error",
        ) from exc


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("file", help="Invoice image or PDF")
    parser.add_argument("--show-browser", action="store_true", help="Show browser activity")
    parser.add_argument("--engine", choices=["chromium", "camoufox"], default="camoufox")
    parser.add_argument("--auto-verify", action=argparse.BooleanOptionalAction, default=True, help="Attempt verification automatically (enabled by default)")
    args = parser.parse_args()
    try:
        print(json.dumps(asyncio.run(extract_invoice(args.file, headless=not args.show_browser, engine=args.engine, auto_verify=args.auto_verify)), indent=2))
    except InvoiceOCRError as exc:
        parser.exit(1, f"{exc}\n")
