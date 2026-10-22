# Agent Mode — user guide (English)

Agent Mode lets the model **do** things instead of only answering: list and read files in
the project you opened, write or delete a file, run it with the toolchain installed on your
machine, search the web, read GitHub issues, and store facts in memory. It is deliberately
narrow: the model may only use the twenty-two registered tools, every sensitive call needs your
approval, and a tool that cannot work says exactly why.

---

## 1. Opening it

1. Click **Agent Mode** in the sidebar (or switch the header to **Agent**).
2. Optional but recommended: open the project folder first in **Code Studio**. Every
   file tool except `create_project` works only inside that folder.
3. Pick the model in the **Model** dropdown. A badge next to the task says whether the
   model advertises tool calling (`Tools supported` / `No tool support` / `Tool support
   unknown`). The agent sends your key to OpenRouter exactly like chat does.
4. Type the goal (“Read `hello.py`, explain what it does and list the project files”) and
   press **Run agent** (or `Ctrl+Enter`).

## 2. The tools card

The left column lists all twenty-two tools with their risk level and live availability:

| Tool | What it does | Risk |
| --- | --- | --- |
| `list_files` | list the project tree | read |
| `read_file` | read a text file (size-capped, binary files refused) | read |
| `write_file` | write or overwrite a file | write |
| `make_folder` | create nested folders inside the project (traversal refused) | write |
| `create_project` | create a real project folder and remember it in Code Studio | write |
| `search_files` | grep the project case-insensitively, optional `*.py` glob | read |
| `delete_file` | delete one file | write |
| `run_file` | run a file with the detected toolchain, wall-clock limit | execute |
| `remember` / `recall` | store and search durable facts in memory | write / read |
| `save_output` | save a draft into Output Studio | write |
| `web_search` | query a SearxNG-compatible endpoint | network |
| `github_list_issues` | list open issues of a repo | network |
| `github_comment` | post a comment on an issue | network |
| `project_map` | structural map: languages with real line counts, largest files, entry points | read |
| `find_files` | glob search (`**/*.py`) with sizes, newest first | read |
| `read_lines` | numbered line window of one file (large files) | read |
| `scan_todos` | every TODO / FIXME / HACK / XXX / BUG with location | read |
| `diff_files` | real unified diff between two project files | read |
| `apply_patch` | apply `@@` hunks; all-or-nothing, line drift tolerated | write |
| `fetch_url` | read one public page as text (page reading, not search) | network |
| `generate_image` | **always unavailable** — no image provider exists | network |

“N of 22 ready” is computed from the real gates. A row marked *Unavailable* carries the
exact reason (no project folder, network off, no endpoint, no token, no image provider).
Hover a row to see the full text; the reason is also repeated in Settings → Agent.

### 2.1 The seven exploration and editing tools

These were added after Phase 5 to make the agent genuinely useful on a real
project, not only able to overwrite whole files:

* **`project_map`** is the suggested first call. It returns languages, real line
  counts, the five largest files and the usual entry points, so the model stops
  guessing file names.
* **`find_files`** answers "where is this?" with a glob, including `**/` patterns,
  and refuses patterns that leave the project.
* **`read_lines`** reads a numbered window instead of a 4 000-line file; the
  model can ask for lines 120–180 after seeing a traceback.
* **`scan_todos`** lists the markers a maintainer would grep for, with counts.
* **`diff_files`** shows a real `difflib` unified diff, or says the files are
  identical.
* **`apply_patch`** applies a unified diff to one file. Context must match
  exactly; line numbers may have drifted. If any hunk fails, **nothing is
  written** — there is no half-applied file. It is a `write` tool, so the
  approval dialog shows the exact patch first.
* **`fetch_url`** reads one public http(s) page through the same reader the Web
  Research page uses. It is a `network` tool: it needs *Allow network tools* and
  the normal approval.

## 3. Approval

With **Ask before writes, runs and network calls** enabled (the default), every `write`,
`execute` and `network` call opens a modal dialog showing the tool name **and the exact
arguments as JSON**. Read that JSON — it is the only thing the agent will execute.

- **Approve** runs the call.
- **Decline** records the step as *Declined*. Nothing is written, deleted, executed or sent.
  The model sees the refusal and may propose something else.

The dialog cannot be bypassed per tool; the global switch lives in Settings → Agent. Turning
it off makes sensitive calls run without asking — only do this when you trust the task.

## 4. The run

The right column shows the **Timeline**:

- *Thought* — an intermediate assistant message;
- *Tool* — the call, its arguments, its result (file content, stdout/stderr, HTTP rows) and
  duration;
- *Declined* / *Error* — what happened, verbatim, including the tool's own error text;
- *Answer* — the final reply; the badge shows *Completed*, *Cancelled*, *Step limit* or
  *Failed*.

**Stop** cancels the stream, the tool in flight and the loop. The loop is bounded by
**Max steps** (4, 8, 12, 20 or 50; default 12, stored in `agent.max_steps`). When the limit
is reached the run stops and says so — it does not invent a result.

**Recent runs** keeps the session's runs; click one to reopen its timeline.

## 5. Configuring the network tools (Settings → Agent & tools)

| Setting | Effect |
| --- | --- |
| Ask before writes, runs and network calls | global approval gate |
| Network tools | master switch for `web_search`, `github_*` (off by default) |
| Max steps | 1–50 |
| Search endpoint | a SearxNG-compatible URL that accepts `?q=…&format=json` (for example `https://searx.example/search`) |
| GitHub token | personal access token stored in the encrypted store; needed for the GitHub tools |

Both credential fields have a Save button; the token also has a Clear button. Saved secrets
never appear in backups, logs or exports. The page repeats the live availability of every
tool so you can see what your settings actually unlocked.

## 6. What it will not do

- It will not write outside the project folder; path traversal, absolute paths and symlink
  escapes are rejected before the handler runs.
- It will not run a program without the approval gate; runs have a wall-clock limit and can
  be stopped.
- It will not fabricate a tool result. If a tool is unavailable, the step says which gate is
  closed; if a call fails, the error goes back to the model and into the timeline unchanged.
- It will not generate images. `generate_image` is registered so the model can see it, but
  it is permanently unavailable until a real image service is configured.

## 7. Troubleshooting

| Symptom | Cause / fix |
| --- | --- |
| Run button disabled | No model selected, no task text, or the model does not advertise tools |
| “Add an OpenRouter key…” | Save a key in **AI settings** (Connection & models) |
| Every file tool says *No project folder is open* | Open a folder in Code Studio first |
| *Network access is disabled* | Settings → Agent → Network tools |
| *No search endpoint is configured* | Settings → Agent → Search endpoint |
| *No GitHub token is stored* | Settings → Agent → GitHub token |
| *Step limit* badge | The task needed more steps; raise Max steps or narrow the task |
| *Failed* badge | Read the error step: it is the provider's or the tool's own message |
