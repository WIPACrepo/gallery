FROM python:3.12

RUN apt-get update && apt-get install -y fonts-freefont-ttf ffmpeg imagemagick && apt-get clean

RUN useradd -m -U app
RUN mkdir /app

WORKDIR /app

COPY src /app/src
COPY pyproject.toml /app/pyproject.toml

RUN chown -R app:app /app

USER app

ENV VIRTUAL_ENV=/app/venv

RUN python3 -m venv $VIRTUAL_ENV

ENV PATH="$VIRTUAL_ENV/bin:$PATH"

RUN ls -al

RUN --mount=source=.git,target=.git,type=bind pip install -e .

CMD ["python", "-m", "gallery"]
