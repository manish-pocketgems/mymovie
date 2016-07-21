
import json
import logging
import urllib
import webapp2

from google.appengine.api import memcache, urlfetch
from google.appengine.ext import ndb

from helper import write_mako_template

# API related constants
TMDB_API_SEARCH_URL = 'https://api.themoviedb.org/3/search/movie'
TMDB_API_VIDEO_URL = 'https://api.themoviedb.org/3/movie/%s/videos?api_key=%s'
API_KEY = 'cb6b724d63906d290169b30bdd60c3a1'

# Memcache related constants
MEMCACHE_ALL_MOVIES_KEY = 'top_movies_mc'
MEMCACHE_KEY_PREFIX = 'movies_mc:'
MEMCACHE_TIMEOUT = 30


# Movie model definition
class Movie(ndb.Model):
    # disable builtin memcache and context cache
    _use_cache = _use_memcache = False
    title = ndb.StringProperty(indexed=True, required=True)
    overview = ndb.TextProperty(indexed=False, required=True)
    trailer = ndb.StringProperty(indexed=False, required=True)
    poster = ndb.StringProperty(indexed=False, required=True)
    average_rating = ndb.ComputedProperty(lambda self: self.calc_avg_rating(),
                                          indexed=True)
    total_rating = ndb.IntegerProperty(indexed=True, default=0)
    num_ratings = ndb.IntegerProperty(indexed=True, default=0)

    @staticmethod
    def get_all():
        movies = memcache.get(MEMCACHE_ALL_MOVIES_KEY)
        if movies:
            logging.info('Read successfully from memcache')
        else:
            movies = Movie.query().order(-Movie.average_rating).fetch(80)
            if not memcache.add(MEMCACHE_ALL_MOVIES_KEY, movies,
                                MEMCACHE_TIMEOUT):
                logging.error('Memcache add failed')
        return movies

    @property
    def movie_id(self):
        return self.key.id()

    def incr_rating(self, rating):
        """Increment the rating for a movie"""
        self.total_rating += int(rating)
        self.num_ratings += 1

    def _post_put_hook(self, future):
        """Hook that runs after put()"""
        mc_key = MEMCACHE_KEY_PREFIX + str(self.movie_id)
        memcache.delete(mc_key)

    @classmethod
    def get_from_cache(cls, movie_id):
        """Get an entity from cache layer"""
        mc_key = MEMCACHE_KEY_PREFIX + str(movie_id)
        movie = memcache.get(mc_key)
        if movie is None:
            movie = Movie.get_by_id(int(movie_id))
            if movie:
                memcache.add(mc_key, movie, MEMCACHE_TIMEOUT)
        return movie

    def calc_avg_rating(self):
        """Calculate avg rating"""
        if self.num_ratings == 0:
            return 0
        return self.total_rating / self.num_ratings


# Handler for the homepage
class MainPage(webapp2.RequestHandler):
    PATH = '/'

    def get(self):
        movies = Movie.get_all()
        write_mako_template(self, 'templates/main.html', movies=movies)


class SubmitMovieHandler(webapp2.RequestHandler):
    PATH = '/submit'

    def get(self):
        write_mako_template(self, 'templates/submit.html', error=None)

    def post(self):
        title = self.request.get('title')
        overview = self.request.get('overview')
        poster = self.request.get('poster')
        trailer_url = self.request.get('trailer_url')

        movie = Movie.query().filter(Movie.title == title).get()
        if not movie:
            movie = Movie(title=title,
                          overview=overview,
                          trailer=trailer_url,
                          poster=poster)
            movie.put()
            if memcache.delete(MEMCACHE_ALL_MOVIES_KEY) == memcache.DELETE_NETWORK_FAILURE:
                logging.info('deleting memcache all movies key failed')
            logging.info('deleting memcache all movies key')
        self.redirect('/')


class SearchHandler(webapp2.RequestHandler):
    PATH = '/search'

    def get(self):
        YOUTUBE_EMBED_URL = "https://www.youtube.com/embed/"
        movie_name = self.request.get('movie_name').strip()
        params = dict(query=movie_name, api_key=API_KEY)
        url = TMDB_API_SEARCH_URL + "?" + urllib.urlencode(params)
        try:
            resp = urlfetch.fetch(url, validate_certificate=True)
            if resp.status_code != 200:
                raise ValueError("Error response: %s" % resp.code)
            res = json.loads(resp.content)
            results = []
            for movie_info in res.get('results'):
                title = (movie_info.get('title') or
                         movie_info.get('original_title'))
                overview = movie_info.get('overview')
                poster_path = movie_info.get('poster_path')
                if not poster_path:
                    continue
                poster_path = 'https://image.tmdb.org/t/p/w500' + poster_path
                movie_id = movie_info.get('id')

                # Get trailer url from imdb
                movie_url = TMDB_API_VIDEO_URL % (movie_id, API_KEY)
                logging.info('MOVIE URL : %s\n' % movie_url)
                resp = urlfetch.fetch(movie_url, validate_certificate=True)
                if resp.status_code != 200:
                    continue
                resp = json.loads(resp.content)
                resp = resp.get('results', [])
                if not resp:
                    continue
                trailer_url = YOUTUBE_EMBED_URL + resp[0].get('key')
                info = dict(title=title, overview=overview,
                            poster=poster_path,
                            trailer_url=trailer_url)
                results.append(info)
            if results:
                write_mako_template(self, 'templates/search.html',
                                    results=results)
            else:
                write_mako_template(self, 'templates/submit.html',
                                    error="No results found")

        except urlfetch.Error as e:
            logging.exception(e)
        except ValueError as e:
            logging.exception(e)


class ViewMovieHandler(webapp2.RequestHandler):
    PATH = "/movie/([0-9]+)"

    def get(self, movie_id):
        movie = Movie.get_from_cache(movie_id)
        if not movie:
                return self.response.write('Movie not found')

        write_mako_template(self, 'templates/view_movie.html', movie=movie)

    @ndb.transactional
    def post(self, movie_id):
        logging.info("MOVIE ID : %s", movie_id)
        rating = self.request.get('rating')

        # Update rating data
        movie = Movie.get_by_id(int(movie_id))
        movie.incr_rating(rating)
        movie.put()

        self.redirect('/')


def get_routes():
    routes = [(MainPage.PATH, MainPage),
              (SubmitMovieHandler.PATH, SubmitMovieHandler),
              (SearchHandler.PATH, SearchHandler),
              (ViewMovieHandler.PATH, ViewMovieHandler)
              ]
    return routes

application = webapp2.WSGIApplication(get_routes(), debug=True)
