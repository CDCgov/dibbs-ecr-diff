FROM public.ecr.aws/lambda/python:3.14 AS builder

WORKDIR ${LAMBDA_TASK_ROOT}

# copy uv binary from uv image
COPY --from=ghcr.io/astral-sh/uv:0.10.9 /uv /bin/uv

# copy dependency manifests
COPY uv.lock pyproject.toml ./

# Install third-party dependencies for `core` and `lambda` packages
RUN uv export \
    --no-emit-workspace \
    --package lambda \
    --package core \
    --frozen \
    --no-dev \
    --no-editable \
    --output-file requirements.txt && \
    pip install --no-cache-dir -r requirements.txt --target "${LAMBDA_TASK_ROOT}"

FROM public.ecr.aws/lambda/python:3.14

# default VERSION is 0.0.0 if not passed at build time
ARG VERSION="0.0.0"

# make it available as an environment variable inside the container
ENV VERSION=$VERSION

# copy all dependencies to lambda task root
COPY --from=builder ${LAMBDA_TASK_ROOT} ${LAMBDA_TASK_ROOT}

# copy necessary workspace packages
COPY ./packages/core/src/core ${LAMBDA_TASK_ROOT}/core

# copy main lambda app
COPY ./packages/lambda/src/lambda ${LAMBDA_TASK_ROOT}/app

# used to satisfy scans since AWS Lambda will already run function as its own non-root user at runtime
USER 1001:1001

CMD ["app.lambda_function.lambda_handler"]