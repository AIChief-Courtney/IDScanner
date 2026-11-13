"""Presentation helpers for the local confirmation and processing phases."""
import html


def progress_for(message, current=0):
    stages = [
        ('opening cardscanner', 5), ('loading the invoice', 15),
        ('uploading your invoice', 25), ('upload accepted', 40),
        ('checking the uploaded', 45), ('verification click', 50),
        ('convert is enabled', 55), ('clicking convert', 65),
        ('conversion complete', 95),
    ]
    return max([current] + [value for marker, value in stages if marker in message.lower()])


def progress_html(percent, label, *, visible=True, remaining=None):
    if not visible:
        return ''
    percent = max(0, min(100, int(percent)))
    eta = '' if remaining is None else (
        f'<div class="invoice-eta">Estimated remaining: ~{max(1, int(remaining))}s</div>'
        if remaining > 0 else '<div class="invoice-eta">Taking longer than estimated…</div>'
    )
    return (
        '<div class="invoice-progress"><div class="progress-heading">'
        f'<strong>{html.escape(label)}</strong><strong>{percent}%</strong></div>'
        f'<progress aria-label="Invoice workflow progress" value="{percent}" max="100"></progress>'
        + eta +
        '<small>Estimated progress. Completion waits for the processing result.</small></div>'
    )


def confirmation_warning():
    return '<div role="alert" class="invoice-warning">Your invoice is processed. Select the confirmation checkbox to view the result. You can also retry viewing it without running OCR again.</div>'


def parallel_timing_html(confirmation_seconds, processing_seconds, elapsed_seconds):
    confirmation = 'waiting' if confirmation_seconds is None else f'{confirmation_seconds:.1f}s'
    return (
        '<div class="invoice-timing">'
        f'Confirmation: {confirmation} &nbsp; · &nbsp; Processing: {processing_seconds:.1f}s'
        f' &nbsp; · &nbsp; <strong>Elapsed: {elapsed_seconds:.1f}s</strong></div>'
    )
