import os
import gradio as gr
import requests
import json
import io
import html
import time
import threading
from pathlib import Path
from invoice_ui import progress_for, progress_html, parallel_timing_html, confirmation_warning
from invoice_jobs import create_job, get_job, advance_verification
from urllib.parse import urlparse
from gradio.components import Image
from PIL import Image as PILImage, ImageDraw, ImageFont  # This import may be needed if you're processing images

from PIL import Image

def process_image(image):
    # Convert PIL image to bytes to send in POST request
    img_bytes = io.BytesIO()
    image.save(img_bytes, format="JPEG")
    img_bytes.seek(0)
    
    
    url = "http://127.0.0.1:9000/deepfake_image"
    files = {'image': img_bytes}
    result = requests.post(url=url, files=files)
    if result.ok:
        json_result = result.json()
        if json_result.get("resultCode") == "Error":
            return {"resultCode": "Error", "result": "Failed to process image"}

        status = json_result.get("result").get("status")
        confidence = json_result.get("result").get("confidence")
        prediction = json_result.get("result").get("prediction")
        similarity = json_result.get("result").get("similarity")
        media_type = json_result.get("result").get("media_type")
        if status == "Not AI Generated":
            status_html = f'<span style="color:green; font-weight:bold;">{status}</span>'
            confidence_html = f'<span style="color:green; font-weight:bold;">{confidence} %</span>'
        else:
            status_html = f'<span style="color:red; font-weight:bold;">{status}</span>'
            confidence_html = f'<span style="color:red; font-weight:bold;">{confidence} %</span>'

        html = ("<table>"
                    "<tr>"
                        "<th>Evaluation Field</th>"
                        "<th>Value</th>"
                    "</tr>"
                    "<tr>"
                        "<td>Result</td>"
                        "<td>{status_html}</td>"
                    "</tr>"
                    "<tr>"
                        "<td>Confidence</td>"
                        "<td>{confidence_html}</td>"
                    "</tr>"
                    "<tr>"
                        "<td>Similarity</td>"
                        "<td>{similarity} % matches to known AI images</td>"
                    "</tr>"
                    "<tr>"
                        "<td>Media Type</td>"
                        "<td>{media_type}</td>"
                    "</tr>"
                    "</table>".format(status_html=status_html, confidence_html=confidence_html, similarity=similarity, media_type=media_type))

        if status == "Ok":
            # Update json_result with the modified process_results
            json_result["result"] = process_results
        return html
    else:
        return {"resultCode": "Error", "result": result.text}
    
def invoice_feedback(payload):
    if payload.get("resultCode") == "Ok":
        result = payload.get("result", {})
        def render(value):
            if isinstance(value, dict):
                rows = ''.join('<tr><th>' + html.escape(str(k)) + '</th><td>' + render(v) + '</td></tr>' for k, v in value.items())
                return '<table>' + rows + '</table>'
            if isinstance(value, list):
                return '<ol>' + ''.join('<li>' + render(v) + '</li>' for v in value) + '</ol>'
            return html.escape(str(value)) if value is not None else ''
        preview = render(result.get("data", result))
        link = result.get("download_url")
        if isinstance(link, str) and urlparse(link).scheme in {"http", "https"}:
            preview += '<p><a target="_blank" rel="noopener noreferrer" href="' + html.escape(link, quote=True) + '">Download CardScanner result</a></p>'
        return "**Invoice extracted.**", preview, result
    return "**CardScanner:** " + str(payload.get("result", "Request failed.")), '', None


def invoice_events(file, show_browser, engine):
    if file is None:
        yield invoice_feedback({"resultCode": "Error", "result": "Please upload an invoice."})
        return
    yield "**Starting...** Watch the CardScanner browser window. Progress will appear here.", '', None
    history = []
    browser_view = ''
    started = time.monotonic()
    def log(message=None):
        elapsed = int(time.monotonic() - started)
        if message is not None:
            history.append(f"[{elapsed // 60:02d}:{elapsed % 60:02d}] {message}")
        return '<pre style="white-space:pre-wrap;max-height:360px;overflow:auto">' + html.escape('\n'.join(history)) + '</pre>'
    try:
        with open(file.name, "rb") as upload:
            with requests.post(
                "http://127.0.0.1:9000/invoice_ocr",
                files={"file": (os.path.basename(file.name), upload)},
                data={"show_browser": str(show_browser).lower(), "stream": "true", "engine": engine, "auto_verify": "true", "processing_requested": "true"},
                timeout=(10, 30), stream=True,
            ) as response:
                if 'application/x-ndjson' not in response.headers.get('Content-Type', ''):
                    yield invoice_feedback(response.json())
                    return
                for line in response.iter_lines(chunk_size=1):
                    if not line:
                        continue
                    event = json.loads(line)
                    if event.get('type') == 'progress':
                        if event.get('image'):
                            browser_view = '<img alt="Live CardScanner browser view" style="width:100%" src="' + html.escape(event['image'], quote=True) + '">'
                            yield log('Browser snapshot refreshed.'), browser_view, None
                        else:
                            yield log(event['message']), browser_view, None
                    elif event.get('type') == 'result':
                        status, preview, result = invoice_feedback(event)
                        yield log(status.replace('**', '')), preview or browser_view, result
                        return
                    elif event.get('type') == 'heartbeat':
                        yield log(), browser_view, None
                yield invoice_feedback({"resultCode": "Error", "result": "The backend connection ended before a result was received."})
    except requests.Timeout:
        yield invoice_feedback({"resultCode": "Error", "result": "Invoice OCR timed out. Please retry."})
    except (requests.RequestException, ValueError) as exc:
        yield invoice_feedback({"resultCode": "Error", "result": f"Cannot read backend response: {exc}"})


def blank_view():
    return ('', '', None, '', '', gr.update(value='Extract invoice', interactive=True),
            gr.update(value=False, visible=False, interactive=False),
            gr.update(visible=False), gr.update(value='', visible=False), '')


def job_view(job):
    with job.lock:
        now = time.monotonic()
        advance_verification(job, now)
        phase = job.verification_phase
        ready = job.result is not None and not job.failed
        show_progress = phase == 'verified'
        progress_elapsed = max(0, now - job.progress_started) if job.progress_started is not None else 0
        if show_progress and job.running:
            job.display_percent = max(job.display_percent, min(95, int(progress_elapsed / job.progress_duration * 95)))
        if show_progress and ready and progress_elapsed >= .5:
            job.display_percent = 100
        reveal = show_progress and ready and job.display_percent == 100
        status = job.status
        if ready and phase == 'awaiting':
            status += confirmation_warning()
        label = 'Complete' if reveal else ('Stopped - retry available' if job.failed else 'Estimated processing progress')
        if job.running:
            button = 'Processing...'
        elif job.failed:
            button = 'Retry extraction'
        elif reveal:
            button = 'View result'
        else:
            button = 'Retry / show result'
        processing_seconds = (job.finished or now) - job.started if job.started is not None else 0
        confirmation_seconds = job.confirmed_at - job.created if job.confirmed_at is not None else None
        remaining = max(0, job.progress_duration - progress_elapsed) if job.running and show_progress else None
        loading = phase in {'preparing', 'confirming'}
        spinner = '<div class="verification-loading" role="status"><span class="verification-dots"></span><span>Verifying...</span></div>'
        note = 'Processing continues in the background.' if phase != 'verified' else ''
        return (
            status, job.preview if reveal else '', job.result if reveal else None,
            progress_html(job.display_percent, label, visible=show_progress, remaining=remaining),
            parallel_timing_html(confirmation_seconds, processing_seconds, now - job.created),
            gr.update(value=button, interactive=not job.running),
            gr.update(value=phase in {'confirming', 'verified'}, visible=phase == 'awaiting', interactive=phase == 'awaiting'),
            gr.update(visible=phase != 'verified'),
            gr.update(value=spinner, visible=loading), note,
        )


def run_invoice_job(file, show_browser, engine, job):
    try:
        for status, preview, result in invoice_events(file, show_browser, engine):
            with job.lock:
                if job.cancelled:
                    return
                job.status, job.preview = status, preview
                job.percent = progress_for(status, job.percent)
                if result is not None:
                    job.result = result
                    job.finished, job.running = time.monotonic(), False
                    return
    except (OSError, ValueError):
        with job.lock:
            job.status = 'Could not process this invoice. Please retry.'
    finally:
        with job.lock:
            if job.running:
                job.running, job.failed = False, True
                job.finished = time.monotonic()


def start_invoice_job(file, show_browser, engine, job):
    with job.lock:
        if job.running or job.result is not None:
            return
        job.running, job.failed = True, False
        job.started, job.finished = time.monotonic(), None
        job.percent, job.status, job.preview = 0, '', ''
        job.display_percent = 0
        if job.verification_phase == 'verified':
            job.progress_started, job.progress_duration = job.started, 60
        job.worker = threading.Thread(target=run_invoice_job, args=(file, show_browser, engine, job), daemon=True)
        job.worker.start()


def reset_invoice_confirmation(file, timing=None, show_browser=True, engine='camoufox'):
    # Mutate the same per-session State object so the periodic renderer always
    # sees the latest upload; the renderer never captures an obsolete job ID.
    state = timing if timing is not None else {}
    previous = get_job(state.get('job_id'))
    if previous:
        with previous.lock:
            previous.cancelled = True
    state.clear()
    if file is None:
        return (state,) + blank_view()
    state['job_id'] = create_job(file.name)
    job = get_job(state['job_id'])
    start_invoice_job(file, show_browser, engine, job)
    return (state,) + job_view(job)


def confirmation_changed(checked, timing):
    job = get_job((timing or {}).get('job_id'))
    if job is None:
        return blank_view()
    with job.lock:
        now = time.monotonic()
        advance_verification(job, now)
        if checked and job.verification_phase == 'awaiting':
            job.verification_phase = 'confirming'
            job.phase_until = now + 5
        elif not checked and job.verification_phase in {'confirming', 'verified'}:
            job.verification_phase, job.confirmed = 'awaiting', False
            job.confirmed_at, job.progress_started = None, None
            job.display_percent = 0
        return job_view(job)


def poll_invoice(timing):
    job = get_job((timing or {}).get('job_id'))
    return job_view(job) if job is not None else tuple(gr.update() for _ in range(10))


def process_invoice(file, show_browser, engine, timing):
    job = get_job((timing or {}).get('job_id'))
    if file is None or job is None or job.file_key != file.name:
        view = list(blank_view())
        view[0] = 'Please upload an invoice first.'
        return tuple(view)
    start_invoice_job(file, show_browser, engine, job)
    return job_view(job)


INVOICE_CSS = '''
#invoice-confirmation:not(.hide) {position:fixed!important;inset:0!important;z-index:10000;width:100vw!important;height:100dvh!important;max-width:none!important;margin:0!important;padding:0!important;border:none!important;border-radius:0!important;background:rgba(15,23,42,.28)!important;display:flex!important;align-items:center;justify-content:center;backdrop-filter:blur(2px)}
#invoice-confirmation > .styler {width:min(300px,calc(100vw - 32px))!important;flex:none!important;box-sizing:border-box;min-height:66px;background:#fafafa!important;color:#111827;border:1px solid #d3d3d3!important;border-radius:3px!important;padding:10px 9px!important;box-shadow:0 12px 40px rgba(15,23,42,.16)}
#verification-row {display:flex!important;flex-wrap:nowrap!important;align-items:center!important;gap:6px!important;margin:0!important;height:44px!important;min-height:44px!important}
#verification-row .wrap {display:none!important}
#verification-row > .block {height:44px!important;min-height:0!important}
#verification-row > .form {flex:1 1 0!important}
#verification-brand.block {display:flex!important;align-items:center!important;justify-content:flex-end!important}
#verification-row > * {min-width:0!important}
#verification-spinner,#human-checkbox {flex:1 1 0!important;min-width:0!important;border:none!important;background:transparent!important;padding:0!important}
#human-checkbox label {padding:0!important;border:none!important;background:transparent!important;box-shadow:none!important;gap:8px;white-space:nowrap;font-size:13px;color:#111827!important}
#human-checkbox input {appearance:none!important;width:24px!important;height:24px!important;flex-shrink:0;border:2px solid #555!important;border-radius:2px!important;background:#fff!important}
#human-checkbox input:checked {appearance:auto!important;accent-color:#16a34a}
#verification-brand {flex:0 0 78px!important;min-width:78px!important;padding:0!important;border:none!important;background:transparent!important}
#verification-note {display:none!important}
.verification-loading {display:flex;align-items:center;gap:10px;min-height:40px;font-size:14px}
.verification-dots {display:inline-block;width:27px;height:27px;border:3px dotted #16a34a;border-radius:50%;animation:verification-spin 1.5s linear infinite}
@keyframes verification-spin {to {transform:rotate(360deg)}}
.verification-brand {text-align:right;font-size:9px;font-weight:800;letter-spacing:.04em;padding-top:0;color:#111827}
.verification-brand small {display:block;font-size:8px;font-weight:400;letter-spacing:0;margin-top:3px}
.invoice-eta {margin-top:8px;font-variant-numeric:tabular-nums}
.invoice-progress {padding:18px;border:1px solid #cbd5e1;border-radius:10px;margin:12px 0}
.progress-heading {display:flex;justify-content:space-between;gap:16px;margin-bottom:10px}
.invoice-progress progress {width:100%;height:18px;accent-color:#6366f1}
.invoice-progress small {display:block;margin-top:8px;color:#64748b}
.invoice-warning {padding:14px;border:1px solid #f59e0b;border-radius:8px;background:#fffbeb;color:#92400e}
.invoice-timing {padding:10px 0;font-variant-numeric:tabular-nums}
'''


with gr.Blocks(title="Invoice OCR and Deepfake Detection", css=INVOICE_CSS) as demo:
    with gr.Tab("Invoice OCR"):
        gr.Markdown("## Invoice OCR\nExtract structured invoice data using CardScanner.")
        gr.Markdown("Your uploaded invoice is sent to **cardscanner.co** for processing.")
        with gr.Row():
            with gr.Column():
                invoice_input = gr.File(
                    elem_id='invoice-upload',
                    interactive=True,
                    label="Invoice image or PDF (up to 10 MB)",
                    file_types=[".jpg", ".jpeg", ".png", ".bmp", ".gif", ".webp", ".pdf"],
                )
                confirmation_timing = gr.State({})
                with gr.Group(visible=False, elem_id='invoice-confirmation') as confirmation_panel:
                    with gr.Row(elem_id='verification-row'):
                        verification_spinner = gr.HTML(visible=False, scale=3, elem_id='verification-spinner')
                        user_confirmed = gr.Checkbox(label="Verify you are human", value=False, visible=False, elem_id='human-checkbox', scale=3)
                        gr.HTML('<div class="verification-brand">INVOICE OCR<small>Local confirmation</small></div>', elem_id='verification-brand')
                    confirmation_note = gr.Markdown(elem_id='verification-note')
                show_browser = gr.Checkbox(
                    label="Show CardScanner browser while processing", value=True
                )
                browser_engine = gr.Dropdown(choices=["camoufox", "chromium"], value="camoufox", label="Browser engine")
                gr.Markdown("Processing starts on upload and continues during confirmation. After confirmation, the progress bar shows the estimated remaining processing time.")
                invoice_button = gr.Button("Extract invoice", variant="primary")
            with gr.Column():
                invoice_progress = gr.HTML(label='Processing progress')
                invoice_timing = gr.HTML(label='Elapsed time')
                invoice_status = gr.HTML(label="Activity log")
                invoice_preview = gr.HTML(label="Invoice result")
                invoice_output = gr.JSON(label="Extracted invoice data and download URL")
        view_outputs = [invoice_status, invoice_preview, invoice_output, invoice_progress, invoice_timing,
                        invoice_button, user_confirmed, confirmation_panel, verification_spinner, confirmation_note]
        user_confirmed.input(confirmation_changed, [user_confirmed, confirmation_timing], view_outputs,
                             queue=False, show_progress='hidden')
        invoice_button.click(process_invoice, [invoice_input, show_browser, browser_engine, confirmation_timing],
                             view_outputs, queue=False, show_progress='hidden')
        invoice_input.change(reset_invoice_confirmation, [invoice_input, confirmation_timing, show_browser, browser_engine],
                             [confirmation_timing] + view_outputs, queue=False, show_progress='hidden')
        demo.load(poll_invoice, confirmation_timing, view_outputs, every=.5, show_progress='hidden')
    with gr.Tab("Deepfake Detection"):
        with gr.Row():
            with gr.Column():
                image_input = gr.Image(type='pil')
                gr.Examples([str(Path(__file__).parent / 'examples' / name) for name in ['1.jpg', '2.jpg', '3.jpg']], inputs=image_input)
                process_button = gr.Button("Process")
            with gr.Column():
                json_output = gr.HTML()
        process_button.click(process_image, inputs=[image_input], outputs=[json_output])

if __name__ == "__main__":
    demo.queue().launch(server_name="0.0.0.0", server_port=7860)


