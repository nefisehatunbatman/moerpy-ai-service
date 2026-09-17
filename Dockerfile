FROM python:3.11-slim AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY requirements.txt requirements.txt
RUN pip install --no-cache-dir -r requirements.txt && useradd --uid 10001 --create-home aiservice && mkdir /state && chown aiservice /state
COPY app app
RUN rm -rf app/tests
COPY main.py main.py
COPY data/financial_decisions.jsonl data/financial_decisions.jsonl
COPY scripts scripts
USER aiservice
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/ready', timeout=3)"
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]

FROM runtime AS test
USER root
COPY requirements-dev.txt requirements-dev.txt
RUN pip install --no-cache-dir -r requirements-dev.txt
COPY app/tests app/tests
COPY pytest.ini pytest.ini
USER aiservice
HEALTHCHECK NONE
CMD ["python", "-B", "-m", "pytest", "-q", "-p", "no:cacheprovider"]

# A plain docker build produces the service, not the test runner.
FROM runtime AS production
