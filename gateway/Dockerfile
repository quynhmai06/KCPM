FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
RUN mkdir -p /app/static/uploads/avatars

EXPOSE 8000
ENV FLASK_RUN_HOST=0.0.0.0 PORT=8000
CMD ["python", "app.py"]
