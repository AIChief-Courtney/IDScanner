# Web-Scrapping Playwriter Demo
Web Scrapping Based Demo

### Invoice OCR (CardScanner)

The Gradio interface includes an Invoice OCR tab alongside Deepfake Detection.
Invoices are uploaded to https://www.cardscanner.co/invoice-ocr using Playwright's
normal browser workflow. Results contain structured invoice JSON and the site's
download URL when provided. Supported inputs: JPG, JPEG, PNG, BMP, GIF, WebP, PDF
(up to 10 MB).

Windows setup from the project directory:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r gradio/requirements.txt
$env:PLAYWRIGHT_BROWSERS_PATH = "$PWD\.playwright"
.\.venv\Scripts\python.exe -m playwright install chromium
cd gradio
$env:LICENSE_KEY = "https://bitmind.ai/detect" # Deepfake tab only
..\.venv\Scripts\python.exe app.py
```

In a second terminal, start the interface from `gradio`:

```powershell
..\.venv\Scripts\python.exe demo.py
```

Open http://localhost:7860. OCR starts automatically when an invoice is uploaded.
The confirmation card appears in the center of the viewport over a dimmed backdrop. It shows a loading animation for five seconds, then a checkbox.
After the user clicks it, loading runs for another five seconds, then the card
disappears and the progress bar starts at 0%. OCR continues through every phase.
The compact
checkbox card uses a familiar verification layout and is clearly labeled
**Invoice OCR / Local confirmation**; it is not Cloudflare or a CAPTCHA service.
New uploads reset the timed sequence. These animations are local presentation
states and are not evidence of a CAPTCHA security check.

A percentage bar estimates the remaining processing time after the timed
confirmation sequence. It uses a rough 60-second processing budget, subtracting
time already spent processing in the background. It stops at 95% if processing
has not completed, and says when the estimate has been exceeded. Confirmation and processing run in parallel, so
their durations are displayed separately alongside total elapsed time.

Successful results stay in server-side session jobs until the checkbox is clicked
and its second five-second animation has finished. If OCR finishes first, the
completed result remains hidden; after confirmation the bar briefly shows 0%
then completes at 100%, without repeating OCR. Results expire after 30 minutes;
failed jobs support retry.

The app opens CardScanner as a guest, uploads the file, clicks Convert when ready,
and displays the returned invoice data as a table and JSON, with its download link.
No sign-in or account connection is required by this app. Verification is attempted
automatically. **Show CardScanner browser while processing** controls visibility.
The browser is brought to the front and the interface shows live progress for
opening, loading, uploading, waiting for Convert, and reading the result.
The page starts processing once its upload code is ready instead of waiting for
ads and analytics to finish loading. The optional API field `stream=true` returns
newline-delimited JSON progress events followed by a final result event.
When Cloudflare verification blocks Convert, the browser scrolls to the checkbox,
waits for its visible loaded frame, attempts a click automatically, and waits up
to 60 seconds for acceptance. One retry is allowed after 12 seconds if it remains
pending; a not-yet-ready widget does not consume an attempt. Gradio retains a timestamped
activity log and refreshes the browser snapshot every five seconds during this
wait. There is no manual-click step in the interface. Rejection and usage-limit
errors stop extraction instead of returning fabricated invoice data.

Camoufox is also available as a browser engine, using its Playwright-compatible
async interface and `humanize=True`. Install its browser after Python dependencies:

```powershell
.\.venv\Scripts\python.exe -m camoufox fetch
```

Select **camoufox** in the interface. Automatic verification performs at most two
clicks after the widget is ready, using the loaded frame's position. It does
not inject verification tokens or remove disabled flags. The app waits for the
real Convert button and OCR response. Cloudflare may still reject the attempt
and stop the workflow; this is not a guaranteed bypass. Browser and
model downloads require Internet access. Package versions pin Playwright to
1.62.0 for Camoufox 0.5.9 compatibility.
The Windows launcher skips Camoufox's failing auxiliary GPU probe and uses a
writable project profile. Selecting Camoufox always uses Camoufox; startup
failure does not switch to Chromium. Run the backend from a normal PowerShell
terminal (`cd gradio; ..\.venv\Scripts\python.exe app.py`) rather than a
restricted automation sandbox, which can block Firefox tab subprocesses.
Camoufox launching and page loading have been verified outside that restriction.
The scraper waits for the upload input instead of the page-private `handlefiles`
function, which is inaccessible from Camoufox's isolated evaluation world.

The scraper does not infer eligibility from the page's internal credits variable.
It attempts the actual upload and reports any visible upstream error. A live
Camoufox test on November 12, 2026 uploaded the sample invoice, passed verification,
converted it, and returned invoice TEST-1001 with total 55 and a downloadable XLSX.
After correcting the widget-readiness race and adding a bounded retry, the user's
PDF also passed verification automatically on the second click, converted, and
returned structured invoice JSON plus a downloaded XLSX on November 12, 2026.
Other attempts hit CardScanner's **Daily Limit Reached** dialog (2 free daily
conversions); quota errors are still reported. Past success does not guarantee
future verification acceptance.

The Flask API accepts `POST /invoice_ocr` with multipart `file`, required
`processing_requested=true` (or the legacy `user_confirmed=true`), and optional
`show_browser=false` for headless operation. Responses use `resultCode` (`Ok` or
`Error`) and `result`. A visible daily-limit dialog returns HTTP 429 with
`error_code=usage_limit`.
An absent processing request returns HTTP 428 (`processing_request_required`).
This flag expresses intent to start OCR, not proof of humanity. The separate
local confirmation governs result display in the Gradio session.
Temporary local invoice uploads are removed after processing.

### Optional server-side proxy

Invoice browser traffic can use a proxy configured in the private, ignored file
`.local/invoice-proxy.json`. Authentication is never returned to Gradio:

```json
{
  "server": "http://dcp.evomi.com:2000",
  "username": "YOUR_PROXY_USERNAME",
  "password": "YOUR_PROXY_PASSWORD"
}
```

Without a session parameter, Evomi controls rotation using its default behavior.
Two independent requests to its IP-check endpoint returned different exit IPs
after removing the session setting. Browser connections may be reused, so the app
does not guarantee a unique IP for every HTTP subrequest. IP changes can interrupt
verification and conversion. The optional `evomi_locked_session` setting is still
supported but is not enabled in the current configuration.

`INVOICE_PROXY_URL` overrides the file and accepts standard authenticated URLs or
Evomi's `http://host:port:username:password` format. An explicitly empty value
disables proxy use. Keep any desired provider session options in the password when
using this environment override. The local file is read afresh for each invoice.
The daily-limit check still stops processing when CardScanner reports a limit.

Standalone browser script:

```powershell
.\.venv\Scripts\python.exe gradio/invoice_ocr.py path/to/invoice.pdf --show-browser
```

Run local browser and API tests from `gradio`:

```powershell
..\.venv\Scripts\python.exe -m unittest test_invoice_ocr -v
```

### How to obsculate python code
```bash
pip install pyarmor
```
```bash
pyarmor gen app.py
```

