# -*- coding: utf-8 -*-
import re
import os
import requests
import time
import yaml
from envsubst import envsubst
from collections import Counter
from dhooks import Webhook, Embed
from pathlib import Path
from plexapi.server import PlexServer

'''
------------------------------------------------------------------------------
PURPOSE

This script is meant to check your plex server, retrieve lists of
shows and movies that are in the Recently Added sections, count and
format them nicely, and then output to a message via discord webhook.

If the lists of media (one for Movies and one for TV) are longer than
discord's max message length (currently set as 4096 chars but can be changed
in the "USER OPTIONS" section below), they will be cut down to size.

i.e: If the sum of the length of both lists is over the
max length, they will each be trimmed down to half of the max size.

The script is meant to be run on a schedule (e.g. via crontab or unraid
user scripts). By default, it should be run every 24 hours, but if you
prefer to run it at a different interval, be sure to change the
lookback_period variable in the "USER OPTIONS" section below.

To get the script working with minimal configuration, you will need to change
these variables (plex_url, plex_token, webhook_url) to match your plex/discord
info; they're in the "USER OPTIONS" section below.

NOTE: Do not set the lookback_period variable to be too far back, or the list
of media may be cut off.

------------------------------------------------------------------------------
DEPENDENCIES

This script requires Python 3, along with the Python modules outlined in
the associated "requirements.txt" file. The modules can be installed by
executing the command in the same folder as requirements.txt:

pip install -r requirements.txt
------------------------------------------------------------------------------
CHANGELOG
~ v1.3 - 2022-05-20
- Switched string generation to use f-strings
- Cleaned up unnecessary code

~ v1.2 - 2022-04-27
- Refactored user variables to be configured via an external secrets file.
- Added a function to ping uptime status monitors

~ v1.1 - 2022-03-19
- Made it so that in case there are too many recently added shows/movies,
the list(s) will automatically be trimmed down to a size that can still be
sent via webhook. Before, if one or both lists were too long, the webhook
message would simply fail and not get sent.

~ v1.0 - 2022-03-17
- Initial build
------------------------------------------------------------------------------
'''
start_time = int(time.time())

os.environ["PLEX_URL"] = os.getenv("PLEX_URL", "https://localhost:32400")
os.environ["PLEX_TOKEN"] = os.getenv("PLEX_TOKEN", "XXXXXXXXXXXXXXXXXXXXX")
os.environ["DISCORD_URL"] = os.getenv("DISCORD_URL", "https://discord.com/api/webhooks/XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX")
os.environ["LOOPBACK_PERIOD"] = os.getenv("LOOPBACK_PERIOD", "24h")

# Setting variables from config file
with open(os.getenv("CONFIG_FILE", Path(__file__).with_name("config.yml")), encoding="utf-8") as file:
    config = yaml.safe_load(envsubst(file.read()))

script_config = config["plex_discord_media_updates"]
try:
    testing_mode = script_config["testing_mode"]
except:
    testing_mode = False
try:
    uptime_status = config["uptime_status"]["plex_discord_media_updates"]
except:
    uptime_status = None
plex_url = config["plex"]["url"]
plex_token = config["plex"]["token"]
movie_library = config["plex"]["libraries"]["movies"]
tv_library = config["plex"]["libraries"]["shows"]
webhook_url = script_config["webhook"]
lookback_period = script_config["lookback_period"]
skip_movies = script_config["skip_libraries"]["movies"]
skip_tv = script_config["skip_libraries"]["shows"]
show_total_episodes = script_config["show_total_episode_count"]
show_individual_episodes = script_config["show_episode_count_per_show"]
message_title = script_config["message_options"]["title"]
embed_options = script_config["embed_options"]
embed_thumbnail = embed_options["thumbnail"]
bullet = embed_options["bullet"]
movie_embed_colour = embed_options["movies_colour"]
tv_embed_colour = embed_options["shows_colour"]
movie_emote = embed_options["movies_emote"]
tv_emote = embed_options["shows_emote"]
max_length_exceeded_msg = script_config["overflow_footer"]

# Character limit of a discord message including embeds
message_max_length = 4000

if testing_mode:
    webhook_url = script_config["testing"]["webhook"]


def clean_year(media):
    """
    Takes a Show/Movie object and returns the title of it with the year
    properly appended. Prevents media with the year already in the title
    from having duplicate years. (e.g., avoids situations like
    "The Flash (2014) (2014)").

    Arguments:
    media -- an object with both .title and .year variables
    """
    title = ""
    # year_regex matches any string ending with a year between 1000-2999 in
    # parentheses. e.g. "The Flash (2014)"
    year_regex = re.compile(".*\([12][0-9]{3}\)$")
    title += media.title
    if not year_regex.match(media.title):
        title += " (" + str(media.year) + ")"
    return title


def trim_on_newlines(long_string, max_length):
    """
    Takes a long multi-line string and a max length, and returns a subsection
    of the string that's the max length or shorter, that ends before a
    newline.

    Arguments:
    long_string -- string; any string with a newline character
    max_length -- integer; denotes the max length to trim the string down to
    """
    if len(long_string) > max_length:
        end = long_string.rfind("\n", 0, max_length)
        return long_string[:end] + max_length_exceeded_msg
    else:
        return long_string + max_length_exceeded_msg


def create_embeds(embed_title, embed_description, embed_color, max_length):
    """
    Creates an embed with data from the given arguments, but modifies the
    description of the embed so be below a given amount of characters. Will
    only trim the embed at the end of a line to avoid partial lines, while
    still keeping the description below max_length.

    Arguments:
    embed_title -- title for the embed
    embed_description -- description for the embed
    embed_color -- colour for the embed
    max_length -- integer; the max length for the embed's description
    """
    if len(embed_description) > max_length:
        embed_description = trim_on_newlines(embed_description, max_length)
    embed = Embed(
        title=embed_title,
        description=embed_description,
        color=embed_color)
    webhook_embeds.append(embed)


if __name__ == "__main__":

    # Formatting strings from user variables section
    bullet += " "
    max_length_exceeded_msg = f"\n\n**{max_length_exceeded_msg}**"
    # Checks whether the lookback period should be specified
    # in plural and makes the message text look more natural.
    period_dict = {
        "m": "minute",
        "h": "hour",
        "d": "day",
        "w": "week",
    }

    # Builds the webhook message that includes the max age of the new media
    if lookback_period[:-1] == "1":
        lookback_text = period_dict[lookback_period[-1]]
    else:
        lookback_text = (f"{lookback_period[:-1]}"
                         f" {period_dict[lookback_period[-1]]}s")
    message_title = f"_ _\n**{message_title} {lookback_text}:**"

    # Initializing plex connection and data structures
    plex = PlexServer(plex_url, plex_token)
    webhook = Webhook(webhook_url)
    webhook_embeds = []
    media_lists = []

    # Skips scanning libraries if specified
    if not skip_movies:
        movies = plex.library.section(movie_library)
        # Retrieves all movies added since the start of the lookback period
        new_movies = movies.search(filters={"addedAt>>": lookback_period})
        # Raises a flag to skip the movie embed
        # creation/addition if there are no new movies
        if not new_movies:
            skip_movies = True
        else:
            # Building movies list
            movies_str = bullet
            new_movies_formatted = [clean_year(movie) for movie in new_movies]
            total_movies = len(new_movies_formatted)
            movies_str += ("\n" + bullet).join(new_movies_formatted)
            media_lists.append(movies_str)

            # Pluralizes "Movie" title string if appropriate
            movies_title_counted = "Movie"
            if total_movies != 1:
                movies_title_counted += "s"

            # Builds the Movies embed title
            movie_title = (f"{total_movies} {movies_title_counted}"
                           f" {movie_emote}")
    if not skip_tv:
        shows = plex.library.section(tv_library)
        # Retrieves all TV episodes added since the start of the lookback
        # period.
        new_eps = shows.searchEpisodes(filters={"addedAt>>": lookback_period})
        # Raises a flag to skip the TV show embed creation/addition if there
        # are no new episodes
        if not new_eps:
            skip_tv = True
        else:
            # Building TV shows list
            newShows = []
            for episode in new_eps:
                # Cannot directly retrieve the Show object from the Episode
                # object so I'm using the workaround to search by unique
                # RatingKey instead.
                newShows.append(clean_year(
                                plex.fetchItem(episode.grandparentRatingKey)))

            # Counts the duplicates and builds the
            # properly-formatted list with episode counts
            counted_shows = Counter(newShows)
            show_list = []
            total_episodes = 0

            # Loops through the dictionary of shows with their counts
            for counted_show in counted_shows:
                # Retrieves the number of new episodes for the current show
                episode_count = counted_shows[counted_show]
                total_episodes += episode_count
                episodes_counted = "episode"
                # Pluralizes "episode" string if appropriate
                if episode_count > 1:
                    episodes_counted += "s"
                if show_individual_episodes:
                    show_list.append(f"{bullet}{counted_show} -"
                                     f" *{episode_count} {episodes_counted}*")
                else:
                    show_list.append(bullet + counted_show)
            show_list.sort()
            total_shows = len(show_list)
            tv_str = "\n".join(show_list)
            media_lists.append(tv_str)

            # Pluralizes "TV Show" and "Episode" title strings if appropriate
            show_title_counted = "Show"
            episode_title_counted = "Episode"
            # Case for multiple shows, therefore multiple episodes
            if total_shows > 1:
                episode_title_counted += "s"
                show_title_counted += "s"
            # Case where there is only one show, but has multiple episodes
            elif episode_count > 1:
                show_title_counted += "s"

            if show_total_episodes:
                # Builds the TV Shows embed title with the episode count
                tv_title = (f"{total_shows} {show_title_counted} /"
                            f" {total_episodes} {episode_title_counted}"
                            f" {tv_emote}")
            else:
                # Builds the TV Shows embed title
                tv_title = (f"{total_shows} {show_title_counted} {tv_emote}")

    # Building embeds
    list_count = len(media_lists)
    if ((sum([len(descr) for descr in media_lists]) < message_max_length)):
        # Sets to max message length if the sum of both lists is less than it
        embed_length = message_max_length
    else:
        # Sets to max message length if there is only
        # one list. Otherwise divides the total embed
        # length by however many lists there are.
        embed_length = message_max_length // list_count

    if not skip_movies:
        create_embeds(movie_title, movies_str, movie_embed_colour,
                      embed_length)
    if not skip_tv:
        create_embeds(tv_title, tv_str, tv_embed_colour, embed_length)

    # Adds thumnail image to embeds if specified
    [embed.set_thumbnail(embed_thumbnail) for embed in webhook_embeds]

    # Sending webhook
    if webhook_embeds:
        try:
            webhook.send(message_title, embeds=webhook_embeds)
        except Exception as err:
            print("There was an error sending the message:", err)
    else:
        print("No new/specified media to notify about - message not sent.")

    # Ping uptime status monitor if specified
    if uptime_status:
        try:
            requests.get(f"{uptime_status}{int(time.time()) - start_time}")
        except Exception as err:
            print(f"There was an error pinging the uptime status monitor:",
                  err)
