import requests

HEADER = "X-ElR-RPA-Agent"


class AgentClient:
    def __init__(self, base_url, token, timeout=30):
        self.base = base_url.rstrip("/") + "/api/rpa/agent/"
        self.headers = {HEADER: token}
        self.timeout = timeout

    def _post(self, path, **kw):
        r = requests.post(self.base + path, headers=self.headers, timeout=self.timeout, **kw)
        if r.status_code != 204:
            r.raise_for_status()
        return r

    def claim(self):
        r = self._post("claim/")
        return None if r.status_code == 204 else r.json()

    def heartbeat(self, doc_id):
        self._post("documents/%s/heartbeat/" % doc_id)

    def report(self, doc_id, payload):
        self._post("documents/%s/report/" % doc_id, json=payload)

    def screenshot(self, run_id, step_index, png_bytes):
        self._post("runs/%s/screenshot/" % run_id,
                   data={"step_index": str(step_index)},
                   files={"image": ("shot.png", png_bytes, "image/png")})
