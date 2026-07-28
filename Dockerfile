FROM python:3.12-slim

LABEL maintainer="ToolDelta Studio"
LABEL description="ToolDelta - Plugin Loader for Minecraft"

ENV TZ=Asia/Shanghai
ENV PYTHONPATH=/app
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

COPY . /app/

RUN pip3 config set global.index-url https://pypi.tuna.tsinghua.edu.cn/simple && \
    pip3 install --no-cache-dir . && \
    rm -rf /app/*

CMD ["python", "-m", "tooldelta.tui"]
