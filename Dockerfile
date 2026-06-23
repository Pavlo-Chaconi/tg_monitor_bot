FROM python:3.12-slim

WORKDIR /app

# Устанавливаем зависимости отдельным слоем — кешируется пока requirements.txt не изменится
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

CMD ["python", "main.py"]
