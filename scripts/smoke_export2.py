import os
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
import django; django.setup()

from django.contrib.auth import get_user_model
from rest_framework_simplejwt.tokens import AccessToken
import urllib.request

User = get_user_model()
user = User.objects.get(username="bassemwolsely94")
token = str(AccessToken.for_user(user))
headers = {"Authorization": "Bearer " + token}

paths = [
    "http://localhost:8000/api/purchasing/summary/",
    "http://localhost:8000/api/purchasing/export/",
    "http://localhost:8000/api/purchasing/export/?format=xlsx&view=aggregated",
    "http://localhost:8000/api/purchasing/trigger/",
]
for path in paths:
    req = urllib.request.Request(path, headers=headers)
    try:
        resp = urllib.request.urlopen(req, timeout=10)
        body = resp.read()
        print("OK ", resp.status, path[-55:], len(body), "bytes")
    except urllib.error.HTTPError as e:
        body = e.read()
        try:
            msg = body.decode("utf-8")[:80]
        except Exception:
            msg = repr(body[:80])
        print("ERR", e.code, path[-55:], msg)
