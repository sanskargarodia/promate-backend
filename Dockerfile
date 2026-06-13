# Bedrock AgentCore Runtime image. Serves the ProMate agent on port 8080
# (BedrockAgentCoreApp: /invocations + /ping) via app/agent_core_entrypoint.py.
# Built for linux/arm64 by AgentCore CodeBuild. Runtime env (ANTHROPIC_API_KEY,
# DATABASE_URL, ...) is injected at deploy time, never baked into the image.
#
# Base image is pulled from Amazon ECR Public (NOT Docker Hub) to avoid CodeBuild
# hitting Docker Hub's anonymous pull rate limit (429 Too Many Requests).
FROM public.ecr.aws/docker/library/python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUTF8=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# libgomp1 is required at runtime by onnxruntime (fastembed embeddings).
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential libgomp1 \
    && rm -rf /var/lib/apt/lists/*

# Dependency layer (cached unless requirements change).
COPY requirements.txt ./
RUN pip install -r requirements.txt

# Bake the embedding model into the image so cold starts don't download ~130MB.
RUN python -c "from fastembed import TextEmbedding; list(TextEmbedding('BAAI/bge-small-en-v1.5').embed(['warmup']))"

COPY . .

EXPOSE 8080
CMD ["python", "-m", "app.agent_core_entrypoint"]
