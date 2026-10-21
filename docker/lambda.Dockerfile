FROM public.ecr.aws/lambda/python:3.14 AS builder

WORKDIR ${LAMBDA_TASK_ROOT}

# copy uv binary from uv image
COPY --from=ghcr.io/astral-sh/uv:0.11.31 /uv /bin/uv

# copy dependency manifests
COPY uv.lock pyproject.toml ./

# Install third-party dependencies for `core` and `lambda` packages
RUN uv export \
    --no-emit-workspace \
    --package did_lambda \
    --package core \
    --frozen \
    --no-dev \
    --no-editable \
    --output-file requirements.txt && \
    pip install --no-cache-dir -r requirements.txt --target "${LAMBDA_TASK_ROOT}"

FROM public.ecr.aws/lambda/python:3.14

# AL2023's ca-certificates still ships two roots distrusted after the eMudhra CA
# key compromise: emSign ECC Root CA - G3 and Comodo's AAA Certificate Services.
# Drop them from the trust source and re-extract every bundle. This is a no-op
# once AL2023 ships a fixed package.
RUN gawk -i inplace -v RS= -v ORS='\n\n' \
    '!/\nlabel: "(emSign ECC Root CA - G3|Comodo AAA Services root)"\n/' \
    /usr/share/pki/ca-trust-source/ca-bundle.trust.p11-kit \
    && update-ca-trust extract

# Remove the base image's own AWS SDK and pip. The function uses the pinned
# copies in LAMBDA_TASK_ROOT, and the base copies ship outdated CA bundles.
RUN pip uninstall -y --no-cache-dir boto3 botocore s3transfer pip

# default VERSION is 0.0.0 if not passed at build time
ARG VERSION="0.0.0"

# make it available as an environment variable inside the container
ENV VERSION=$VERSION

# copy all dependencies to lambda task root
COPY --from=builder ${LAMBDA_TASK_ROOT} ${LAMBDA_TASK_ROOT}

# copy necessary workspace packages
COPY ./packages/core/src/core ${LAMBDA_TASK_ROOT}/core

# copy main lambda app
COPY ./packages/did_lambda/src/did_lambda ${LAMBDA_TASK_ROOT}/app/lambda

# Fail the build if either distrusted root is left in any CA bundle, whether from
# the OS or vendored by a Python package. Each pattern is one line of a root's
# base64 body (emSign ECC Root CA - G3, then AAA Certificate Services), so it
# matches however a bundle labels the certificate. grep exits 1 only when
# nothing matched.
RUN grep -rlF \
    -e 'CUfvO6wIBHxcmbHtRwfSAjEAnbpV/KlK6O3t5nYBQnvI+GDZjVGLVTv7jHvrZQnD' \
    -e 'l2D4kF501KKaU73yqWjgom7C12yxow+ev+to51byrvLjKzg6CYG1a4XXvi3tPxq3' \
    /etc /usr /var; \
    test $? -eq 1

# used to satisfy scans since AWS Lambda will already run function as its own non-root user at runtime
USER 1001:1001

CMD ["app.lambda.lambda_function.lambda_handler"]