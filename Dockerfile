FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 DATABASE_PATH=/data/faf.sqlite3 REPLAY_DIR=/replays FRIENDS_CONFIG_PATH=/config/friends.json
ARG APP_UID=10001
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt && useradd --uid ${APP_UID} --create-home app && mkdir /data /replays && chown app:app /data /replays
COPY --chown=app:app app ./app
COPY --chown=app:app config /config
USER app
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/healthz', timeout=3)"
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]
