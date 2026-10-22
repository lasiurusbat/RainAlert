"""The cities RainAlert links to from its city index and its sitemap.

The app can look up any city the geocoder knows, so this list is not a
limit on what the site can do — it is the seed of the crawlable part of the
site. Every city on it has its own address, ``/city/<slug>``, and every one
of those addresses is a real page with the real forecast on it.

Two things are worth knowing about the list:

* **The slug is the address, the name is the lookup.** A slug cannot carry
  accents or punctuation, so ``sao-paulo`` has to become ``Sao Paulo``
  before it reaches the geocoder. The name is what the geocoder needs.
* **The names are the ones people type.** They are deliberately plain, so
  that a city in the list and a city typed into the search box resolve to
  the same place, and the page shows the same name in both cases.

The list is short on purpose. Every address in it is a page the app will
have to fetch a forecast for, and the geocoder is rate-limited, so a
crawl of the whole list is a burst of requests. The site works for every
city the geocoder knows; this list is only the front door.
"""

# The slug is the address, the name is what the geocoder is asked for.
CURATED_CITIES = (
    ("amsterdam", "Amsterdam"),
    ("athens", "Athens"),
    ("atlanta", "Atlanta"),
    ("auckland", "Auckland"),
    ("bangkok", "Bangkok"),
    ("barcelona", "Barcelona"),
    ("beijing", "Beijing"),
    ("belfast", "Belfast"),
    ("berlin", "Berlin"),
    ("birmingham", "Birmingham"),
    ("boston", "Boston"),
    ("brisbane", "Brisbane"),
    ("bristol", "Bristol"),
    ("brussels", "Brussels"),
    ("bucharest", "Bucharest"),
    ("budapest", "Budapest"),
    ("buenos-aires", "Buenos Aires"),
    ("cairo", "Cairo"),
    ("calgary", "Calgary"),
    ("cape-town", "Cape Town"),
    ("chicago", "Chicago"),
    ("copenhagen", "Copenhagen"),
    ("dallas", "Dallas"),
    ("delhi", "Delhi"),
    ("denver", "Denver"),
    ("dhaka", "Dhaka"),
    ("dubai", "Dubai"),
    ("dublin", "Dublin"),
    ("durban", "Durban"),
    ("edinburgh", "Edinburgh"),
    ("frankfurt", "Frankfurt"),
    ("geneva", "Geneva"),
    ("glasgow", "Glasgow"),
    ("hanoi", "Hanoi"),
    ("havana", "Havana"),
    ("helsinki", "Helsinki"),
    ("hong-kong", "Hong Kong"),
    ("honolulu", "Honolulu"),
    ("houston", "Houston"),
    ("istanbul", "Istanbul"),
    ("jakarta", "Jakarta"),
    ("johannesburg", "Johannesburg"),
    ("kuala-lumpur", "Kuala Lumpur"),
    ("lagos", "Lagos"),
    ("las-vegas", "Las Vegas"),
    ("lima", "Lima"),
    ("lisbon", "Lisbon"),
    ("liverpool", "Liverpool"),
    ("london", "London"),
    ("los-angeles", "Los Angeles"),
    ("madrid", "Madrid"),
    ("manchester", "Manchester"),
    ("manila", "Manila"),
    ("melbourne", "Melbourne"),
    ("mexico-city", "Mexico City"),
    ("milan", "Milan"),
    ("montreal", "Montreal"),
    ("mumbai", "Mumbai"),
    ("munich", "Munich"),
    ("nairobi", "Nairobi"),
    ("new-orleans", "New Orleans"),
    ("new-york", "New York"),
    ("osaka", "Osaka"),
    ("oslo", "Oslo"),
    ("ottawa", "Ottawa"),
    ("paris", "Paris"),
    ("perth", "Perth"),
    ("philadelphia", "Philadelphia"),
    ("phoenix", "Phoenix"),
    ("portland", "Portland"),
    ("prague", "Prague"),
    ("rio-de-janeiro", "Rio de Janeiro"),
    ("riyadh", "Riyadh"),
    ("rome", "Rome"),
    ("san-francisco", "San Francisco"),
    ("santiago", "Santiago"),
    ("sao-paulo", "Sao Paulo"),
    ("seattle", "Seattle"),
    ("seoul", "Seoul"),
    ("shanghai", "Shanghai"),
    ("singapore", "Singapore"),
    ("stockholm", "Stockholm"),
    ("sydney", "Sydney"),
    ("taipei", "Taipei"),
    ("tel-aviv", "Tel Aviv"),
    ("tokyo", "Tokyo"),
    ("toronto", "Toronto"),
    ("vancouver", "Vancouver"),
    ("vienna", "Vienna"),
    ("warsaw", "Warsaw"),
    ("washington-dc", "Washington, D.C."),
    ("zurich", "Zurich"),
)

# The same list as a lookup, so the app can go from a name to a slug and
# from a slug to a name without walking the tuple.
CITY_NAMES = {name.lower(): slug for slug, name in CURATED_CITIES}
CITY_SLUGS = {slug: name for slug, name in CURATED_CITIES}
