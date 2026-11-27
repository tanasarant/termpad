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
# Compatibility shim — ตรวจ textual version ตอน import
# ============================================================================
# TermPad ทดสอบกับ textual 8.2.8 โค้ดพึ่งพา API ภายในหลายจุดที่อาจจะเปลี่ยน
# ข้าม major version โดยไม่มี deprecation warning ดูรายละเอียดใน SPEC.md §11
# เมื่ออัปเกรด textual ให้รัน test suite ใน scripts/ ก่อน เพื่อยืนยันว่ายังทำงานได้
TESTED_TEXTUAL_VERSION = (8, 2, 0)   # เวอร์ชั่นต่ำสุดที่ทดสอบ
KNOWN_GOOD_TEXTUAL_VERSION = (8, 2, 8)  # เวอร์ชั่นที่ใช้พัฒนา
_textual_ver = tuple(int(p) for p in textual.__version__.split(".")[:3]
                     if p.isdigit())
if _textual_ver:
    if _textual_ver[0] != TESTED_TEXTUAL_VERSION[0]:
        warnings.warn(
            f"TermPad ทดสอบกับ textual {KNOWN_GOOD_TEXTUAL_VERSION[0]}.x "
            f"แต่คุณใช้ textual {textual.__version__} — อาจจะพังได้ "
            f"ดู SPEC.md §11 สำหรับวิธีตรวจสอบ",
            stacklevel=2,
        )
    elif _textual_ver < TESTED_TEXTUAL_VERSION:
        warnings.warn(
            f"TermPad ต้องการ textual >= {TESTED_TEXTUAL_VERSION} "
            f"แต่คุณใช้ {textual.__version__}",
            stacklevel=2,
        )

# pyperclip เป็น optional dependency สำหรับอ่าน system clipboard ตอน paste
# ติดตั้งด้วย `pip install pyperclip` (บน Linux ต้องมี xclip/xsel/wl-clipboard ด้วย)
try:
    import pyperclip
    HAS_PYPERCLIP = True
except ImportError:
    pyperclip = None
    HAS_PYPERCLIP = False


# ============================================================================
# Internal-API helpers — รวมจุดที่พึ่งพา internal API ของ textual ไว้ที่เดียว
# เวลา textual update ใหม่ แก้ที่นี่เป็นหลัก
# ============================================================================
def _remove_app_binding(app: App, key: str) -> bool:
    """ลบ App-level binding ออกจาก BindingsMap

    ใช้ internal attribute `app._bindings.key_to_bindings` ซึ่งอาจจะเปลี่ยนใน
    textual 9.x ถ้าเปลี่ยน ให้หา API สาธารณะแทน (เช่น `app.unbind(...)` ถ้ามี)
    คืน True ถ้าลบสำเร็จ False ถ้าไม่มี key นั้นอยู่
    """
    try:
        key_to_bindings = app._bindings.key_to_bindings
    except AttributeError:
        # API เปลี่ยน — คืน False ให้ App ทำงานต่อได้ (แค่ Ctrl+C อาจจะไม่ทำงาน)
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
    """TextArea ที่ปรับ key bindings และ clipboard ให้เป็นมาตรฐาน text editor:

    - Ctrl+A = เลือกข้อความทั้งหมด (select_all) — override default `cursor_line_start`
    - Ctrl+C = copy ไปยัง system clipboard ผ่าน pyperclip (OSC 52 เป็น fallback)
    - Ctrl+X = cut  + เขียนไป system clipboard ผ่าน pyperclip
    - Ctrl+V = paste จาก system clipboard (pyperclip) → fallback local clipboard

    หมายเหตุ: textual ใช้ OSC 52 escape sequence สำหรับ copy_to_clipboard
    แต่ terminal บางตัวไม่รองรับ OSC 52 → copy/cut ดูเหมือนสำเร็จ แต่ข้อมูลไม่ไปถึง
    system clipboard จริง → paste ที่อื่นไม่ได้ ใช้ pyperclip เป็นทางเลือกหลัก
    เพื่อให้ copy/cut ไปถึง X11/Wayland clipboard โดยตรง
    """
    BINDINGS = [
        Binding("ctrl+a", "select_all", "Select all", show=False, priority=True),
        Binding("ctrl+c", "copy", "Copy", show=False, priority=True),
        Binding("ctrl+x", "cut", "Cut", show=False, priority=True),
        Binding("ctrl+v", "paste", "Paste", show=False, priority=True),
    ]

    def _system_clipboard_copy(self, text: str) -> None:
        """เขียน text ไป system clipboard (pyperclip) + sync local clipboard

        ถ้า pyperclip ทำงานได้ → ใช้ pyperclip (เข้าถึง X11/Wayland clipboard จริง)
        ถ้าไม่ได้ → fallback เป็น app.copy_to_clipboard (OSC 52) เหมือนเดิม
        """
        # เก็บใน local clipboard เสมอ เผื่อ paste ภายในแอป
        self.app.copy_to_clipboard(text)
        if HAS_PYPERCLIP:
            try:
                pyperclip.copy(text)
            except Exception:
                pass  # ใช้ OSC 52 ที่เก็บไว้ข้างบนเป็น fallback

    def action_copy(self) -> None:
        """Ctrl+C: copy selection → system clipboard (pyperclip) + local clipboard"""
        selected_text = self.selected_text
        if not selected_text:
            return  # ไม่มี selection → เงียบ ๆ ไม่ต้อง raise SkipAction
        self._system_clipboard_copy(selected_text)

    def action_cut(self) -> None:
        """Ctrl+X: cut text → system clipboard (pyperclip) + local clipboard"""
        if self.read_only:
            return
        start, end = self.selection
        if start == end:
            # ไม่มี selection → ตัดทั้งบรรทัดที่ cursor อยู่ (default behavior ของ textual)
            edit_result = self._delete_cursor_line()
        else:
            edit_result = self._delete_via_keyboard(start, end)
        if edit_result is not None:
            self._system_clipboard_copy(edit_result.replaced_text)

    def action_paste(self) -> None:
        """Ctrl+V: paste จาก system clipboard (pyperclip) → fallback local clipboard

        อ่านจาก pyperclip ก่อน (เพื่อให้ paste ข้อความที่ copy จากภายนอกแอปได้)
        ถ้า pyperclip ไม่มี/fail → ใช้ local clipboard ของแอป
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
  """หน้าต่างเปิดไฟล์ (กด ESC เพื่อยกเลิก)"""

  BINDINGS = [("escape", "cancel", "Cancel")]

  def compose(self) -> ComposeResult:
    yield Label("เปิดไฟล์ (ระบุชื่อหรือ Path) [กด ESC เพื่อยกเลิก]:")
    yield Input(
        placeholder="เช่น note.txt หรือ /home/user/document.txt",
        id="open_input",
    )

  def on_input_submitted(self, event: Input.Submitted) -> None:
    self.dismiss(event.value.strip())

  def action_cancel(self) -> None:
    self.dismiss(None)


class SaveModal(ModalScreen):
  """หน้าต่างบันทึกไฟล์ (กด ESC เพื่อยกเลิก)"""

  BINDINGS = [("escape", "cancel", "Cancel")]

  def compose(self) -> ComposeResult:
    yield Label("บันทึกไฟล์ (ระบุชื่อหรือ Path) [กด ESC เพื่อยกเลิก]:")
    yield Input(
        placeholder="เช่น note.txt หรือ /home/user/document.txt", id="file_input"
    )

  def on_input_submitted(self, event: Input.Submitted) -> None:
    self.dismiss(event.value.strip())

  def action_cancel(self) -> None:
    self.dismiss(None)


class ConfirmOverwriteModal(ModalScreen):
  """หน้าต่างยืนยันการเขียนทับไฟล์ (กด ESC เพื่อยกเลิก)"""

  BINDINGS = [("escape", "cancel", "Cancel")]

  def compose(self) -> ComposeResult:
    yield Static(
        "ไฟล์นี้มีอยู่แล้ว ต้องการเขียนทับหรือไม่?\n[ กด Enter / Y เพื่อยืนยัน |"
        " N หรือ ESC เพื่อยกเลิก ]"
    )

  def on_key(self, event) -> None:
    if event.key in ("enter", "y", "Y"):
      self.dismiss(True)
    elif event.key in ("n", "N", "escape"):
      self.dismiss(False)

  def action_cancel(self) -> None:
    self.dismiss(False)


class HelpModal(ModalScreen):
  """หน้าต่าง Help (F1) — แสดง key bindings ทั้งหมด [กด ESC เพื่อปิด]"""

  BINDINGS = [("escape", "cancel", "Close")]

  HELP_TEXT = """\
# TermPad — Key Bindings

## คำสั่งแอป (App Bindings)

| คีย์       | ฟังก์ชัน                                            |
|-----------|----------------------------------------------------|
| F1        | แสดงหน้าต่าง Help (นี้)                              |
| F5        | สลับ Editor ↔ Preview                              |
| Ctrl+S    | บันทึกไฟล์                                         |
| Ctrl+F    | เปิดไฟล์                                            |
| Ctrl+R    | สลับเปิด/ปิด Word Wrap                            |
| Ctrl+L    | สลับไปยังภาษาไฮไลต์ถัดไปทันที (Markdown→Python→...) |
| Ctrl+Q    | ออกจากโปรแกรม                                     |

## คำสั่ง Editor (TextArea Bindings)

| คีย์             | ฟังก์ชัน                              |
|-----------------|--------------------------------------|
| Ctrl+A          | เลือกข้อความทั้งหมด (Select All)      |
| Ctrl+C          | คัดลอก → system clipboard            |
| Ctrl+X          | ตัดข้อความ → system clipboard         |
| Ctrl+V          | วางจาก system clipboard              |
| Ctrl+Z / Ctrl+Y | Undo / Redo                          |
| Home / End      | ย้าย cursor ไปต้น/ท้ายบรรทัด         |
| Ctrl+Left/Right | ย้าย cursor ทีละคำ                   |
| Shift+Arrow     | เลือกข้อความ                          |
| Ctrl+K          | ลบถึงท้ายบรรทัด                      |
| Ctrl+U          | ลบถึงต้นบรรทัด                       |
| Ctrl+W          | ลบคำทางซ้าย                          |
| F6              | เลือกทั้งบรรทัด                       |
| F7              | เลือกทั้งหมด (เหมือน Ctrl+A)         |

## คำสั่ง Modal (หน้าต่าง popup)

| คีย์    | ฟังก์ชัน                                            |
|--------|----------------------------------------------------|
| ESC    | ยกเลิก/ปิดหน้าต่าง Modal กลับสู่ Editor           |
| Enter/Y| ยืนยัน (เช่นยืนยันเขียนทับไฟล์)                    |
| N      | ไม่ยืนยัน                                          |

## หมายเหตุ

- copy/cut/paste ใช้ pyperclip เป็นทางเลือกหลักเพื่อ sync กับ system clipboard
  (X11/Wayland) ถ้าไม่ได้ติดตั้ง pyperclip จะ fallback เป็น OSC 52 ของ terminal
- ต้องติดตั้ง xclip/xsel (X11) หรือ wl-clipboard (Wayland) เพื่อให้ copy/cut/paste
  ข้ามแอปทำงานได้
- Preview ใช้ MarkdownViewer ที่ปิด TOC เพื่อให้ content ใช้เต็มจอ
- Autosave ทำงานทุก 60 วินาที เก็บไว้ที่ /tmp/note_YYYYMMDD_HHMMSS.tmp
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
      ("f1", "show_help", "Help"),                  # FIX: เพิ่ม F1 สำหรับ Help
      ("ctrl+s", "save_file", "Save"),
      ("ctrl+f", "open_file", "Open"),
      ("f5", "toggle_preview", "Preview"),  # FIX: ย้ายจาก Ctrl+M → F5 เพื่อคืน Ctrl+M ให้เป็น newline
      ("ctrl+r", "toggle_wrap", "Toggle Wrap"),
      ("ctrl+l", "cycle_lang", "Cycle Lang"),  # FIX: เปลี่ยนจาก focus_lang → cycle_lang (สลับภาษาถัดไปทันที)
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
          yield Checkbox("ตัดคำ (Word Wrap)", value=False, id="wrap_checkbox")
        yield EditorTextArea.code_editor("", language="markdown", id="editor")
      with TabPane("Preview (Markdown)", id="preview_tab"):
        # FIX #3: ปิด TOC เพราะ heading ที่ยาวจะทำให้ TOC ขอความกว้างเกินจอ
        #   จน content ด้านขวาเหลือ height=0 (มองไม่เห็นเลย = เห็นเป็น outline ว่าง)
        #   ถ้าต้องการ TOC ภายหลัง ควรทำเป็นแท็บ "Outline" แยกต่างหาก
        yield MarkdownViewer(id="preview", show_table_of_contents=False)
    yield Footer()

  def on_mount(self) -> None:
    self.editor = self.query_one("#editor", TextArea)
    self.preview = self.query_one("#preview", MarkdownViewer)
    self.editor.focus()
    self.set_interval(60.0, self.auto_save_temp)
    # FIX: ลบ App's default `ctrl+c → help_quit` ออก เพื่อให้ EditorTextArea
    #   สามารถใช้ Ctrl+C เป็น copy ได้ (priority binding ของ widget จะได้รับ event)
    # ผ่าน helper ที่รองรับการเปลี่ยน API ของ textual (ดู _remove_app_binding)
    if not _remove_app_binding(self, "ctrl+c"):
      # ถ้า helper ใช้ไม่ได้ (API เปลี่ยน) → ลองวิธีสาธารณะถ้ามี ไม่งั้นข้ามไป
      # ในกรณีนี้ Ctrl+C อาจจะเป็น help_quit อยู่ แต่แอปยังทำงานได้
      pass

  async def on_tabbed_content_tab_activated(
  self, event: TabbedContent.TabActivated
  ) -> None:
    # FIX #1: event.tab.id ถูก generate เป็น "--content-tab-<pane_id>"
    #   ดังนั้นต้องใช้ event.pane.id เพื่ออ้างถึง id ที่เราตั้งใน TabPane
    # FIX #2: Markdown.update() คืน AwaitComplete ต้อง await เพื่อรอ mount
    if event.pane.id == "preview_tab":
      await self.preview.document.update(self.editor.text)

  def action_toggle_preview(self) -> None:
    """Ctrl+M: สลับระหว่างแท็บ Editor และ Preview ทันที"""
    tabs = self.query_one("#tabs", TabbedContent)
    if tabs.active == "editor_tab":
      tabs.active = "preview_tab"
      # NOTE: เมื่อ set tabs.active จะ trigger on_tabbed_content_tab_activated
      #   ซึ่งจะอัปเดต preview ให้แล้ว จึงไม่ต้องเรียก update() ซ้ำที่นี่
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
    """Ctrl+R: สลับเปิด/ปิด ตัดคำ"""
    checkbox = self.query_one("#wrap_checkbox", Checkbox)
    checkbox.value = not checkbox.value
    self.notify(f"Word Wrap: {'On' if checkbox.value else 'Off'}", timeout=1)

  def action_show_help(self) -> None:
    """F1: เปิดหน้าต่าง Help แสดง key bindings ทั้งหมด"""
    self.push_screen(HelpModal())

  def action_focus_lang(self) -> None:
    """(ไม่ผูกกับ keybinding แล้ว — เก็บไว้ให้เรียกเองถ้าต้องการ)"""
    self.query_one("#lang_select", Select).focus()
    self.notify("เลือกภาษาไฮไลต์", timeout=1)

  def action_cycle_lang(self) -> None:
    """Ctrl+L: สลับไปยังภาษาไฮไลต์ถัดไปทันที (toggle/cycle)

    อ่านค่าปัจจุบันจาก Select แล้วหา index ถัดไปใน list ของภาษา
    เมื่อถึงภาษาสุดท้ายจะวนกลับไปที่ภาษาแรก
    """
    lang_select = self.query_one("#lang_select", Select)
    # ลำดับภาษาตามที่ตั้งไว้ใน compose()
    languages = ["markdown", "python", "json", "css", "javascript", "html", "sql"]
    current = lang_select.value
    try:
      idx = languages.index(current)
    except ValueError:
      idx = -1
    next_idx = (idx + 1) % len(languages)
    next_lang = languages[next_idx]
    lang_select.value = next_lang  # trigger on_select_changed → เปลี่ยน editor.language
    # ชื่อภาษาสำหรับแสดงใน notification
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
    """Ctrl+F: เปิดไฟล์จากเครื่อง"""

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
          self.notify(f"เปิดไฟล์สำเร็จ: {target_path.name}", timeout=1)
        else:
          self.notify("ไม่พบไฟล์ที่ระบุ", timeout=1)
      except Exception as e:
        self.notify("เปิดไฟล์ล้มเหลว", timeout=1)

    self.push_screen(OpenModal(), load_path)

  def action_save_file(self) -> None:
    """Ctrl+S: บันทึกไฟล์"""

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
      self.notify("ยกเลิกการบันทึก", timeout=1)
      return
    try:
      target_path.write_text(self.editor.text, encoding="utf-8")
      self.notify("บันทึกเสร็จสิ้น", timeout=1)
    except Exception as e:
      self.notify("บันทึกล้มเหลว", timeout=1)

  def on_unmount(self) -> None:
    if self.temp_file.exists():
      try:
        self.temp_file.unlink()
      except Exception:
        pass


if __name__ == "__main__":
  app = TextEditorApp()
  app.run() 
