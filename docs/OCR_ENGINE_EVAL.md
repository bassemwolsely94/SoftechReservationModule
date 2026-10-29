# OCR engine evaluation & setup

The invoice OCR stack is a **pluggable engine registry** (`apps/invoices/engines.py`).
Every engine — free-local or paid/served API — registers an `EngineSpec` and is then
selectable anywhere via its name (`--engine <name>`), auto-escalation, or
`INVOICE_OCR_ENGINE`. See what's installed/keyed right now:

```bash
python manage.py ocr_engines
```

| engine | kind | how to enable | notes |
|---|---|---|---|
| `tesseract` | free, in-proc | installed | ara+eng + RapidOCR digit voting. Primary free engine. |
| `easyocr` | free, in-proc | installed | ar+en; slow on CPU. |
| `paddleocr` | free, in-proc | `pip install paddleocr paddlepaddle` | **needs Python ≤ 3.12** (no 3.14 wheel). Classic PaddleOCR detect+recognize. |
| `gemini` | API | `GEMINI_API_KEY[,_2]` | free tier 20/day/model/key; key rotation + cooldown built in. |
| `mistral` | API | `MISTRAL_API_KEY` | paid, no daily cap; `pip install mistralai`. |
| `vlm` | API (self-hosted) | `VLM_OCR_URL` | **any served vision model** over an OpenAI-compatible endpoint. This is how you eval PaddleOCR-VL / Qwen2.5-VL / Nanonets-OCR2. |

## Which VLM fits the `vlm` adapter

Our `vlm` engine sends the page image + a prompt asking for our **13-field JSON**
({lines:[…]}). So it needs a **general instruction-following vision model** that
obeys a JSON prompt:

- ✅ **Qwen2.5-VL-7B-Instruct** (recommended self-host), Pixtral, GPT-4o, Gemini — all follow the JSON prompt.
- ⚠️ **PaddleOCR-VL is NOT a drop-in.** Served via vLLM it is a *task-prompt* OCR model
  ("OCR:", "Table Recognition:") returning markdown, and the official PaddleOCR docs
  discourage calling the raw `/v1/chat/completions` with an OpenAI client for document
  parsing. Using PaddleOCR-VL would need its full pipeline (`vl_rec_backend="vllm-server"`)
  plus a custom markdown→13-fields adapter — more work than it's worth for this use.

This machine is CPU-only on Python 3.14, so the model runs best on a separate GPU box.

**1. On a GPU box, serve a JSON-capable VLM over the OpenAI schema (vLLM):**

```bash
pip install "vllm>=0.11.1"
vllm serve Qwen/Qwen2.5-VL-7B-Instruct --port 8000
# → http://<gpu-box-ip>:8000/v1/chat/completions
```

(Any OpenAI chat/vision server works: Ollama, HF TGI, LM Studio.) For a zero-setup
semantic baseline, `--engine gemini` needs no server at all.

**2. Point this app at it** (`.env`):

```
VLM_OCR_URL=http://<gpu-box>:8000/v1/chat/completions
VLM_OCR_MODEL=PaddlePaddle/PaddleOCR-VL
VLM_OCR_KEY=            # only if the server requires a bearer token
```

**3. Confirm and A/B it** against the ground-truth HQ benchmark:

```bash
python manage.py ocr_engines                       # vlm → available: yes
python manage.py benchmark_vs_softech --pdf "…/رامكو.pdf" --host 192.168.1.8 \
    --supplier رامكو --limit 20 --engine vlm --out diff_vlm.csv
```

Compare the `── ACCURACY ──` block (cost/qty/discount %, `matched via`, OCR code
recall) against `--engine tesseract` and `--engine gemini` on the same invoices.
Score Arabic quality with a KITAB-Bench-style set if you want a model-level number.

## Image / PDF perfecting (free accuracy, no new engine)

`preprocess.enhance_for_ocr` always does grayscale + autocontrast + deskew + upscale.
These extra steps are **opt-in** (off by default) because the best combination is
scan-dependent — turn them on in `.env` and A/B via the benchmark:

```
INVOICE_PDF_DPI=300        # 300 is Tesseract's sweet spot (was 200)
INVOICE_OCR_EQUALIZE=True  # histogram equalize — uneven lighting
INVOICE_OCR_SHARPEN=True   # unsharp mask — soft/blurry scans
INVOICE_OCR_BINARIZE=True  # Sauvola adaptive threshold — faint/shadowed scans
```

Re-run the benchmark after each toggle and keep whatever raises cost/qty accuracy
and OCR code recall for your scan quality.

## Fine-tuning (long-term, beats paid APIs on your own invoices)

Every confirmed invoice line is labelled data (vendor code + name → item, plus the
field values). Export the confirmed corpus and fine-tune Tesseract 5 (LSTM) or a
small VLM (Qwen2.5-VL / PaddleOCR-VL) on your distributors' layouts, then serve it
as the `vlm` engine. This is the in-house-OCR flywheel: accuracy compounds with use
at zero per-call cost.
