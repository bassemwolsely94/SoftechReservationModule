import os
from django.core.wsgi import get_wsgi_application

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
application = get_wsgi_application()

from config.writers import run_startup_checks  # noqa: E402
run_startup_checks()     # P-54: refuse to serve on a duplicated .env key or a contradictory role
