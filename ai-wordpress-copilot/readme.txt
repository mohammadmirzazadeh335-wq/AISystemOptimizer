=== AI WordPress Copilot ===
Contributors: aiwcstudio
Tags: ai, assistant, seo, automation, openai
Requires at least: 6.0
Tested up to: 6.8
Requires PHP: 7.4
Stable tag: 1.0.0
License: GPLv2 or later
License URI: https://www.gnu.org/licenses/gpl-2.0.html

A real AI agent for WordPress: chat-driven site management, design, SEO, content tools with safe execution, approvals, snapshots and rollback.

== Description ==

AI WordPress Copilot is a modular AI agent (not just a chat box) that can:

* Create and edit real pages, posts, menus, media alt text and products (WooCommerce)
* Design sections, header/footer (block themes + classic fallback), custom CSS
* Analyze SEO per-page and site-wide (title, meta, headings, links, alt text, schema, duplicates) with scoring
* Inspect the whole site through a bounded, cached Site Context Engine
* Remember brand facts and preferences across conversations (editable memory)
* Execute safely: WordPress nonces, capability checks, input validation, risk levels, admin approvals, activity log, snapshots & rollback
* Work with any OpenAI-compatible API (configurable Base URL, model, temperature, top-p, retries, timeout)

The admin UI is RTL-first Persian with full English support and dark/light themes.

== Installation ==

1. Upload the `ai-wordpress-copilot` folder to `/wp-content/plugins/`.
2. Activate the plugin.
3. Go to AI Copilot → API Connection and set your API key, Base URL and model.
4. Choose an execution mode in Settings (confirm-by-default is recommended).
5. Start chatting in AI Chat.

== Frequently Asked Questions ==

= Does it work with non-OpenAI providers? =

Yes. Any OpenAI-compatible endpoint works (set Base URL, e.g. `https://api.example.com/v1`).

= Is the API key exposed to the browser? =

No. The key is stored server-side and always masked in API responses.

= Can the AI delete content? =

Only with explicit administrator approval (depending on execution mode). Every mutation is logged and snapshotted for rollback.

== Changelog ==

= 1.0.0 =
* Initial release: agent loop with tool calling, 30+ tools, chat UI, SEO engine, memory, activity log, snapshots/rollback, job queue.
