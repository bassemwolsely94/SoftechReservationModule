"""Always-on-top operator strip. tkinter / pynput are imported lazily."""
import threading

HANDS_OFF = "ارفع يدك عن الكيبورد"
STOP = "إيقاف"
START = "ابدأ"
CANCEL = "إلغاء"


def handle_press(stop, is_esc, injected):
    """Esc stops the run, but never for keys the robot itself injected."""
    if is_esc and not injected:
        stop.set()


class Overlay:
    def __init__(self, stop_event):
        self.stop = stop_event
        self._listener = None
        self._closing = False
        self._message = None

    def say(self, text):
        """Show `text` on the running strip in place of the hands-off line (supplier-portal robot:
        «سجّل الدخول ثم اضغط متابعة», «راجع ثم اضغط Submit Order بنفسك»)."""
        self._message = text

    def confirm_checklist(self, reference, items):
        """Blocks until the operator ticks every item and presses start. False if declined."""
        import tkinter as tk
        result = {"ok": False}
        root = tk.Tk()
        root.title("ElRezeiky RPA " + reference)
        root.attributes("-topmost", True)
        vars_ = []

        def refresh():
            btn.config(state="normal" if all(x.get() for x in vars_) else "disabled")

        for it in items:
            v = tk.BooleanVar(value=False)
            vars_.append(v)
            tk.Checkbutton(root, text=it, variable=v, anchor="e", justify="right",
                           command=refresh).pack(fill="x", padx=10, pady=2)

        def go():
            result["ok"] = True
            root.destroy()

        btn = tk.Button(root, text=START, command=go)
        btn.pack(side="left", padx=10, pady=10)
        tk.Button(root, text=CANCEL, command=root.destroy).pack(side="right", padx=10, pady=10)
        refresh()
        root.mainloop()
        return result["ok"]

    def show_running(self, reference):
        """Start the strip in a thread and the Esc listener; returns immediately."""
        self._closing = False

        def ui():
            import tkinter as tk
            root = tk.Tk()
            root.attributes("-topmost", True)
            root.overrideredirect(True)
            root.geometry("+0+0")
            label = tk.Label(root, text="%s  %s" % (HANDS_OFF, reference), bg="#b00020", fg="white",
                             font=("Segoe UI", 16, "bold"))
            label.pack(side="left", padx=10)
            tk.Button(root, text=STOP, font=("Segoe UI", 18, "bold"), bg="black", fg="white",
                      command=self.stop.set).pack(side="right")

            def poll():
                if self._closing:
                    root.destroy()
                else:
                    if self._message is not None:
                        label.config(text="%s  %s" % (self._message, reference), bg="#022871")
                        self._message = None
                    root.after(200, poll)
            poll()
            root.mainloop()

        threading.Thread(target=ui, daemon=True).start()
        try:
            from pynput import keyboard

            def on_press(key, injected=False):
                handle_press(self.stop, key == keyboard.Key.esc, injected)
            self._listener = keyboard.Listener(on_press=on_press)
            self._listener.start()
        except Exception:
            pass

    def close(self):
        self._closing = True
        if self._listener:
            self._listener.stop()
