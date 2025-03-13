# syntax=docker/dockerfile:1.2
FROM python:3.9-slim

# 作業ディレクトリを設定
WORKDIR /app

# 依存関係ファイルをコピー
COPY requirements.txt .

# BuildKit のキャッシュマウントを利用して、仮想環境の作成およびパッケージのインストール
RUN --mount=type=cache,target=/root/.cache/pip \
    python -m venv /opt/venv && \
    . /opt/venv/bin/activate && \
    pip install --no-cache-dir -r requirements.txt

# ソースコードを全てコピー
COPY . .

# コンテナ起動時に bot.py を実行
CMD ["/opt/venv/bin/python", "main.py"]
