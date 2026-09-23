FROM python:3.11-slim

WORKDIR /app

# Dependencies first so that code changes do not invalidate the pip layer.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY src/ ./src/
COPY db/ ./db/
COPY data/ ./data/

# No CMD on purpose: docker-compose starts four different processes from this
# same image, so each service supplies its own command.
