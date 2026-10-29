# Any endpoint, any model, and the tools that make real files

Version 0.9.0 made the provider a choice; **0.9.1** added a relay entry and a
hand-typed model id; **0.10.0** finishes the idea:

* **any endpoint** can be added by address — name, base URL, protocol and
  whether it wants a key — and then behaves exactly like a built-in service;
* **GapGPT** is a first-class entry (`https://api.gapgpt.app/v1`);
* every model row says **free**, **paid**, or *nothing* when the catalogue
  published no price;
* the model chip above the send button actually changes the model;
* chat accepts **197 file types** and hands pictures to vision models as real
  image parts;
* six **creative tools** let a text model produce real files: charts, PDFs,
  resized images, contact sheets, archives — and read a file's true metadata.

## 1. Providers

### What is supported

| Service | Protocol | Key | Notes |
|---|---|---|---|
| OpenRouter | OpenAI-compatible | `sk-or-…` | Prices and capability tags come from its catalogue. |
| OpenAI | OpenAI-compatible | `sk-proj-…` / `sk-…` | Catalogue has no prices, so nothing is claimed about cost. |
| Anthropic | Messages API | `sk-ant-…` | System prompt is hoisted to its own field; temperature 0–1. |
| Google Gemini | generateContent / stream | `AIza…` | Embedding models are filtered out of the picker. |
| Groq, DeepSeek, Mistral | OpenAI-compatible | vendor key | Same code path as OpenAI. |
| Tooken Club | OpenAI-compatible | `tc_live_…` | A reseller gateway: one key for GPT, Claude, DeepSeek, Gemini, Kimi, GLM and Grok. Its catalogue needs a key, so an id can also be typed by hand. |
| Ollama, LM Studio | OpenAI-compatible | none | Local, so the system proxy is bypassed on purpose. |
| Custom | OpenAI-compatible | optional | Any base URL; `http` is allowed only on the loopback interface. |

### Adding your own endpoint

`API page → Custom endpoints`. Fill in a name, the base URL and the protocol,
then press **Save endpoint**. The endpoint is stored in `ai.custom_endpoints`,
registered at boot before any page asks which providers exist, and appears in
the provider list under its own name. It keeps its own vault key
(`ai.key.<slug>`), its own catalogue cache and its own models.

- The id is derived from the name and always starts with `cx-`, which cannot
  collide with a built-in id and satisfies the vault's id rule.
- `http` is accepted for `127.0.0.1` and `localhost` only; a remote host must be
  `https`, exactly like the built-in services.
- **Delete** removes the endpoint, its stored key and its URL, and moves the
  selection back to OpenRouter if it was active. Conversations are untouched.
- Three protocols are offered: OpenAI-compatible (chat, tool calling),
  Anthropic Messages and Google Gemini. Anything else is not guessed.

### Free or paid — said only when known

A catalogue row carries `pricing.prompt` / `pricing.completion` or it does not.
`price_state()` answers `free`, `paid` or `unknown`, and the model picker, the
catalogue row and the default-model popup all read that one answer:

| Catalogue says | Badge | Price column |
|---|---|---|
| both prices are 0 | **free** (green) | `free` |
| any price is above 0 | **paid** (amber) | `$3 / $15` |
| no pricing at all | nothing | `price n/a` |

Before this, a missing price was read as zero and a paid model could wear a
green *free* badge. The test `test_models_are_labelled_free_or_paid_only_when_known`
locks the three cases.

### Example: entering a relay key (Tooken Club)

`API page → Provider → Tooken Club`. The base URL field already holds
`https://tooken.club/v1`, and the key field expects a `tc_live_…` value.

1. Paste the key into **API key** and press **Save key**. It is written to the
   encrypted vault under `ai.key.tooken`, never to a settings file, a log or an
   export. The page only ever shows a masked version afterwards.
2. Press **Load models**. That is one request: `GET https://tooken.club/v1/models`
   with `Authorization: Bearer <key>`.
3. Choose a model — type in the default-model list to filter it, or press
   **Use model** on any row. The id is stored in `ai.default_model` and becomes
   the model of the open chat.
4. If the catalogue comes back empty, or the model you want is not in it, type
   its exact id next to **Model id** and press **Use model**. The row is marked
   *typed by hand*, so it is never mistaken for something the provider listed.

A wrong or revoked key comes back as `401 invalid_api_key`, and the page reports
it as an authentication error; nothing is retried and no tokens are spent.

### Where the switch is

`API page → Provider`. Choosing a service changes four things at once: the base
URL field, the key field (and which stored key it shows), the catalogue that is
loaded, and the model list offered in the composer and the header. Nothing is
reset: every provider keeps its own key and its own URL.

### What is stored, and where

- Keys live in the encrypted vault under `ai.key.<provider>`; OpenRouter keeps
  the pre-0.9 slot `openrouter.api_key`, so an upgrade never loses a key.
- URLs live in `ai.base_urls` as a provider → URL map.
- The catalogue cache is `ai.model_cache`, one list per provider, migrated from
  the old single `ai.openrouter_cache` list on first read.

### Rules that did not change

- **A provider with no key is usable without pretending one is stored.** A local
  server or an open gateway shows "no key needed" instead of "a key is stored: ''".
- **A key is only checked for its shape**, never declared "valid" offline.
  The server still decides; the app only prevents obvious mistakes (spaces,
  line breaks, a prefix from a different vendor).
- **No invented prices.** Catalogues without prices are marked
  `price_known=False`, and the badge stays off instead of saying "free".
- **Remote hosts must be https.** `http` is accepted for `127.0.0.1` and
  `localhost` only, because a local server cannot offer TLS.
- **Agent Mode needs an OpenAI-compatible provider.** Tool calling is
  implemented for that protocol only; choosing Anthropic or Gemini disables the
  run button with a stated reason instead of failing mid-run.
- **Live calls were not tested from this sandbox.** Every network path here is
  driven through `httpx.MockTransport` and local servers; see the test section
  of the release notes. One exception is worth stating precisely: an
  unauthenticated `GET https://tooken.club/v1/models` was performed and answered
  `401 invalid_api_key` in the OpenAI error shape, which proves the host, the
  TLS path and the `/v1` route exist — it says nothing about a *valid* key or
  about the models a real account can see, because no authenticated request was
  made here.

## 2. Chat input: 197 formats, and pictures that a model can see

`myai/services/attachments.py` now accepts 197 extensions in eight families:

| Family | Examples | What the model receives |
|---|---|---|
| text / code | `.py .md .json .csv .ipynb .rs .go .sql .tex` | the text, decoded and fenced |
| office | `.docx .xlsx .pptx .odt .ods .odp .epub` | the text inside the archive |
| image | `.png .jpg .webp .tiff .avif .heic .psd .svg` | pixel size in words, plus a real image part on a vision model |
| audio | `.mp3 .wav .flac .m4a .ogg .opus` | duration/channels when the header carries them |
| video | `.mp4 .mkv .mov .webm .avi .m4v` | duration from the `mvhd` box, real metadata |
| archive | `.zip .tar .gz .7z .rar .whl .iso` | the member list (names and sizes) for zip/tar |
| data / pdf | `.pdf .sqlite .parquet .h5 .npy` | a stated "no text extractor" note |

The file dialog is built from the same sets (`dialog_filters()`), so a file the
dialog offers can never be rejected a second later. A picture is sent as an
`image_url` part **only** when the selected model's catalogue entry says it sees
images; a text-only model receives the filename and the pixel size instead of a
megabyte of base64 it cannot read (`ai.attach_images` turns the whole thing off).

## 3. Creative tools: files a text model can actually make

`myai/services/creative.py` is pure Python plus Qt's own writers, and it works
offline with no media provider:

| Generator | Output | Notes |
|---|---|---|
| `render_chart` | real SVG (bar / line / pie) | axis labels, legend, one `<rect>` per value |
| `render_pdf` | real PDF | A4, Markdown rendered by the app's own converter |
| `convert_image` | png / jpg / webp copy | smooth resize, aspect kept, 8192 px cap |
| `contact_sheet` | one grid PNG | captioned cells, 1–8 columns |
| `zip_bundle` | real zip | paths kept relative to a base folder |
| `probe_media` | text | size, pixels, WAV/MP4 duration from the header |

Six agent tools wrap them (`create_chart`, `export_pdf`, `resize_image`,
`contact_sheet`, `zip_files`, `describe_file`), so any OpenAI-compatible model
can choose them — and the *model* picks which tool to use, not the app. The
Image and Video studios, Output Studio (PDF) and the Usage page (CSV) expose the
same code as buttons. Video and speech are still absent, and both pages say so.

## 4. The model picker

Before: `QMenu` with one action per model. OpenRouter publishes 300+ models, so
the menu grew past the window, had no search and no scrollbar.

Now: a popup that

- caps at eight rows and never more than half the screen height;
- has a search box that keeps the keyboard focus and filters on the display
  name, the model id and its capability tags (words can be typed in any order);
- paints rows with a delegate, so 300 models cost one widget, not 300;
- shows context size, free/tools/vision tags, and a check mark on the current
  model;
- is driven by ↑ ↓ PageUp PageDown Enter Esc, and closes on Escape or a click
  outside.

The same widget is used by the composer chip, the header chip and the default
model selector on the API page. Short lists (six rows or fewer) keep the plain
menu, where a search box would be noise.

## 5. Files that carry the change

- `myai/services/providers.py` — the registry, key rules, URL rules, the
  three-protocol client and the per-provider cache helpers.
- `myai/security/secrets.py` — `get_key/set_key/has_key/configured_providers`.
- `myai/services/settings.py` — `ai.provider`, `ai.base_urls`, `ai.model_cache`.
- `myai/ui/widgets/model_picker.py` — the popup, its model and its delegate.
- `myai/ui/views/api_page.py` — the provider card and provider-aware key,
  catalogue and default-model controls.
- `myai/ui/main_window.py` — provider-aware bootstrap and cache, and the rich
  choices handed to the composer and header chips.
- `myai/services/creative.py` — the six generators (SVG, PDF, image, sheet, zip,
  probe) with Qt imported lazily so the services layer still imports headless.
- `myai/services/attachments.py` — the 197-extension table, `dialog_filters()`,
  `extension_kind()` and real media metadata.
- `myai/services/chat.py` — multimodal turn assembly, gated on the model's
  vision capability.
- `myai/services/providers.py` — custom endpoint registry, GapGPT entry.
- `myai/services/tools.py` — six creative tools and the `paths` field on
  `ToolContext`.
- Tests: `tests/unit/test_providers.py` (49), `tests/ui/test_model_picker.py`
  (18), `tests/unit/test_creative_tools.py` (17),
  `tests/ui/test_custom_endpoints.py` (6), plus updated expectations in
  `test_phase2_pages`, `test_doctor`, `test_agent_ideas`, `test_attachments`.
