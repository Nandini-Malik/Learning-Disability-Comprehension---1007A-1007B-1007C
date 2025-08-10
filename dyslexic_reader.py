import tkinter as tk
from tkinter import scrolledtext
import pyttsx3
import threading
import queue
import re
import string
from functools import partial

# -------------------------
# TTS worker + queues
# -------------------------
tts_queue = queue.Queue()   # tasks sent to TTS worker
gui_queue = queue.Queue()   # events from TTS worker to GUI (word-start events)

def tts_worker():
    """Runs in a background thread. Owns its pyttsx3 engine."""
    engine_worker = pyttsx3.init()
    # Callback function for word-start events; push to gui_queue
    def on_word(name, location, length):
        # place an event for GUI to process (do NOT touch GUI here)
        gui_queue.put(('word', location, length))
    while True:
        task = tts_queue.get()
        if task is None:
            # shutdown sentinel
            tts_queue.task_done()
            break

        ttype = task.get('type')
        text = task.get('text', '')
        sync = task.get('sync', False)

        if ttype == 'speak':
            if sync:
                # connect callback
                cid = engine_worker.connect('started-word', on_word)
                engine_worker.say(text)
                engine_worker.runAndWait()
                # disconnect callback to avoid accumulating callbacks
                try:
                    engine_worker.disconnect(cid)
                except Exception:
                    pass
            else:
                # just speak without callbacks (good for letter clicks)
                engine_worker.say(text)
                engine_worker.runAndWait()

        tts_queue.task_done()

# Start the TTS worker thread
threading.Thread(target=tts_worker, daemon=True).start()

# Helper to enqueue speak tasks
def enqueue_speak(text, sync=False):
    """Put a speak task into the TTS queue.
       sync=True => worker will connect started-word and emit gui events
       sync=False => speak without callbacks (no highlights)
    """
    tts_queue.put({'type':'speak', 'text': text, 'sync': sync})

# -------------------------
# GUI and app logic
# -------------------------
root = tk.Tk()
root.title("Dyslexia Comprehension")
root.geometry("900x600")
root.configure(bg="#F5F5DC")

# -------------------------
# Left: Scrollable alphabet & numbers panel
# -------------------------
panel_frame = tk.Frame(root)
panel_frame.pack(side="left", fill="y", padx=(8,4), pady=8)

panel_canvas = tk.Canvas(panel_frame, width=120, highlightthickness=0)
panel_scrollbar = tk.Scrollbar(panel_frame, orient="vertical", command=panel_canvas.yview)
panel_inner = tk.Frame(panel_canvas)

panel_inner.bind(
    "<Configure>",
    lambda e: panel_canvas.configure(scrollregion=panel_canvas.bbox("all"))
)

panel_canvas.create_window((0,0), window=panel_inner, anchor="nw")
panel_canvas.configure(yscrollcommand=panel_scrollbar.set)

panel_canvas.pack(side="left", fill="y", expand=False)
panel_scrollbar.pack(side="right", fill="y")

# Similar-looking groups and colors (you can tweak colors)
similar_groups = [
    set(['I','l','1']),
    set(['O','0','o']),
    set(['B','8']),
    set(['S','5']),
    set(['Z','2']),
    set(['M','rn']),  # note 'rn' isn't a single char but grouping to suggest similarity
]
group_colors = ['#ffb3c1','#b3ffd9','#c6c6ff','#fff9b3','#ffd9b3','#d0f0ff']
char_color_map = {}
# assign colors for single-char members
for idx, grp in enumerate(similar_groups):
    for ch in grp:
        if len(ch) == 1:
            char_color_map[ch] = group_colors[idx]

default_btn_color = "#eeeeee"
# Create buttons: capitals A-Z, lowercase a-z, then 0-9
for ch in list(string.ascii_uppercase) + list(string.ascii_lowercase) + list(string.digits):
    color = char_color_map.get(ch, default_btn_color)
    btn = tk.Button(panel_inner, text=ch, width=6, height=1,
                    bg=color, relief="raised")
    btn.pack(pady=3, padx=6)

# -------------------------
# Right: Text area + controls
# -------------------------
right_frame = tk.Frame(root)
right_frame.pack(side="right", fill="both", expand=True, padx=(4,8), pady=8)

text_area = scrolledtext.ScrolledText(right_frame, wrap=tk.WORD, width=60, height=25,
                                      font=("Arial", 16), bg="#f5f5dc", fg="#222222")
text_area.pack(fill="both", expand=True, padx=6, pady=6)

controls_frame = tk.Frame(right_frame)
controls_frame.pack(fill="x", pady=(4,0))

# Read button (speaks entire text with highlighting sync)
def start_reading():
    """Collect the text and enqueue a speak task with sync=True (so highlighting events will be produced)."""
    content = text_area.get("1.0", tk.END).rstrip()
    if not content.strip():
        return
    # store latest_text so GUI highlight events refer to the same text the TTS sees
    global latest_text_for_tts
    latest_text_for_tts = content
    # enqueue a synced speak (worker will emit started-word events)
    enqueue_speak(content, sync=True)

read_btn = tk.Button(controls_frame, text="Read & Highlight", font=("Arial",12),
                     bg="#4CAF50", fg="white", command=start_reading)
read_btn.pack(side="left", padx=6)

# -------------------------
# GUI polling: process gui_queue events from TTS worker
# -------------------------
HIGHLIGHT_TAG = "highlight"
HIGHLIGHT_BG = "#FFFF99"

def process_gui_events():
    """Called periodically in main thread to handle events posted by TTS worker."""
    try:
        while True:
            ev = gui_queue.get_nowait()
            if not ev:
                continue
            etype = ev[0]
            if etype == 'word':
                _, location, length = ev
                # Use the exact location & length provided by TTS engine
                # Ensure indices are within bounds
                try:
                    if location < 0:
                        continue
                    # Remove old highlight, add new
                    text_area.tag_remove(HIGHLIGHT_TAG, "1.0", tk.END)
                    start = f"1.0 + {location} chars"
                    end = f"{start} + {length} chars"
                    text_area.tag_add(HIGHLIGHT_TAG, start, end)
                    text_area.tag_config(HIGHLIGHT_TAG, background=HIGHLIGHT_BG)
                    # Make sure highlighted word is visible
                    text_area.see(start)
                except Exception:
                    # ignore any index errors gracefully
                    pass
            # mark processed
            gui_queue.task_done()
    except queue.Empty:
        pass
    # schedule the next poll
    root.after(30, process_gui_events)

# start polling
process_gui_events()

# -------------------------
# Graceful shutdown
# -------------------------
def on_closing():
    # stop worker
    tts_queue.put(None)
    # wait until worker finishes
    tts_queue.join()
    root.destroy()

root.protocol("WM_DELETE_WINDOW", on_closing)

# Run the GUI
root.mainloop()
