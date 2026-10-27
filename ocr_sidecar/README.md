# PaddleOCR box sidecar

> **STATUS (2026-10-24): built & working; now actually matches.** The sidecar runs
> (2.x stack: paddlepaddle 2.6.2 + paddleocr 2.7.3, Python 3.12) and returns boxes.
> The earlier "matched 0" was NOT a model problem — it was two reconstruction bugs
> (now fixed in `apps/invoices/engines.py`): (1) the PharmaOverseas column template
> was never selected for the English vendor name "PHARMA OVER SEAS", so boxes fell
> through to the generic path; and (2) `_structured_by_bands` dropped every product
> row whose price cell the engine missed — fatal for PaddleOCR, which reads names
> well but misses ~half the numbers. After the fix a representative PharmaOverseas
> page goes **0 → 11/14 matched**, and the full-invoice benchmark **0 → 7 matched**.
> Remaining gap is PP-OCRv3's mediocre Arabic recognition (CPU has no PP-OCRv5) plus
> misaligned numeric columns, so matched lines still need price review. Both fixes
> also help the Tesseract/`auto` path (same template, same row-survival rule).
>
> Production still uses `auto` (Tesseract → Gemini escalation); `paddleocr` stays
> opt-in via `--engine paddleocr` (`auto` never picks it — Tesseract has higher
> registry priority). A **GPU or Linux box** running PP-OCRv5 (81%) would lift the
> recognition ceiling further.



PaddleOCR PP-OCRv5 (Arabic) as a tiny local HTTP server, so the main Django app
(**Python 3.14**, where `paddlepaddle` has no wheel) can use it. The app's
`paddleocr` engine POSTs a page image and feeds the returned boxes through its
existing band/template pipeline — PaddleOCR becomes a drop-in better box source.

## Why a sidecar (not the main venv)
- **`paddlepaddle` has no Python 3.14 wheel** — it cannot install in the app's venv.
- It (and Surya/docTR) also force-upgrade `transformers` / `pillow` / `protobuf`,
  which would break the app's `easyocr` / `faster-whisper` / `gemini` stack.
- A separate venv isolates all of that. The app only ever makes an HTTP call.

## Install (one-time) — needs Python 3.10–3.12

```powershell
# 1. make a 3.12 venv just for OCR (adjust the python path to your 3.12 install)
py -3.12 -m venv C:\ocr_sidecar_venv
C:\ocr_sidecar_venv\Scripts\python -m pip install --upgrade pip
C:\ocr_sidecar_venv\Scripts\python -m pip install -r requirements.txt
```

(No Python 3.12 yet? Install from python.org, or `winget install Python.Python.3.12`.
 GPU box: swap `paddlepaddle` for `paddlepaddle-gpu` in requirements.txt.)

## Run

```powershell
C:\ocr_sidecar_venv\Scripts\python server.py
# → serving on http://127.0.0.1:8077   (first run downloads the Arabic model)
```

Leave it running (or install it as a Windows service / scheduled task). Check:
`curl http://127.0.0.1:8077/health` → `{"ok": true, "lang": "arabic"}`

## Point the app at it

In the main app's `.env`:
```
PADDLE_OCR_URL=http://127.0.0.1:8077/boxes
```
Then from the app venv:
```
python manage.py ocr_engines          # paddleocr → available: yes
python manage.py benchmark_vs_softech --pdf "…/فارما اوفر.pdf" --host 192.168.1.8 \
    --supplier فارما --limit 20 --engine paddleocr --out diff_paddle.csv
```

## Surya / docTR
Install them in this same sidecar venv and add `/boxes`-style endpoints the same way
(both return boxes + text). Keep them out of the app's 3.14 venv for the same reason.
