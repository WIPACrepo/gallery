FROM python:3.10

RUN apt-get update && apt-get install -y fonts-freefont-ttf ffmpeg && apt-get clean

RUN useradd -m -U app
RUN mkdir /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

WORKDIR /app
USER app

COPY . .

ENV PYTHONPATH=/app

CMD ["bash"]
