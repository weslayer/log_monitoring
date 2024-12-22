FROM python:3.9-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY server.py .
COPY static/ static/

EXPOSE 3100

CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "3100"] 