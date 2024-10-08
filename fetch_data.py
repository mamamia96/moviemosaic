"""
Fetch Data from rss feed then transform data into MovieClass objects.
Maybe we split this up into a fetch_data.py and a transform_data.py?
"""

from bs4 import BeautifulSoup
import requests
from datetime import datetime
import re
from tmdb_fetch import get_director, get_tmdb_poster_url
import aiohttp
import asyncio
import aiofiles
from moviecell import MovieCell
import os
from PIL import Image
from io import BytesIO
from db_cache import dbCache

async def download(name_url: tuple[str], session, db_cache: dbCache):
    filename, url = name_url

    # file already exists or there is no poster to download
    if db_cache.lookup(filename) or not url:
        return
    
    # stream image data from requests
    image_data: bytes
    async with session.get(url) as response:
        image_data = await response.read()

    with Image.open(BytesIO(image_data)) as img:
        img = img.resize((120, 180))
        format = img.format if img.format else 'PNG'
        with BytesIO() as buffer:
            img.save(buffer, format=format)
            resized_image_data = buffer.getvalue()

    db_cache.push(filename=filename, image_data=resized_image_data)

    # put in shared cache object here
    # it will check if 'filename' already exists
    # if it does then just return no further action needed
    # else call function regularly
    # async with session.get(url) as response:
    #     async with aiofiles.open(filename, "wb") as f:
    #         await f.write(await response.read())

async def download_all(name_urls: list[tuple], db_cache: dbCache):
    async with aiohttp.ClientSession() as session:
        await asyncio.gather(
            *[download(name_url, session=session, db_cache=db_cache) for name_url in name_urls]
        )

# going to make this into a class to avoid duplicate calls because front-end makes calls here to determine if user valid
# every instance of Scraper needs to be tied to a server-side session
class Scraper:
    '''
    Scrape data from rss feed and return content.
    Can also check for invalid rss feed. 
    '''
    _rss_feed: bytes
    _username: str

    
    def __init__(self, username: str) -> None:
        print('scraper created!')
        self._username = username
        self.load_rss_feed()

    def load_rss_feed(self) -> None:
        url = f'https://letterboxd.com/{self._username}/rss/'
        headers = {'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_10_1) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/39.0.2171.95 Safari/537.36'}
        r = requests.get(url, headers=headers)
        self._rss_feed = r.content
    
    def valid_rss_feed(self) -> bool:
        return not "<title>Letterboxd - Not Found</title>" in self._rss_feed.decode("utf-8")

    def get_rss_feed(self) -> bytes:
        return self._rss_feed

class Transformer:
    '''
    Takes data from rss feed and transforms into usable state for building MovieCell objects.
    '''
    _username: str
    _mode: int
    _date: datetime
    _movies: list[str]
    _feed_content: bytes

    def __init__(self, username: str, mode: int, date: datetime, feed_content: bytes):
        self._username = username
        self._mode = mode
        self._date = date
        self._feed_content = feed_content
        print('transformer created!')
    
    def load_movies(self) -> None:
        self._movies = self.get_valid_movies()

    def get_items(self) -> list[str]:
        # remove duplicate items here to avoid complicating things downstream


        soup = BeautifulSoup(self._feed_content, 'xml')
        return soup.find_all('item')

    def remove_duplicate_movies(self, items: list):
        # abomination of a function :)
        def get_movie_title(item) -> str:
            return item.find('letterboxd:filmTitle').string
        

        title_locs = {}
        for index, item in enumerate(items):
            title = get_movie_title(item)
            if title in title_locs:
                title_locs[title].append(index)
            else:
                title_locs[title] = [index]

        keep_indices = set([loc[0] for loc in title_locs.values()])
        return [item for index, item in enumerate(items) if index in keep_indices]

    def get_valid_movies(self):
        def is_movie(item) -> bool:
            return str(item.find('link')).find(f'https://letterboxd.com/{self._username}/list/') == -1 

        def watched_this_month(item) -> bool:
            # if 'Departed' in str(item):
            #     print(f'DEPARTED WATCH DATE {get_watched_date(item)} MONTH: {get_watched_date(item).month}')
            watched_date = get_watched_date(item)
            return watched_date.month == self._date.month and watched_date.year == self._date.year
        
        def has_watched_date(item) -> bool:
            watched_date = item.find('letterboxd:watchedDate')
            return not watched_date is None
        
        def get_watched_date(item) -> datetime:
            date_val = item.find('letterboxd:watchedDate')
            date_split = date_val.string.split('-')
            # date_split = re.split(pattern='<|>', string=str(item.find("letterboxd:watchedDate")))[2].split('-')
            return datetime(year=int(date_split[0]), month=int(date_split[1]), day=int(date_split[2]))

        # ensure item has watched date field
        items = list(filter(has_watched_date, self.get_items()))

        # remove duplicate items
        items = self.remove_duplicate_movies(items)

        # sorting movies by date
        items = sorted(filter(is_movie, items), key=lambda x: get_watched_date(x), reverse=True)

        # going to remove this 
        if self._mode == 0:
            # getting movies watched this month
            items = list(filter(watched_this_month, items))
        elif self._mode == 1:
            # getting last 30 movies (change 30 to config.json val?)
            items = list(items)[:30]

        return items
    
    def get_last_movie_date(self) -> datetime:
        def get_watched_date(item) -> datetime:
            date_split = re.split(pattern='<|>', string=str(item.find("letterboxd:watchedDate")))[2].split('-')
            date = datetime(year=int(date_split[0]), month=int(date_split[1]), day=int(date_split[2]))
            # print(f'getwatched date returning: {date.month}')
            return date

        if not self._movies:
            return None

        return get_watched_date(self._movies[-1])        
    
    def get_movie_titles(self) -> list:
        def get_movie_title(item) -> str:
            return re.split(pattern='<|>', string=str(item.find("letterboxd:filmTitle")))[2]

        return list(map(get_movie_title, self._movies))

    def get_movie_ratings(self) -> list:
        def get_movie_rating(item) -> int:
            rating_tag = item.find("letterboxd:memberRating")
            if not rating_tag: return -1
            return float(re.split(pattern='<|>', string=str(rating_tag))[2])

        return list(map(get_movie_rating, self._movies))
    
    def get_movie_directors(self) -> list:
        def get_tmdb_id(item) -> tuple[int, str]:
            # make this into a proper function ??
            # tmdb_movie_id = int(re.split(pattern='<|>', string=str(item.find("tmdb:movieId")))[0])
            # if tmdb_movie_id == -1:
                # tmdb_tv_id = int(re.split(pattern='<|>', string=str(item.find("tmdb:tvId")))[0])
            # we need to pass a flag to our tmdb_fetch functions telling them if it's a tv show or a movie**
            tmdb_id = item.find('tmdb:movieId')
            tmdb_type = 'mv'
            if not tmdb_id:
                tmdb_id = item.find('tmdb:tvId')
                tmdb_type = 'tv'

            return (int((tmdb_id.string)), tmdb_type)
        
        return [get_director(id, t) for id, t in map(get_tmdb_id, self._movies)]

        # return list(map(get_director, map(get_tmdb_id, self._movies)))
    
    def get_movie_poster_paths(self) -> list:
        def title_to_image_path(title: str):
            # make sure we are only taking alphanumeric characters
            title = re.sub(r'[^a-zA-Z0-9]', '', title)
            images_dir = os.environ['IMAGES_DIR']
            return images_dir + '/' + title.replace(' ', '-') + '.png'

        return list(map(title_to_image_path, self.get_movie_titles()))
    
    def get_movie_poster_urls(self) -> list:
        def get_tmdb_id(item) -> int:

            # tmdb_movie_id = int(re.split(pattern='<|>', string=str(item.find("tmdb:movieId")))[0])
            # if tmdb_movie_id == -1:
                # tmdb_tv_id = int(re.split(pattern='<|>', string=str(item.find("tmdb:tvId")))[0])
            # we need to pass a flag to our tmdb_fetch functions telling them if it's a tv show or a movie**
            tmdb_id = item.find('tmdb:movieId')
            tmdb_type = 'mv'
            if not tmdb_id:
                tmdb_id = item.find('tmdb:tvId')
                tmdb_type = 'tv'

            return (int((tmdb_id.string)), tmdb_type)

        return [get_tmdb_poster_url(id, t) for id, t in map(get_tmdb_id, self._movies)]

    def valid_movies_exist(self) -> bool:
        return len(self._movies)

'''
==MCB=CLASS==
GOAL: persist data from user per session

1. MCB is built
    a) rss_feed is built
    b) status is set T-> rss_feed exists F-> rss_feed not exists
    c) if status then we use Transformer funcs to build data
    d) if not status then no calls are made to transformer

'''

class MovieCellBuilder:
    _username: str
    _mode: int
    _movie_data: list
    _status: tuple[bool, str]

    def __init__(self, username: str, mode: int, db_cache: dbCache, status: tuple[bool, str] = None, movie_data: list = None) -> None:

        self._username = username
        self._mode = mode
        self._movie_data = None
        self._db_cache = db_cache

        if status and status[0]:
            # class has been rehydrated and it has no good data
            self._status = status
            self._movie_data = movie_data
            return

        
        if movie_data:
            # class has been rehydrated but data is good to go already
            self._movie_data = movie_data
            return

        # attempt to scrape data and set status to false is no data to scrape
        scraper = Scraper(username=username)
        if not scraper.valid_rss_feed():
            self._status = (False, f'{self._username} has no rss feed (most likely no letterboxd account)')
            return

        # attempt to transform scraped data and set status to false if data not viable
        transformer = Transformer(username=username, mode=self._mode, date=datetime.now(), feed_content=scraper.get_rss_feed())
        transformer.load_movies()
        if not transformer.valid_movies_exist():
            self._status = (False, f'{self._username} has no valid movies according to the criteria')
            return

        # transform good data and store
        self._movie_data = [
            transformer.get_movie_titles(),       # 0
            transformer.get_movie_directors(),    # 1
            transformer.get_movie_ratings(),      # 2
            transformer.get_movie_poster_paths(), # 3
            transformer.get_movie_poster_urls(),  # 4
            transformer.get_last_movie_date()
        ]

        # we need to make sure poster paths are taken out if there is no url
        for index, url in enumerate(self._movie_data[4]):
            if not url:
                self._movie_data[3][index] = None

        # set status so we know data is good
        self._status = (True, f'movie data for {self._username} good')

    def get_last_movie_date(self) -> datetime:
        if not self._movie_data or self._mode == 0:
            return None
        return self._movie_data[5]

    def get_status(self) -> tuple[bool, str]:
        return self._status

    def build_cells(self) -> list[MovieCell]:
        # download posters
        asyncio.run(download_all(zip(self._movie_data[3], self._movie_data[4]), self._db_cache))

        # collect all needed components of MovieCell from self._transformer
        return [
            MovieCell(*movie_tuple)
            for movie_tuple in zip(
                self._movie_data[0],
                self._movie_data[1],
                self._movie_data[2],
                self._movie_data[3]
            )
        ]