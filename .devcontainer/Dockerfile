FROM mcr.microsoft.com/vscode/devcontainers/python:0-3.8

SHELL ["/bin/bash", "-o", "pipefail", "-c"]


WORKDIR /workspaces

# Install Python dependencies from requirements.txt if it exists
COPY requirements_tests.txt .
RUN pip3 install -r requirements_tests.txt \
    && pip3 install tox \
    && rm -f requirements_tests.txt

# Set the default shell to bash instead of sh
ENV SHELL /bin/bash
