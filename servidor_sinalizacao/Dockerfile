FROM python:3.11-slim

WORKDIR /aplicacao
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .

EXPOSE 8080
CMD ["python", "servidor.py", "--host", "0.0.0.0"]
