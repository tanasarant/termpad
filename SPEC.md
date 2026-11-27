TermPad — Technical Specification (SPEC.md)

    Single-file Markdown-capable terminal text editor built on Python + Textual.

This document describes the architecture, components, key bindings, data flow, and integration surface of TermPad. It is intended as the authoritative reference for anyone reading, extending, or embedding the codebase.
1. Overview

TermPad is a TUI (Terminal User Interface) text editor that lets the user write plain text or Markdown and instantly preview the rendered Markdown output without leaving the terminal. The editor runs entirely in the terminal — no browser, no external viewer, no GUI toolkit.

The whole application is contained in a single Python file (termpad.py) so that it can be copied into any project, dropped onto a server, or run as a standalone script.

Design goals:

    Keyboard-first — every action is reachable through a documented key binding.
    System-clipboard aware — copy/cut/paste should sync with the OS clipboard, not an internal buffer.
    Embeddable — the editor widget (EditorTextArea) is a self-contained class that can be reused in other Textual apps (e.g. LLM wrappers, chat clients, note apps).
    No external assets — no themes, no configs, no plugins. Just one Python file and two pip dependencies.

2. Requirements
Runtime

    Python: 3.10 or newer (uses match-friendly typing and str | None union syntax)
    OS: any platform Textual supports (Linux, macOS, Windows); clipboard features work best on Linux with X11/Wayland

Python packages
Package
	
Min version
	
Required?
	
Purpose
textual	>=8.0.0	required	TUI framework (TextArea, MarkdownViewer, App, …)
pyperclip	>=1.8.0	optional	System clipboard integration (X11/Wayland/Win/Mac)
System clipboard utilities (Linux only)

One of the following is required for cross-application copy/paste via pyperclip:

    xclip (X11) — sudo apt-get install xclip
    xsel (X11, alternative) — sudo apt-get install xsel
    wl-clipboard (Wayland) — sudo apt-get install wl-clipboard

If none are installed, TermPad still runs but copy/cut only updates the in-app clipboard and the OSC 52 escape sequence (which works only on supporting terminals).
3. Architecture
3.1 Module layout
text

termpad.py
├── (module imports + pyperclip availability flag)
├── class EditorTextArea(TextArea)        ← reusable editor widget
├── class OpenModal(ModalScreen)          ← "Open file" dialog
├── class SaveModal(ModalScreen)          ← "Save file" dialog
├── class ConfirmOverwriteModal(ModalScreen)
├── class HelpModal(ModalScreen)          ← F1 Help screen
└── class TextEditorApp(App)              ← main application

3.2 Component responsibilities
Class
	
Responsibility
EditorTextArea	Subclass of TextArea providing system-clipboard copy/cut/paste and the right key bindings. Reusable outside the app.
OpenModal	Modal screen that prompts the user for a path, returns the string (or None on cancel).
SaveModal	Same pattern as OpenModal but for save targets.
ConfirmOverwriteModal	Yes/No confirmation when a save target already exists. Returns a bool.
HelpModal	Modal screen rendering the full keymap via MarkdownViewer. Closes on ESC.
TextEditorApp	Composes the layout (Header + Tabs + Footer), wires bindings, drives file I/O, schedules autosave, and cleans up the temp file on exit.
3.3 Layout
text

┌─────────────────────────────────────────────────────────────────┐
│ Header                                                          │
├─────────────────────────────────────────────────────────────────┤
│ [Editor] [Preview (Markdown)]   ← TabbedContent                 |
│ ┌─────────────────────────────────────────────────────────────┐ │
│ │ Select(language)  Checkbox(word wrap)    ← .controls bar   │ │
│ ├─────────────────────────────────────────────────────────────┤ │
│ │                                                             │ │
│ │   EditorTextArea             (Editor tab)                   │ │
│ │     or                                                     │ │
│ │   MarkdownViewer            (Preview tab, TOC disabled)    │ │
│ │                                                             │ │
│ └─────────────────────────────────────────────────────────────┘ │
├─────────────────────────────────────────────────────────────────┤
│ Footer (binding hints)                                          │
└─────────────────────────────────────────────────────────────────┘

4. Key Bindings
4.1 App-level bindings (defined in TextEditorApp.BINDINGS)
Key
	
Action
	
Description
F1	show_help	Push HelpModal (renders the keymap)
F5	toggle_preview	Toggle active tab between editor_tab and preview_tab
Ctrl+S	save_file	Push SaveModal; on submit, save (with overwrite confirm)
Ctrl+F	open_file	Push OpenModal; on submit, load file into editor
Ctrl+R	toggle_wrap	Flip editor.soft_wrap and sync the checkbox
Ctrl+L	cycle_lang	Rotate Select.value to the next language; updates editor.language
Ctrl+Q	quit	Quit the app

    Note: The default App.BINDINGS includes Ctrl+C → help_quit. TermPad removes this in on_mount so that Ctrl+C reaches EditorTextArea and runs action_copy. See §5.1.

4.2 Editor-level bindings (defined in EditorTextArea.BINDINGS)

All bindings below use priority=True so they take precedence over the App-level defaults when the editor is focused.
Key
	
Action
	
Description
Ctrl+A	select_all	Select the entire document (overrides TextArea's default cursor_line_start)
Ctrl+C	copy	Copy selection → system clipboard (pyperclip) + local clipboard
Ctrl+X	cut	Cut selection (or current line if no selection) → system + local clipboard
Ctrl+V	paste	Paste from system clipboard; falls back to local clipboard if pyperclip is unavailable

The following bindings are inherited unchanged from TextArea.BINDINGS:
Key
	
Action
Home / Ctrl+E	cursor_line_start / cursor_line_end
Ctrl+Left/Right	cursor_word_left / cursor_word_right
Shift+Arrow	Cursor movement with selection
Ctrl+Z / Ctrl+Y	undo / redo
Ctrl+W / Ctrl+Backspace	delete_word_left
Ctrl+K	delete_to_end_of_line_or_delete_line
Ctrl+U	delete_to_start_of_line
F6	select_line
F7	select_all (alias of Ctrl+A)
4.3 Modal bindings
Key
	
Action
	
Available in
ESC	cancel	All modals (OpenModal, SaveModal, ConfirmOverwriteModal, HelpModal)
Enter	submit	OpenModal, SaveModal (via Input.Submitted)
Enter/Y	confirm yes	ConfirmOverwriteModal (via on_key)
N	confirm no	ConfirmOverwriteModal
5. Behaviour specification
5.1 System clipboard integration

Problem solved: Textual's built-in TextArea.action_copy calls app.copy_to_clipboard(text), which emits the OSC 52 escape sequence (ESC ] 52 ; c ; <base64> BEL). Many terminal emulators silently ignore OSC 52 (for security reasons), so copy/cut appears to succeed but the system clipboard is never updated — and Ctrl+V then pastes stale content.

Solution in TermPad: EditorTextArea overrides action_copy, action_cut, and action_paste:
python

def _system_clipboard_copy(self, text: str) -> None:
    self.app.copy_to_clipboard(text)        # local clipboard + OSC 52
    if HAS_PYPERCLIP:
        try:
            pyperclip.copy(text)             # writes to X11 / Wayland clipboard
        except Exception:
            pass                             # OSC 52 already wrote above

def action_paste(self) -> None:
    # 1. Try pyperclip first (cross-application paste)
    # 2. Fall back to self.app.clipboard (in-app copy/cut)
    ...

Removal of App's Ctrl+C binding: in on_mount:
python

if "ctrl+c" in self._bindings.key_to_bindings:
    del self._bindings.key_to_bindings["ctrl+c"]
    self.refresh_bindings()

This prevents the App-level Ctrl+C → help_quit default from swallowing the key before the focused EditorTextArea sees it.
5.2 Preview tab activation

The Preview tab uses a MarkdownViewer with show_table_of_contents=False. Tab switching is handled by:
python

async def on_tabbed_content_tab_activated(
    self, event: TabbedContent.TabActivated
) -> None:
    if event.pane.id == "preview_tab":
        await self.preview.document.update(self.editor.text)

Two important details:

    The check uses event.pane.id (the TabPane id the user set), not event.tab.id (which Textual auto-generates as --content-tab-<pane_id>).
    Markdown.update() returns an AwaitComplete that must be awaited for the new content blocks to mount before the next render cycle — otherwise the preview shows stale content.

5.3 Table of Contents disabled

MarkdownViewer opens its TOC sidebar by default. The sidebar docks left and requests a width equal to the longest heading in the document. With long Markdown headings (e.g. this very spec), the sidebar consumes the entire terminal width, leaving the content pane with height=0. Setting show_table_of_contents=False removes the sidebar and gives the content the full width.
5.4 Language cycling (Ctrl+L)
python

def action_cycle_lang(self) -> None:
    languages = ["markdown", "python", "json", "css", "javascript", "html", "sql"]
    current = self.query_one("#lang_select", Select).value
    idx = languages.index(current) if current in languages else -1
    next_lang = languages[(idx + 1) % len(languages)]
    self.query_one("#lang_select", Select).value = next_lang

Setting Select.value fires on_select_changed, which sets editor.language — so a single keypress rotates both the dropdown and the editor's syntax highlighter.
5.5 Autosave

    Interval: 60 seconds (set via self.set_interval(60.0, self.auto_save_temp)).
    File: /tmp/note_YYYYMMDD_HHMMSS.tmp (timestamp frozen at app start, so each session uses one stable path).
    Content-change check: only writes if self.editor.text != self.last_content.
    Cleanup: on on_unmount, the temp file is unlink()-ed if it still exists.

5.6 File operations
Action
	
Modal flow
Open (Ctrl+F)	Push OpenModal → on submit, resolve relative paths against Path.cwd() → read UTF-8 → set editor.text.
Save (Ctrl+S)	Push SaveModal → on submit, resolve path → if exists, push ConfirmOverwriteModal → on confirm, write UTF-8.
Cancel	ESC in any modal calls self.dismiss(None) (or False for confirmation) and the underlying action is silently aborted.
6. CSS

All styling lives inline in TextEditorApp.CSS. Notable rules:

    .controls — horizontal bar above the editor, height 3, $surface background
    TextArea, MarkdownViewer — both height: 1fr so they fill remaining vertical space
    HelpModal MarkdownViewer — 90% width/height with thick $primary border, on a rgba(0,0,0,0.85) overlay
    OpenModal, SaveModal — fixed 60×11 centered dialog with thick border

7. Integration
7.1 Embedding EditorTextArea in another Textual app

EditorTextArea is intentionally self-contained — it only depends on textual.widgets.TextArea and the optional pyperclip module. To embed:
python

from termpad import EditorTextArea
from textual.app import App, ComposeResult

class MyLLMClient(App):
    def compose(self) -> ComposeResult:
        yield EditorTextArea.code_editor(
            "Type a prompt here…",
            language="markdown",
            id="prompt",
        )

    def on_mount(self) -> None:
        # Critical: remove App's default Ctrl+C so it doesn't swallow copy
        if "ctrl+c" in self._bindings.key_to_bindings:
            del self._bindings.key_to_bindings["ctrl+c"]
            self.refresh_bindings()

7.2 Use cases

TermPad's editor widget is a good fit for:

    LLM wrappers / chat TUIs — let the user compose a Markdown prompt with full editing and clipboard, then submit it to the model on Enter (or a custom binding).
    Note-taking apps — pair EditorTextArea with a file list widget to build a Markdown-first knowledge base.
    Journaling / log tools — EditorTextArea plus a date-stamped autosave gives you a frictionless daily journal.
    Configuration editors — embed with a fixed language (e.g. language="json") to edit config files with syntax highlighting and clipboard support.
    Code snippet tools — collect snippets in a TextArea, with Ctrl+L cycling between languages.

7.3 Customisation hooks
Want to change…
	
Where to edit
Key bindings	EditorTextArea.BINDINGS and TextEditorApp.BINDINGS
Languages offered	compose() (the languages list) and action_cycle_lang()
Autosave interval	self.set_interval(60.0, ...) in on_mount
Temp-file location	self.temp_file in __init__
Help text	HelpModal.HELP_TEXT
Modal styling	TextEditorApp.CSS
8. Limitations & known quirks

    OSC 52 fallback is terminal-dependent. If pyperclip is not available and the terminal does not support OSC 52 (or has it disabled), copy/cut will only update the in-app clipboard. The user can still paste with Ctrl+V within TermPad, but cross-application paste will not work.
    SSH without X11 forwarding. pyperclip cannot reach a desktop clipboard over plain SSH. Run with ssh -X (X11 forwarding) or use a terminal that supports OSC 52.
    No multi-file tabs. TermPad is intentionally single-document. For multi-file editing, embed EditorTextArea and add your own tab management.
    TOC disabled by default. Long headings force the TOC sidebar to consume the whole terminal; we trade the outline view for full-width content. A future enhancement could add a separate "Outline" tab using MarkdownTableOfContents with a fixed width.
    No search/replace yet. TextArea itself does not ship a search widget; a future version could add Ctrl+F for in-buffer search (which would conflict with our file-open binding — we'd need to remap).

9. Testing

End-to-end tests are written with App.run_test() (Textual's Pilot API) and live under scripts/test_*.py. They cover:

    Ctrl+A selects all text
    Ctrl+C updates both local clipboard and (when available) pyperclip's system clipboard
    Ctrl+V pastes from system clipboard, falling back to local clipboard
    Ctrl+X cuts, reduces document length by exactly len(selected_text), and updates clipboard
    After Ctrl+X, a subsequent Ctrl+V pastes the cut text (clipboard is updated, not stale)
    Ctrl+L cycles editor.language (markdown → python → json → …)
    F5 switches the active tab to preview_tab
    F1 opens HelpModal and ESC closes it
    Preview pane renders markdown blocks (count > 0) after switching tabs

Run them with:
bash

python scripts/test_final2.py    # clipboard + select-all
python scripts/test_help.py      # F1 Help screen

10. Versioning & changelog

This is v0.1.0 — first public release.

Planned for v0.2.0:

    In-buffer search & replace
    Outline tab using MarkdownTableOfContents with fixed width
    Optional "open recent files" menu
    Configuration file (~/.config/termpad/config.toml) for key remapping

11. Compatibility Notes (important for maintenance)

TermPad is tested against textual 8.2.8. The codebase relies on several
internal APIs of Textual that may change across major releases without a
deprecation cycle. This section documents every fragile touchpoint so that
when you upgrade Textual you know exactly where to look.
11.1 Runtime version check

At the top of termpad.py we do:
python

import textual
TESTED_TEXTUAL_VERSION = (8, 2, 0)
_textual_ver = tuple(int(p) for p in textual.__version__.split(".")[:3])
if _textual_ver[0] != TESTED_TEXTUAL_VERSION[0]:
    warnings.warn(...)

This emits a RuntimeWarning if the installed Textual major version differs
from what TermPad was tested with. The app still runs — the warning is
informational, not blocking.
11.2 Fragile API touchpoints
#
	
Where
	
Internal API used
	
Risk if Textual changes it
	
Mitigation in TermPad
1	_remove_app_binding(app, key)	app._bindings.key_to_bindings (dict mutation)	BindingsMap could change its internal storage or remove key_to_bindings attribute	Helper wrapped in try/except AttributeError; returns False on failure so the app keeps running (Ctrl+C just won't be intercepted)
2	on_tabbed_content_tab_activated	event.pane.id	Pre-8.x Textual used event.tab.id directly; 8.x auto-generates --content-tab-<pane_id> for event.tab.id. Could change again.	Always use event.pane.id; if event.pane is removed, fall back to event.tabbed_content.active == "preview_tab"
3	EditorTextArea.action_paste	self._replace_via_keyboard(text, *self.selection)	_replace_via_keyboard is a private helper of TextArea. Public API may appear in future.	Currently the only way to insert text respecting selection; if removed, fall back to self.insert(text, self.cursor_location) (less featureful — won't replace selection)
4	EditorTextArea.action_cut	self._delete_via_keyboard(start, end) and self._delete_cursor_line()	Same as #3 — private helpers of TextArea	If removed, implement cut manually: read selected_text, self.delete(start, end), then write to clipboard
5	Binding("ctrl+c", ..., priority=True)	The priority kwarg semantics	The behaviour of priority=True could change (e.g. be replaced by an override=True flag, or by removing App-level bindings entirely)	If priority is removed, fall back to subclassing App.BINDINGS = [] directly and not relying on widget priority
6	MarkdownViewer(id="preview", show_table_of_contents=False)	show_table_of_contents reactive + MarkdownTableOfContents widget	Could be renamed or refactored	If renamed, look for the new equivalent in MarkdownViewer.__init__ signature; if removed entirely, the TOC will just appear again (annoying but not breaking)
7	MarkdownViewer.document property	Returns the inner Markdown widget via self.query_one(Markdown)	Property could be removed in favour of a different composition model	If removed, fall back to self.query_one("#preview Markdown") or self.preview.query_one(Markdown)
8	markdown_viewer.document.update(text)	Returns AwaitComplete, must be awaited	The return type could change to a plain coroutine or to None	Currently await works for both AwaitComplete and real coroutines; if it becomes None, just call without await
11.3 Upgrade checklist (when Textual 9.x ships)

Before upgrading requirements.txt to allow textual>=9.0.0:

    Read Textual's CHANGELOG.md for the 9.0 release — look specifically for BREAKING CHANGES and any items mentioning BindingsMap, TextArea, MarkdownViewer, TabbedContent, or Binding.
    Bump the version in a feature branch: pip install textual==9.0.0.
    Run python scripts/test_final2.py and python scripts/test_help.py. If any test fails:
        If Ctrl+C no longer copies → check touchpoint #1 and #5.
        If Ctrl+V pastes wrong text → check touchpoint #3.
        If Ctrl+X doesn't delete → check touchpoint #4.
        If Preview tab is blank → check touchpoint #2 and #7.
        If Preview shows TOC sidebar → check touchpoint #6.
    Update TESTED_TEXTUAL_VERSION in termpad.py and the pin in requirements.txt.
    Re-run the full test suite, then manually smoke-test the app for 5 minutes (open, save, copy/cut/paste across apps, switch languages, toggle preview).

11.4 Why we don't just use the public API

Some operations genuinely have no public API in Textual 8.x:

    Removing an App-level binding — there's no app.unbind(...). The only ways are (a) override App.BINDINGS entirely (loses Ctrl+Q too), or (b) dig into _bindings.key_to_bindings.
    Replacing the current selection with new text — TextArea.insert(text) inserts at the cursor; to actually replace a non-empty selection, you need _replace_via_keyboard.
    Cutting the current line when there's no selection — _delete_cursor_line() is the private helper that mirrors the default Ctrl+X behaviour.

We've minimised the surface area (only 8 touchpoints, all wrapped in helpers or try/except), but a perfect zero-internal-API version would lose features. Trade-off documented.
11.5 Lock-file strategy for end users

For users who just want TermPad to keep working, the simplest insurance is a lockfile:
bash

# create a venv and pin exact versions
python -m venv .venv
source .venv/bin/activate
pip install textual==8.2.8 pyperclip==1.9.0
pip freeze > requirements.lock

Then pip install -r requirements.lock will reproduce the exact tested environment regardless of what Textual ships next.
