FROM python:3.13-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
# Render 는 PORT 를 주입한다. 로컬 docker run 에서는 8000.
CMD ["sh", "-c", "python start.py --host 0.0.0.0 --port ${PORT:-8000} --llm ${PLANBEE_LLM:-live} --no-browser"]
