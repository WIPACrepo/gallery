FROM python:3.12

RUN apt-get update && apt-get install -y fonts-freefont-ttf ffmpeg imagemagick && apt-get clean

RUN useradd -m -U app
RUN mkdir /app && chown app:app /app

WORKDIR /app
USER app

COPY . .

ENV VIRTUAL_ENV=/app/venv

RUN python3 -m venv $VIRTUAL_ENV

ENV PATH="$VIRTUAL_ENV/bin:$PATH"

RUN pip install -e /app

CMD ["python", "-m", "gallery"]
