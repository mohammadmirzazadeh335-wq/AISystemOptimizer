# More than one provider, and a model picker that stays out of the way

Version 0.9.0. Two changes the app had been missing: it can now talk to services
other than OpenRouter, and the model list is a small searchable popup instead of
a menu that covered half the window.

## 1. Providers

### What is supported

| Service | Protocol | Key | Notes |
|---|---|---|---|
| OpenRouter | OpenAI-compatible | `sk-or-…` | Prices and capability tags come from its catalogue. |
| OpenAI | OpenAI-compatible | `sk-proj-…` / `sk-…` | Catalogue has no prices, so nothing is claimed about cost. |
| Anthropic | Messages API | `sk-ant-…` | System prompt is hoisted to its own field; temperature 0–1. |
| Google Gemini | generateContent / stream | `AIza…` | Embedding models are filtered out of the picker. |
| Groq, DeepSeek, Mistral | OpenAI-compatible | vendor key | Same code path as OpenAI. |
| Ollama, LM Studio | OpenAI-compatible | none | Local, so the system proxy is bypassed on purpose. |
| Custom | OpenAI-compatible | optional | Any base URL; `http` is allowed only on the loopback interface. |

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
  of the release notes.

## 2. The model picker

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

## 3. Files that carry the change

- `myai/services/providers.py` — the registry, key rules, URL rules, the
  three-protocol client and the per-provider cache helpers.
- `myai/security/secrets.py` — `get_key/set_key/has_key/configured_providers`.
- `myai/services/settings.py` — `ai.provider`, `ai.base_urls`, `ai.model_cache`.
- `myai/ui/widgets/model_picker.py` — the popup, its model and its delegate.
- `myai/ui/views/api_page.py` — the provider card and provider-aware key,
  catalogue and default-model controls.
- `myai/ui/main_window.py` — provider-aware bootstrap and cache, and the rich
  choices handed to the composer and header chips.
- Tests: `tests/unit/test_providers.py` (42), `tests/ui/test_model_picker.py`
  (13), plus updated expectations in `test_phase2_pages`, `test_doctor`.
