FROM python:3.12-slim

WORKDIR /app

COPY pyproject.toml README.md LICENSE ./
COPY meta_ads_mcp/ ./meta_ads_mcp/

RUN pip install --no-cache-dir .

EXPOSE 8000

ENV MCP_TRANSPORT=sse

ENTRYPOINT ["python", "-m", "meta_ads_mcp"]
