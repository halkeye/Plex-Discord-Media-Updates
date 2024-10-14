FROM python:3.13.0

WORKDIR /usr/src/app

COPY pip_requirements.txt requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY config.yml plex_discord_media_updates.py /usr/src/app/

CMD [ "python", "./plex_discord_media_updates.py" ]
