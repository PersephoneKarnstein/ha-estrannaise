# Build context is the REPOSITORY ROOT, not standalone/:
#   docker build -f standalone/Dockerfile .
# The image needs custom_components/estrannaise/*.py, so the context must
# include both trees. This is what keeps one copy of the PK model.
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    ESTRANNAISE_CORE=/app/core \
    ESTRANNAISE_DATA=/data

WORKDIR /app

COPY standalone/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# The three Home Assistant-free modules, imported by standalone/core.py.
# Copied individually and deliberately: pulling in the whole integration would
# drag __init__.py, which imports Home Assistant and would fail at runtime.
COPY custom_components/estrannaise/const.py \
     custom_components/estrannaise/database.py \
     custom_components/estrannaise/schedule.py \
     ./core/

COPY standalone/ ./standalone/

# Reuse the Plotly build the Lovelace card already vendors, rather than
# shipping a second copy or pulling from a CDN at runtime.
COPY custom_components/estrannaise/www/plotly-2.35.2.min.js \
     ./standalone/static/plotly.min.js

# Runs unprivileged. UID 1000 matches the PUID convention used across the
# stack, so the bind-mounted /data is writable without a chown on startup.
RUN useradd --uid 1000 --create-home --shell /usr/sbin/nologin estrannaise \
 && mkdir -p /data \
 && chown -R estrannaise:estrannaise /app /data

USER estrannaise
VOLUME ["/data"]
EXPOSE 8099

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
  CMD python -c "import urllib.request,sys; \
sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8099/healthz', timeout=4).status==200 else 1)"

CMD ["uvicorn", "standalone.app:app", "--host", "0.0.0.0", "--port", "8099"]
