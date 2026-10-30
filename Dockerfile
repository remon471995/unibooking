FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
WORKDIR /app

# System libraries WeasyPrint needs to build the voucher/report PDFs, plus fonts with Arabic support
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpango-1.0-0 libpangoft2-1.0-0 libharfbuzz-subset0 libffi8 shared-mime-info \
    fonts-noto-core fonts-noto-ui-core \
 && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
RUN DJANGO_SECRET_KEY=build-only python manage.py collectstatic --noinput

CMD ["sh", "-c", "python manage.py migrate --noinput && gunicorn unibooking.wsgi:application --bind 0.0.0.0:${PORT:-8000} --workers 2 --timeout 120"]
