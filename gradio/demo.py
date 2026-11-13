import os
import gradio as gr
import requests
import json
import io
import html
import time
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


def process_invoice(file, show_browser, engine):
    if file is None:
        yield invoice_feedback({"resultCode": "Error", "result": "Please upload an invoice."})
        return
    yield "**Starting...** Watch the CardScanner browser window. Progress will appear here.", '', None
    history = []
    browser_view = ''
    started = time.monotonic()
    def log(message):
        elapsed = int(time.monotonic() - started)
        history.append(f"[{elapsed // 60:02d}:{elapsed % 60:02d}] {message}")
        return '<pre style="white-space:pre-wrap;max-height:360px;overflow:auto">' + html.escape('\n'.join(history)) + '</pre>'
    try:
        with open(file.name, "rb") as upload:
            with requests.post(
                "http://127.0.0.1:9000/invoice_ocr",
                files={"file": (os.path.basename(file.name), upload)},
                data={"show_browser": str(show_browser).lower(), "stream": "true", "engine": engine, "auto_verify": "true"},
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
                yield invoice_feedback({"resultCode": "Error", "result": "The backend connection ended before a result was received."})
    except requests.Timeout:
        yield invoice_feedback({"resultCode": "Error", "result": "Invoice OCR timed out. Please retry."})
    except (requests.RequestException, ValueError) as exc:
        yield invoice_feedback({"resultCode": "Error", "result": f"Cannot read backend response: {exc}"})


with gr.Blocks(title="Invoice OCR and Deepfake Detection") as demo:
    with gr.Tab("Invoice OCR"):
        gr.Markdown("## Invoice OCR\nExtract structured invoice data using CardScanner.")
        gr.Markdown("Your uploaded invoice is sent to **cardscanner.co** for processing.")
        with gr.Row():
            with gr.Column():
                invoice_input = gr.File(
                    label="Invoice image or PDF (up to 10 MB)",
                    file_types=[".jpg", ".jpeg", ".png", ".bmp", ".gif", ".webp", ".pdf"],
                )
                show_browser = gr.Checkbox(
                    label="Show CardScanner browser while processing", value=True
                )
                browser_engine = gr.Dropdown(choices=["camoufox", "chromium"], value="camoufox", label="Browser engine")
                gr.Markdown("Click Extract invoice. Verification is attempted automatically, followed by conversion and result extraction. Cloudflare rejection or site usage limits are reported here.")
                invoice_button = gr.Button("Extract invoice", variant="primary")
            with gr.Column():
                invoice_status = gr.HTML(label="Activity log")
                invoice_preview = gr.HTML(label="Invoice result")
                invoice_output = gr.JSON(label="Extracted invoice data and download URL")
        invoice_button.click(process_invoice, [invoice_input, show_browser, browser_engine], [invoice_status, invoice_preview, invoice_output])
    with gr.Tab("Deepfake Detection"):
        with gr.Row():
            with gr.Column():
                image_input = gr.Image(type='pil')
                gr.Examples(['examples/1.jpg', 'examples/2.jpg', 'examples/3.jpg'], inputs=image_input)
                process_button = gr.Button("Process")
            with gr.Column():
                json_output = gr.HTML()
        process_button.click(process_image, inputs=[image_input], outputs=[json_output])

if __name__ == "__main__":
    demo.queue().launch(server_name="0.0.0.0", server_port=7860)
