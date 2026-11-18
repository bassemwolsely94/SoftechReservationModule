"""Windows driver. pywinauto / Pillow are imported lazily."""
import io

MAX_BYTES = 2 * 1024 * 1024


def _norm(s):
    return " ".join((s or "").split())


class Win32Driver:
    def _desktop(self):
        from pywinauto import Desktop
        return Desktop(backend="win32")

    def focus(self, window_title):
        """True only if the foreground window title equals window_title (collapsed whitespace)."""
        try:
            wins = [w for w in self._desktop().windows()
                    if _norm(w.window_text()) == _norm(window_title)]
            if not wins:
                return False
            w = wins[0]
            import ctypes
            if int(ctypes.windll.user32.GetForegroundWindow()) != int(w.handle):
                try:
                    w.set_focus()
                except Exception:
                    pass
            return int(ctypes.windll.user32.GetForegroundWindow()) == int(w.handle)
        except Exception:
            return False

    def send(self, keys, pause):
        from pywinauto.keyboard import send_keys
        # keys are already in send_keys notation (server-escaped): send verbatim.
        send_keys(keys, pause=pause, with_spaces=False, with_tabs=False, with_newlines=False,
                  turn_off_numlock=False)

    def popups(self):
        out = []
        try:
            for w in self._desktop().windows(class_name="#32770"):
                text = " ".join(c.window_text() for c in w.children() if c.window_text())
                out.append({"title": w.window_text(), "text": text})
        except Exception:
            pass
        return out

    def screenshot(self):
        from PIL import ImageGrab
        img = ImageGrab.grab()
        scale = 1.0
        while True:
            im = img if scale == 1.0 else img.resize(
                (int(img.width * scale), int(img.height * scale)))
            buf = io.BytesIO()
            im.save(buf, format="PNG", optimize=True)
            data = buf.getvalue()
            if len(data) <= MAX_BYTES or scale < 0.2:
                return data
            scale *= 0.7
