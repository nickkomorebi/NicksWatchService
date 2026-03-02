from app.adapters.chrono24_web import Chrono24WebAdapter
from app.adapters.ebay import EbayAdapter
from app.adapters.mercari_jp import MercariJpAdapter
from app.adapters.reddit import RedditAdapter
from app.adapters.web_search import WebSearchAdapter
from app.adapters.web_search_recent import WebSearchRecentAdapter
from app.adapters.yahoo_jp import YahooJpAdapter

ALL_ADAPTERS = [
    WebSearchAdapter(),
    WebSearchRecentAdapter(),
    EbayAdapter(),
    Chrono24WebAdapter(),
    RedditAdapter(),
    MercariJpAdapter(),
    YahooJpAdapter(),
]
