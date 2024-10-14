FROM python:3.13.0

WORKDIR /usr/src/app

RUN apt-get update && \
  apt-get install -yqq --no-install-recommends gettext && \
  apt-get autoremove && \
  apt-get clean && \
  rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./requirements.txt

RUN pip install --no-cache-dir -r requirements.txt

COPY config.yml plex_discord_media_updates.py /usr/src/app/

CMD [ "python", "./plex_discord_media_updates.py" ]
