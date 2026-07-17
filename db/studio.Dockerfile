# Curation Studio in a container — so a fresh clone needs nothing but Docker.
# Build context is the repo root (see db/docker-compose.yml).
FROM python:3.12-slim
WORKDIR /app/db/tools
COPY db/tools/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
# the repo is bind-mounted over /app at runtime (live-editable UI + uploads)
EXPOSE 8890
CMD ["uvicorn", "curate:app", "--host", "0.0.0.0", "--port", "8890"]
