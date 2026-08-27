FROM python:3.12-slim-bookworm

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
    && playwright install --with-deps chromium

COPY arin_waitlist.py .

RUN mkdir -p /data

ENV ARIN_STATE_FILE=/data/arin_waitlist_state.json \
    PYTHONUNBUFFERED=1

VOLUME /data

# Watch mode checks once a day by default. Pass --once to run a single check.
ENTRYPOINT ["python", "arin_waitlist.py"]
CMD ["--watch"]
