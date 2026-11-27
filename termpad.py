from datetime import datetime
import pathlib
import warnings
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.screen import ModalScreen
from textual.widgets import (
    Checkbox,
    Footer,
    Header,
    Input,
    Label,
    MarkdownViewer,
    Select,
    Static,
    TabbedContent,
    TabPane,
    TextArea,
)
import textual

# ============================================================================
# Compatibility shim — check textual version at import time
# ============================================================================
# TermPad is tested against textual 8.2.8. The code relies on several internal
# APIs that can change across major versions without a deprecation cycle.
# See SPEC.md §11 for details. Before upgrading textual, re-run the test
# suite under scripts/ to confirm everything still works.
TESTED_TEXTUAL_VERSION = (8, 2, 0)   # minimum tested version
KNOWN_GOOD_TEXTUAL_VERSION = (8, 2, 8)  # version used during development
_textual_ver = tuple(int(p) for p in textual.__version__.split(".")[:3]
                     if p.isdigit())
if _textual_ver:
    if _textual_ver[0] != TESTED_TEXTUAL_VERSION[0]:
        warnings.warn(
            f"TermPad was tested against textual {KNOWN_GOOD_TEXTUAL_VERSION[0]}.x "
            f"but you have textual {textual.__version__} — things may break. "
            f"See SPEC.md §11 for guidance.",
            stacklevel=2,
        )
    elif _textual_ver < TESTED_TEXTUAL_VERSION:
        warnings.warn(
            f"TermPad requires textual >= {TESTED_TEXTUAL_VERSION} "
            f"but you have {textual.__version__}",
            stacklevel=2,
        )

# pyperclip is an optional dependency used to read the system clipboard on paste.
# Install with `pip install pyperclip` (on Linux you also need xclip/xsel/wl-clipboard).
try:
    import pyperclip
    HAS_PYPERCLIP = True
except ImportError:
    pyperclip = None
    HAS_PYPERCLIP = False


# ============================================================================
# Internal-API helpers — all fragile textual internals live here.
# When textual ships a new major version, fix these first.
# ============================================================================
def _remove_app_binding(app: App, key: str) -> bool:
    """Remove an App-level binding from the BindingsMap.

    Uses the internal attribute `app._bindings.key_to_bindings`, which may
    change in textual 9.x. If it changes, find the public equivalent
    (e.g. `app.unbind(...)` if one is added). Returns True if the binding
    was removed, False if the key was not present or the API is unavailable.
    """
    try:
        key_to_bindings = app._bindings.key_to_bindings
    except AttributeError:
        # API changed — return False so the app keeps running (Ctrl+C may not be intercepted)
        return False
    if key in key_to_bindings:
        del key_to_bindings[key]
        try:
            app.refresh_bindings()
        except Exception:
            pass
        return True
    return False


class EditorTextArea(TextArea):
    """TextArea subclass with editor-style key bindings and system-clipboard support.

    - Ctrl+A = select all (overrides TextArea's default `cursor_line_start`)
    - Ctrl+C = copy to system clipboard via pyperclip (OSC 52 fallback)
    - Ctrl+X = cut  + write to system clipboard via pyperclip
    - Ctrl+V = paste from system clipboard (pyperclip) → fallback to local clipboard

    Note: textual uses the OSC 52 escape sequence for `copy_to_clipboard`,
    but some terminals don't support OSC 52 — copy/cut then appears to
    succeed but the system clipboard is never updated, so paste elsewhere
    returns stale content. We use pyperclip as the primary path so copy/cut
    reaches the X11/Wayland clipboard directly.
    """
    BINDINGS = [
        Binding("ctrl+a", "select_all", "Select all", show=False, priority=True),
        Binding("ctrl+c", "copy", "Copy", show=False, priority=True),
        Binding("ctrl+x", "cut", "Cut", show=False, priority=True),
        Binding("ctrl+v", "paste", "Paste", show=False, priority=True),
    ]

    def _system_clipboard_copy(self, text: str) -> None:
        """Write text to the system clipboard (pyperclip) and sync the local clipboard.

        If pyperclip is available → use it (reaches the X11/Wayland clipboard directly).
        Otherwise → fall back to `app.copy_to_clipboard` (OSC 52), as before.
        """
        # Always store in the local clipboard too, so in-app paste still works.
        self.app.copy_to_clipboard(text)
        if HAS_PYPERCLIP:
            try:
                pyperclip.copy(text)
            except Exception:
                pass  # OSC 52 above is the fallback

    def action_copy(self) -> None:
        """Ctrl+C: copy selection → system clipboard (pyperclip) + local clipboard."""
        selected_text = self.selected_text
        if not selected_text:
            return  # No selection — silently do nothing (don't raise SkipAction)
        self._system_clipboard_copy(selected_text)

    def action_cut(self) -> None:
        """Ctrl+X: cut text → system clipboard (pyperclip) + local clipboard."""
        if self.read_only:
            return
        start, end = self.selection
        if start == end:
            # No selection → cut the entire line at the cursor (textual's default behaviour)
            edit_result = self._delete_cursor_line()
        else:
            edit_result = self._delete_via_keyboard(start, end)
        if edit_result is not None:
            self._system_clipboard_copy(edit_result.replaced_text)

    def action_paste(self) -> None:
        """Ctrl+V: paste from system clipboard (pyperclip) → fallback to local clipboard.

        Reads from pyperclip first (so pasting text copied from outside the app works),
        then falls back to the app's local clipboard if pyperclip is unavailable.
        """
        if self.read_only:
            return
        text = ""
        pyperclip_text = None
        if HAS_PYPERCLIP:
            try:
                pyperclip_text = pyperclip.paste()
            except Exception:
                pyperclip_text = None
        if pyperclip_text:
            text = pyperclip_text
        else:
            text = self.app.clipboard
        if not text:
            return
        if result := self._replace_via_keyboard(text, *self.selection):
            self.move_cursor(result.end_location)


class OpenModal(ModalScreen):
  """Open-file dialog (press ESC to cancel)."""

  BINDINGS = [("escape", "cancel", "Cancel")]

  def compose(self) -> ComposeResult:
    yield Label("Open file (enter name or path) [press ESC to cancel]:")
    yield Input(
        placeholder="e.g. note.txt or /home/user/document.txt",
        id="open_input",
    )

  def on_input_submitted(self, event: Input.Submitted) -> None:
    self.dismiss(event.value.strip())

  def action_cancel(self) -> None:
    self.dismiss(None)


class SaveModal(ModalScreen):
  """Save-file dialog (press ESC to cancel)."""

  BINDINGS = [("escape", "cancel", "Cancel")]

  def compose(self) -> ComposeResult:
    yield Label("Save file (enter name or path) [press ESC to cancel]:")
    yield Input(
        placeholder="e.g. note.txt or /home/user/document.txt", id="file_input"
    )

  def on_input_submitted(self, event: Input.Submitted) -> None:
    self.dismiss(event.value.strip())

  def action_cancel(self) -> None:
    self.dismiss(None)


class ConfirmOverwriteModal(ModalScreen):
  """Confirm-overwrite dialog (press ESC to cancel)."""

  BINDINGS = [("escape", "cancel", "Cancel")]

  def compose(self) -> ComposeResult:
    yield Static(
        "This file already exists. Overwrite?\n[ Enter / Y to confirm |"
        " N or ESC to cancel ]"
    )

  def on_key(self, event) -> None:
    if event.key in ("enter", "y", "Y"):
      self.dismiss(True)
    elif event.key in ("n", "N", "escape"):
      self.dismiss(False)

  def action_cancel(self) -> None:
    self.dismiss(False)


class HelpModal(ModalScreen):
  """Help screen (F1) — shows the full keymap [press ESC to close]."""

  BINDINGS = [("escape", "cancel", "Close")]

  HELP_TEXT = """\
# TermPad — Key Bindings

## App Bindings

| Key       | Action                                            |
|-----------|---------------------------------------------------|
| F1        | Show this Help screen                              |
| F5        | Toggle Editor ↔ Preview                            |
| Ctrl+S    | Save file                                          |
| Ctrl+F    | Open file                                          |
| Ctrl+R    | Toggle word wrap                                   |
| Ctrl+L    | Cycle to next syntax-highlight language            |
| Ctrl+Q    | Quit                                               |

## Editor Bindings (TextArea)

| Key              | Action                              |
|------------------|-------------------------------------|
| Ctrl+A           | Select all                          |
| Ctrl+C           | Copy → system clipboard             |
| Ctrl+X           | Cut → system clipboard              |
| Ctrl+V           | Paste from system clipboard         |
| Ctrl+Z / Ctrl+Y  | Undo / Redo                         |
| Home / End       | Move cursor to start/end of line    |
| Ctrl+Left/Right  | Move cursor one word                |
| Shift+Arrow      | Select text                         |
| Ctrl+K           | Delete to end of line               |
| Ctrl+U           | Delete to start of line             |
| Ctrl+W           | Delete word to the left             |
| F6               | Select line                         |
| F7               | Select all (alias of Ctrl+A)        |

## Modal Bindings (popup windows)

| Key     | Action                                              |
|---------|-----------------------------------------------------|
| ESC     | Cancel/close the modal and return to the editor     |
| Enter/Y | Confirm (e.g. confirm overwrite)                    |
| N       | Decline                                             |

## Notes

- copy/cut/paste use pyperclip as the primary path to sync with the system
  clipboard (X11/Wayland). If pyperclip is not installed, the editor falls
  back to OSC 52 (which only works in terminals that support it).
- Install xclip/xsel (X11) or wl-clipboard (Wayland) for cross-application
  copy/cut/paste to work.
- The Preview tab uses MarkdownViewer with TOC disabled so the content gets
  the full terminal width.
- Autosave runs every 60 seconds to /tmp/note_YYYYMMDD_HHMMSS.tmp and is
  cleaned up when the app exits.
"""

  def compose(self) -> ComposeResult:
    yield MarkdownViewer(self.HELP_TEXT, show_table_of_contents=False, id="help_viewer")

  def action_cancel(self) -> None:
    self.dismiss(None)


class TextEditorApp(App):
  CSS = """
    Screen {
        layout: vertical;
    }
    TabbedContent {
        height: 1fr;
    }
    .controls {
        layout: horizontal;
        height: 3;
        align: left middle;
        padding: 0 1;
        background: $surface;
    }
    Select {
        width: 30;
        margin-right: 2;
    }
    Checkbox {
        margin-top: 1;
    }
    TextArea {
        height: 1fr;
    }
    MarkdownViewer {
        height: 1fr;
    }
    ConfirmOverwriteModal, SaveModal, OpenModal {
        align: center middle;
        background: rgba(0,0,0,0.7);
    }
    ConfirmOverwriteModal Static {
        padding: 2 4;
        background: $surface;
        border: thick $primary;
        text-align: center;
    }
    SaveModal, OpenModal {
        height: 11;
        width: 60;
        background: $surface;
        border: thick $primary;
        padding: 1;
    }
    SaveModal Label, OpenModal Label {
        padding: 1;
    }
    SaveModal Input, OpenModal Input {
        margin: 0 1;
    }
    HelpModal {
        align: center middle;
        background: rgba(0,0,0,0.85);
    }
    HelpModal MarkdownViewer {
        width: 90%;
        height: 90%;
        background: $surface;
        border: thick $primary;
        padding: 1 2;
    }
    """

  BINDINGS = [
      ("f1", "show_help", "Help"),                  # F1 opens the Help screen
      ("ctrl+s", "save_file", "Save"),
      ("ctrl+f", "open_file", "Open"),
      ("f5", "toggle_preview", "Preview"),  # F5 toggles Editor ↔ Preview
      ("ctrl+r", "toggle_wrap", "Toggle Wrap"),
      ("ctrl+l", "cycle_lang", "Cycle Lang"),  # Ctrl+L rotates to next language
      ("ctrl+q", "quit", "Quit"),
  ]

  def __init__(self):
    super().__init__()
    now_str = datetime.now().strftime("%Y%m%d_%H%M%S")
    self.temp_file = pathlib.Path(f"/tmp/note_{now_str}.tmp")
    self.last_content = ""

  def compose(self) -> ComposeResult:
    yield Header()
    languages = [
        ("Markdown", "markdown"),
        ("Python", "python"),
        ("JSON", "json"),
        ("CSS", "css"),
        ("JavaScript", "javascript"),
        ("HTML", "html"),
        ("SQL", "sql"),
    ]
    with TabbedContent(initial="editor_tab", id="tabs"):
      with TabPane("Editor", id="editor_tab"):
        with Static(classes="controls"):
          yield Select(languages, value="markdown", id="lang_select")
          yield Checkbox("Word Wrap", value=False, id="wrap_checkbox")
        yield EditorTextArea.code_editor("", language="markdown", id="editor")
      with TabPane("Preview (Markdown)", id="preview_tab"):
        # TOC is disabled because long headings would otherwise make the TOC
        # sidebar consume the entire terminal width, leaving the content pane
        # with height=0 (the preview would appear blank). If you want a TOC
        # later, add a separate "Outline" tab with MarkdownTableOfContents
        # constrained to a fixed width.
        yield MarkdownViewer(id="preview", show_table_of_contents=False)
    yield Footer()

  def on_mount(self) -> None:
    self.editor = self.query_one("#editor", TextArea)
    self.preview = self.query_one("#preview", MarkdownViewer)
    self.editor.focus()
    self.set_interval(60.0, self.auto_save_temp)
    # Remove the App's default `ctrl+c → help_quit` binding so EditorTextArea's
    # priority binding for `ctrl+c → copy` actually receives the event.
    # Done through the helper so an API change in textual 9.x degrades
    # gracefully (Ctrl+C just won't be intercepted, instead of crashing).
    if not _remove_app_binding(self, "ctrl+c"):
      # Helper couldn't find the internal API — try a public alternative
      # if one exists in the future; otherwise leave the default binding.
      pass

  async def on_tabbed_content_tab_activated(
  self, event: TabbedContent.TabActivated
  ) -> None:
    # Two things to be careful of here:
    #   1. event.tab.id is auto-generated as "--content-tab-<pane_id>" in
    #      textual 8.x, so we compare event.pane.id (the id we set on TabPane).
    #   2. Markdown.update() returns an AwaitComplete that must be awaited;
    #      otherwise the new blocks won't have mounted by render time and
    #      the preview will be blank.
    if event.pane.id == "preview_tab":
      await self.preview.document.update(self.editor.text)

  def action_toggle_preview(self) -> None:
    """F5: instantly toggle between the Editor and Preview tabs."""
    tabs = self.query_one("#tabs", TabbedContent)
    if tabs.active == "editor_tab":
      tabs.active = "preview_tab"
      # NOTE: setting tabs.active fires on_tabbed_content_tab_activated,
      # which already calls preview.document.update(...) — no need to call
      # update() again here.
      self.notify("Preview Mode", timeout=1)
    else:
      tabs.active = "editor_tab"
      self.editor.focus()
      self.notify("Editor Mode", timeout=1)



  def on_select_changed(self, event: Select.Changed) -> None:
    if event.select.id == "lang_select" and event.value is not Select.BLANK:
      self.editor.language = str(event.value)

  def on_checkbox_changed(self, event: Checkbox.Changed) -> None:
    if event.checkbox.id == "wrap_checkbox":
      self.editor.soft_wrap = event.value

  def action_toggle_wrap(self) -> None:
    """Ctrl+R: toggle word wrap on/off."""
    checkbox = self.query_one("#wrap_checkbox", Checkbox)
    checkbox.value = not checkbox.value
    self.notify(f"Word Wrap: {'On' if checkbox.value else 'Off'}", timeout=1)

  def action_show_help(self) -> None:
    """F1: open the Help modal showing the full keymap."""
    self.push_screen(HelpModal())

  def action_focus_lang(self) -> None:
    """No longer bound to a key — kept for manual use if needed."""
    self.query_one("#lang_select", Select).focus()
    self.notify("Select highlight language", timeout=1)

  def action_cycle_lang(self) -> None:
    """Ctrl+L: rotate to the next syntax-highlight language.

    Reads the current value from the Select widget, finds the next index
    in the language list, and wraps around at the end.
    """
    lang_select = self.query_one("#lang_select", Select)
    # Language order must match the list in compose().
    languages = ["markdown", "python", "json", "css", "javascript", "html", "sql"]
    current = lang_select.value
    try:
      idx = languages.index(current)
    except ValueError:
      idx = -1
    next_idx = (idx + 1) % len(languages)
    next_lang = languages[next_idx]
    lang_select.value = next_lang  # fires on_select_changed → updates editor.language
    # Pretty labels for the notification.
    lang_labels = {
        "markdown": "Markdown", "python": "Python", "json": "JSON",
        "css": "CSS", "javascript": "JavaScript", "html": "HTML", "sql": "SQL",
    }
    self.notify(f"Language: {lang_labels.get(next_lang, next_lang)}", timeout=1)

  def auto_save_temp(self) -> None:
    current_content = self.editor.text
    if current_content != self.last_content:
      try:
        self.temp_file.write_text(current_content, encoding="utf-8")
        self.last_content = current_content
      except Exception:
        pass

  def action_open_file(self) -> None:
    """Ctrl+F: open a file from disk."""

    def load_path(path_str: str | None) -> None:
      if not path_str:
        return
      target_path = pathlib.Path(path_str)
      if not target_path.is_absolute():
        target_path = pathlib.Path.cwd() / target_path
      try:
        if target_path.exists() and target_path.is_file():
          content = target_path.read_text(encoding="utf-8")
          self.editor.text = content
          self.notify(f"Opened: {target_path.name}", timeout=1)
        else:
          self.notify("File not found", timeout=1)
      except Exception:
        self.notify("Failed to open file", timeout=1)

    self.push_screen(OpenModal(), load_path)

  def action_save_file(self) -> None:
    """Ctrl+S: save the current buffer to disk."""

    def check_path(path_str: str | None) -> None:
      if not path_str:
        return
      target_path = pathlib.Path(path_str)
      if not target_path.is_absolute():
        target_path = pathlib.Path.cwd() / target_path

      if target_path.exists():
        self.push_screen(
            ConfirmOverwriteModal(),
            lambda confirmed: self.execute_save(target_path, confirmed),
        )
      else:
        self.execute_save(target_path, True)

    self.push_screen(SaveModal(), check_path)

  def execute_save(self, target_path: pathlib.Path, confirmed: bool) -> None:
    if not confirmed:
      self.notify("Save cancelled", timeout=1)
      return
    try:
      target_path.write_text(self.editor.text, encoding="utf-8")
      self.notify("Saved", timeout=1)
    except Exception:
      self.notify("Failed to save", timeout=1)

  def on_unmount(self) -> None:
    if self.temp_file.exists():
      try:
        self.temp_file.unlink()
      except Exception:
        pass


if __name__ == "__main__":
  app = TextEditorApp()
  app.run() 
