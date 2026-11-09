FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    HOST=0.0.0.0 \
    PORT=8000

WORKDIR /app

COPY requirements.txt ./
# Install the CPU-only wheel first; requirements.txt then sees torch>=2.0 as satisfied.
RUN pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu \
    && pip install --no-cache-dir -r requirements.txt

COPY . .
RUN mkdir -p data

EXPOSE 8000
CMD ["python", "run.py", "--no-browser"]
