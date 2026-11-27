TermPad

    A terminal-based text editor with live Markdown preview, written in Python with Textual.

TermPad is a single-file TUI editor designed for quickly writing Markdown (or code) in the terminal and instantly previewing the rendered output — without leaving the keyboard. It ships with system-clipboard integration, multi-language syntax highlighting, autosave, and a built-in Help screen.

TermPad Python License
Features

    Editor + Live Preview tabs — switch instantly with F5, no external renderer needed
    System clipboard integration — Ctrl+C / Ctrl+X / Ctrl+V sync with the X11 / Wayland clipboard via pyperclip (OSC 52 fallback included)
    Multi-language syntax highlighting — Markdown, Python, JSON, CSS, JavaScript, HTML, SQL (powered by tree-sitter)
    Cycle language with one key — Ctrl+L rotates through languages instantly (no dropdown navigation)
    Autosave to temp file every 60 seconds, cleaned up on exit
    File operations — open / save / overwrite-confirm via modal dialogs
    Word-wrap toggle, undo/redo, select-all, and all the standard editor keybindings you'd expect
    Help screen on F1 — every binding documented in-app
    No external assets — single Python file, runs anywhere with pip install

Quick start
bash

# 1. install dependencies
pip install -r requirements.txt

# 2. (Linux only) install a clipboard utility so Ctrl+C/X/V cross apps:
sudo apt-get install xclip       # X11
# or
sudo apt-get install wl-clipboard  # Wayland

# 3. run
python termpad.py

Open a file with Ctrl+F, save with Ctrl+S, toggle Preview with F5, press F1 for the full keymap.
Two locales available

TermPad ships as two interchangeable single-file builds:
File
	
UI / Help language
	
Use when
termpad.py	English	default — international audience
termpad_thai.py	Thai (ภาษาไทย)	personal preference or Thai-speaking users

Both files are API-identical (TextEditorApp, EditorTextArea, modal screens) — pick the one that fits your audience, or keep both in the repo so users can choose. They share the same requirements.txt and the same SPEC.md.
Key bindings
Key
	
Action
F1	Help screen (full keymap)
F5	Toggle Editor ↔ Preview
Ctrl+S	Save file
Ctrl+F	Open file
Ctrl+R	Toggle word wrap
Ctrl+L	Cycle syntax-highlight language
Ctrl+Q	Quit
Ctrl+A	Select all
Ctrl+C	Copy → system clipboard
Ctrl+X	Cut → system clipboard
Ctrl+V	Paste from system clipboard
Ctrl+Z/Y	Undo / Redo
Home/End	Move cursor to start/end of line
Ctrl+Left/Right	Move cursor one word
Ctrl+K/U	Delete to end / start of line
Ctrl+W	Delete word to the left
Shift+Arrow	Select text
ESC	Close any modal dialog

Full reference (with notes on clipboard fallbacks, autosave path, etc.) lives in SPEC.md and is also reachable in-app via F1.
Project structure
text

termpad/
├── termpad.py          # Single-file app — English UI (default)
├── termpad_thai.py     # Single-file app — Thai UI (locale variant, API-identical)
├── requirements.txt    # Python dependencies
├── SPEC.md             # Technical specification
└── README.md           # This file

Embedding into other apps

EditorTextArea is a self-contained subclass of textual.widgets.TextArea — you can import and drop it into any Textual app. Both locale files expose the same class, so the import is identical:
python

# Pick whichever locale fits your app's UI language
from termpad import EditorTextArea          # English UI strings
# or
from termpad_thai import EditorTextArea     # Thai UI strings

class MyApp(App):
    def compose(self):
        yield EditorTextArea.code_editor("", language="markdown")

This makes it suitable as a building block for LLM wrappers, chat clients, note-taking apps, journaling tools, or any TUI that needs a Markdown-capable editing surface with system-clipboard support. See SPEC.md → "Integration" for details.
Requirements

    Python 3.10+
    textual >= 8.0.0
    pyperclip >= 1.8.0 (recommended — enables cross-application clipboard)
    Linux clipboard utility: xclip / xsel (X11) or wl-clipboard (Wayland)
    tree-sitter language parsers (auto-installed by Textual when needed)

Limitations & known quirks

    The OSC 52 fallback (used when pyperclip is unavailable) only works in terminals that support OSC 52 (iTerm2, Alacritty, Kitty, Windows Terminal, etc.). Otherwise Ctrl+C / Ctrl+X will only update the in-app clipboard.
    Over SSH without X11 forwarding, cross-application clipboard is unavailable. The editor still works normally within the session.
    The Markdown preview intentionally disables the Table of Contents sidebar (show_table_of_contents=False) because long headings otherwise cause the TOC to consume the entire terminal width.

License

MIT — see SPEC.md for the project owner information and feel free to fork, modify, and embed.
Acknowledgements

Built on top of Textual by the Textualize team — without which none of this would be possible.
