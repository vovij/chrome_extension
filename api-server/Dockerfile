FROM python:3.11-slim

RUN apt-get update && apt-get install -y build-essential curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
RUN mkdir -p /app/data

COPY requirements.txt ./

RUN pip install torch==2.10.0 --index-url https://download.pytorch.org/whl/cpu
RUN pip install -r requirements.txt

COPY . .
COPY .env* ./

EXPOSE 8000

CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]