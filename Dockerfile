FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt requirements-prod.txt ./
RUN pip install --no-cache-dir -r requirements.txt -r requirements-prod.txt
COPY app.py pyproject.toml Procfile ./
COPY templates/ templates/
COPY static/style.css static/style.css
RUN mkdir -p static/uploads instance
ENV PORT=8000 FLASK_ENV=production
EXPOSE 8000
CMD ["gunicorn", "-w", "3", "-b", "0.0.0.0:8000", "app:app"]
