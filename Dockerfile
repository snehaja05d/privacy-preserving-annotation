FROM python:3.11-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PIP_NO_CACHE_DIR=1

RUN apt-get update && apt-get install -y \
    libglib2.0-0 \
    libgl1 \
    libgomp1 \
    libsm6 \
    libxext6 \
    libxrender1 \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# Install CPU-only PyTorch separately so this layer stays cached
RUN pip install --upgrade pip && \
    pip install torch==2.13.0 torchvision==0.28.0 \
    --index-url https://download.pytorch.org/whl/cpu

# Install project dependencies
COPY requirements.txt .

RUN pip install -r requirements.txt

# Copy project
COPY . .

EXPOSE 8501

CMD ["python", "privacyhub_web/run_web.py"]
