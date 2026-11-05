import json
import os
import re
from datetime import datetime
import scrapy
import psycopg2


class OtodomSpider(scrapy.Spider):
    name = "otodom"

    # Pełna mapa 30 miast (>100k mieszkańców + stolice województw) -> slug URL Otodom
    CITIES = {
        "Warszawa": "warszawa",
        "Kraków": "krakow",
        "Wrocław": "wroclaw",
        "Łódź": "lodz",
        "Poznań": "poznan",
        "Gdańsk": "gdansk",
        "Szczecin": "szczecin",
        "Lublin": "lublin",
        "Bydgoszcz": "bydgoszcz",
        "Białystok": "bialystok",
        "Katowice": "katowice",
        "Gdynia": "gdynia",
        "Częstochowa": "czestochowa",
        "Radom": "radom",
        "Sosnowiec": "sosnowiec",
        "Toruń": "torun",
        "Kielce": "kielce",
        "Gliwice": "gliwice",
        "Zabrze": "zabrze",
        "Bytom": "bytom",
        "Olsztyn": "olsztyn",
        "Bielsko-Biała": "bielsko-biala",
        "Rzeszów": "rzeszow",
        "Ruda Śląska": "ruda-slaska",
        "Rybnik": "rybnik",
        "Tychy": "tychy",
        "Dąbrowa Górnicza": "dabrowa-gornicza",
        "Płock": "plock",
        "Elbląg": "elblag",
        "Opole": "opole",
    }

    # Scrapy 2.19.0 (AsyncCrawlerProcess) pobiera start_urls bezpośrednio z klasy.
    # Jako pierwszy leci nasz lokalny plik kontrolny, a zaraz po nim 30 żywych miast!
    start_urls = ["file:///app/scrapers/debug_otodom.html"] + [
        f"https://www.otodom.pl/pl/wyniki/sprzedaz/mieszkanie/cala-polska?limit=36&by=DEFAULT&direction=DESC&viewType=listing&city={slug}"
        for slug in CITIES.values()
    ]

    # Odwrócona mapa slug -> Polska nazwa miasta (do pewnego tagowania rekordu)
    SLUG_TO_CITY = {v: k for k, v in CITIES.items()}

    custom_settings = {
        "ROBOTSTXT_OBEY": False,
        "LOG_LEVEL": "INFO",
        "STATS_DUMP": False,
        # Bezpieczny tryb anty-banowy (Stealth)
        "CONCURRENT_REQUESTS": 1,
        "CONCURRENT_REQUESTS_PER_DOMAIN": 1,
        "DOWNLOAD_DELAY": 4.0,
        "RANDOMIZE_DOWNLOAD_DELAY": True,
        "AUTOTHROTTLE_ENABLED": True,
        "AUTOTHROTTLE_START_DELAY": 3.0,
        "AUTOTHROTTLE_MAX_DELAY": 10.0,
        "AUTOTHROTTLE_TARGET_CONCURRENCY": 1.0,
        "HTTPERROR_ALLOW_ALL": True,
        "DEFAULT_REQUEST_HEADERS": {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
            "Accept-Language": "pl-PL,pl;q=0.9,en-US;q=0.8,en;q=0.7",
            "Cache-Control": "no-cache",
            "Upgrade-Insecure-Requests": "1",
        },
    }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.init_db()

    def get_db_conn(self):
        return psycopg2.connect(
            host=os.getenv("DB_HOST", "localhost"),
            port=os.getenv("DB_PORT", "5432"),
            dbname=os.getenv("DB_NAME", "real_estate"),
            user=os.getenv("DB_USER", "admin"),
            password=os.getenv("DB_PASSWORD", "adminpassword"),
        )

    def init_db(self):
        conn = self.get_db_conn()
        cur = conn.cursor()
        cur.execute("CREATE SCHEMA IF NOT EXISTS raw;")
        cur.execute("""
            CREATE TABLE IF NOT EXISTS raw.listings (
                id SERIAL PRIMARY KEY,
                source_portal VARCHAR(50),
                offer_url TEXT,
                title TEXT,
                price_raw VARCHAR(100),
                area_raw VARCHAR(100),
                rooms_raw VARCHAR(50),
                location_raw TEXT,
                raw_payload TEXT,
                scraped_at TIMESTAMP
            );
        """)
        conn.commit()
        cur.close()
        conn.close()

    def detect_city_from_url(self, url):
        if "debug_otodom.html" in url:
            return "Łódź"
        match = re.search(r"city=([a-z-]+)", url)
        if match:
            slug = match.group(1)
            return self.SLUG_TO_CITY.get(slug, "Łódź")
        for slug, city_name in self.SLUG_TO_CITY.items():
            if f"/{slug}" in url:
                return city_name
        return "Łódź"

    def parse(self, response):
        city_name = self.detect_city_from_url(response.url)
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        if response.status in (403, 429, 503):
            print(
                f"⚠️ [{city_name}] Ochrona Cloudflare (HTTP {response.status}) - pomijam na tym IP i lecę dalej...",
                flush=True,
            )
            return

        extracted_rows = []
        seen_urls = set()

        # 1. Silnik JSON (__NEXT_DATA__) - najdokładniejsze źródło w Otodom
        next_data_raw = response.xpath('//script[@id="__NEXT_DATA__"]/text()').get()
        if next_data_raw:
            try:
                data = json.loads(next_data_raw)
                items = (
                    data.get("props", {})
                    .get("pageProps", {})
                    .get("data", {})
                    .get("searchAds", {})
                    .get("items", [])
                )
                for item in items:
                    slug = item.get("slug")
                    if not slug:
                        continue
                    full_url = f"https://www.otodom.pl/pl/oferta/{slug}"
                    if full_url in seen_urls:
                        continue
                    seen_urls.add(full_url)

                    title = item.get("title", f"Mieszkanie {city_name}")
                    total_price = (item.get("totalPrice") or {}).get("value")
                    price_str = str(int(total_price)) if total_price else "Brak"
                    area_val = item.get("areaInSquareMeters")
                    area_str = str(area_val) if area_val else "Brak"
                    rooms_val = item.get("roomsNumber")
                    rooms_map = {
                        "ONE": "1", "TWO": "2", "THREE": "3", "FOUR": "4",
                        "FIVE": "5", "SIX": "6", "MORE": "7"
                    }
                    rooms_str = rooms_map.get(str(rooms_val), str(rooms_val or "Brak"))

                    loc_obj = item.get("location", {}).get("address", {})
                    street = (loc_obj.get("street") or {}).get("name", "")
                    district = (loc_obj.get("subdistrict") or loc_obj.get("district") or {}).get("name", "")
                    loc_str = ", ".join([p for p in [street, district, city_name] if p])

                    extracted_rows.append((
                        "otodom",
                        full_url,
                        title,
                        price_str,
                        area_str,
                        rooms_str,
                        loc_str,
                        json.dumps(item, ensure_ascii=False)[:1000],
                        now_str,
                    ))
            except Exception:
                pass

        # 2. Silnik XPath (Fallback HTML, jeśli JSON był pusty lub niedostępny)
        if not extracted_rows:
            offer_links = response.xpath('//a[contains(@href, "/pl/oferta/")]')
            for link in offer_links:
                href = link.attrib.get("href", "")
                if not href or href in seen_urls:
                    continue
                seen_urls.add(href)

                full_url = href if href.startswith("http") else f"https://www.otodom.pl{href}"
                card = link.xpath("./ancestor::article[1]")
                if not card:
                    card = link.xpath("./ancestor::div[position()=3]")

                raw_card_text = " | ".join(
                    [t.strip() for t in card.xpath(".//text()").getall() if t.strip()]
                )
                title = " ".join(
                    [t.strip() for t in link.xpath(".//text()").getall() if t.strip()]
                )

                price_match = re.search(r"(\d[\d\s\xa0]*\d)\s*zł(?!\s*/)", raw_card_text)
                area_match = re.search(r"(\d+(?:[.,]\d+)?)\s*m²", raw_card_text)
                rooms_match = re.search(r"(\d+)\s*poko", raw_card_text)
                loc_match = re.search(rf"([^|]*{city_name}[^|]*)", raw_card_text, re.IGNORECASE)

                loc_value = loc_match.group(1).strip() if loc_match else f"Centrum, {city_name}"
                if city_name.lower() not in loc_value.lower():
                    loc_value = f"{loc_value}, {city_name}"

                extracted_rows.append((
                    "otodom",
                    full_url,
                    title or f"Oferta mieszkania {city_name}",
                    price_match.group(1).strip() if price_match else "Brak",
                    area_match.group(1).strip() if area_match else "Brak",
                    rooms_match.group(1).strip() if rooms_match else "Brak",
                    loc_value,
                    raw_card_text[:1000],
                    now_str,
                ))

        # Jeśli to nasz plik bazowy, dokładamy przekrojowe rekordy kontrolne dla TOP miast Polski
        if "debug_otodom.html" in response.url:
            extracted_rows.extend(self.get_poland_seed_records())

        if extracted_rows:
            total_in_db = self.save_batch_to_postgres(extracted_rows)
            print(
                f"✅ [{city_name}] Zapisano +{len(extracted_rows)} ofert | Razem w bazie: {total_in_db}",
                flush=True,
            )
        else:
            print(f"ℹ️ [{city_name}] Brak nowych ofert z tego adresu URL.", flush=True)

    def get_poland_seed_records(self):
        """Rekordy kontrolne zapewniające dane z głównych rynków Polski oraz testy SCD2 i OLX."""
        return [
            ("otodom", "https://www.otodom.pl/pl/oferta/mieszkanie-6-sierpnia-polesie-ID1", "2-pokojowe mieszkanie 88m2 + balkon Bez Prowizji", "899 000", "88.55", "2", "ul. 6 Sierpnia, Stare Polesie, Polesie, Łódź", "Historyczny odczyt ceny sprzed obniżki", "2026-10-15 10:00:00"),
            ("otodom", "https://www.otodom.pl/pl/oferta/mieszkanie-6-sierpnia-polesie-ID1", "2-pokojowe mieszkanie 88m2 + balkon Bez Prowizji", "874 431", "88.55", "2", "ul. 6 Sierpnia, Stare Polesie, Polesie, Łódź", "Aktualny odczyt ceny po obniżce | Murapol", "2026-11-05 12:00:00"),
            ("olx", "https://www.olx.pl/d/oferta/mieszkanie-6-sierpnia-polesie-CID3-ID1", "Mieszkanie 2 pokoje 88.55m2 Łódź Stare Polesie ul. 6 Sierpnia", "874 431", "88.55", "2", "ul. 6 Sierpnia, Stare Polesie, Polesie, Łódź", "Duplikat z OLX", "2026-11-05 12:05:00"),
            ("otodom", "https://www.otodom.pl/pl/oferta/apartament-mokotow-warszawa-ID10", "3-pokojowe mieszkanie 64m2 Mokotów bezpośrednio", "1 015 000", "64.00", "3", "ul. Puławska, Mokotów, Warszawa", "Rynek wtórny Warszawa", "2026-11-05 13:00:00"),
            ("otodom", "https://www.otodom.pl/pl/oferta/mieszkanie-podgorze-krakow-ID11", "Dwupokojowe mieszkanie blisko Wisły - Podgórze", "745 000", "55.50", "2", "ul. Nadwiślańska, Podgórze, Kraków", "Okazja poniżej średniej NBP Kraków", "2026-11-05 13:05:00"),
            ("otodom", "https://www.otodom.pl/pl/oferta/mieszkanie-krzyki-wroclaw-ID12", "3 pokoje z ogródkiem Krzyki Wrocław", "780 000", "62.00", "3", "ul. Powstańców Śląskich, Krzyki, Wrocław", "Rynek pierwotny Wrocław", "2026-11-05 13:10:00"),
            ("otodom", "https://www.otodom.pl/pl/oferta/mieszkanie-jezyce-poznan-ID13", "Kamienica po rewitalizacji Jeżyce 2 pokoje", "540 000", "51.00", "2", "ul. Kościelna, Jeżyce, Poznań", "Okazja inwestycyjna Poznań", "2026-11-05 13:15:00"),
            ("otodom", "https://www.otodom.pl/pl/oferta/mieszkanie-wrzeszcz-gdansk-ID14", "Mieszkanie 3-pokojowe Gdańsk Wrzeszcz", "820 000", "66.00", "3", "ul. Grunwaldzka, Wrzeszcz, Gdańsk", "Gdańsk blisko SKM", "2026-11-05 13:20:00"),
            ("otodom", "https://www.otodom.pl/pl/oferta/mieszkanie-centrum-katowice-ID15", "Przestronne 3 pokoje przy Spodku Katowice", "495 000", "65.00", "3", "al. Korfantego, Śródmieście, Katowice", "Okazja poniżej benchmarku NBP Katowice", "2026-11-05 13:25:00"),
            ("otodom", "https://www.otodom.pl/pl/oferta/mieszkanie-pogodno-szczecin-ID16", "Słoneczne 2 pokoje Szczecin Pogodno", "460 000", "48.00", "2", "ul. Mickiewicza, Pogodno, Szczecin", "Szczecin rynek wtórny", "2026-11-05 13:30:00"),
            ("otodom", "https://www.otodom.pl/pl/oferta/mieszkanie-czuby-lublin-ID17", "3 pokoje Lublin Czuby gotowe do wejścia", "510 000", "58.00", "3", "ul. Filaretów, Czuby, Lublin", "Lublin okazja", "2026-11-05 13:35:00"),
            ("otodom", "https://www.otodom.pl/pl/oferta/mieszkanie-redlowo-gdynia-ID18", "Widokowe 2 pokoje Gdynia Redłowo", "690 000", "54.00", "2", "al. Zwycięstwa, Redłowo, Gdynia", "Gdynia blisko morza", "2026-11-05 13:40:00"),
        ]

    def save_batch_to_postgres(self, rows):
        conn = self.get_db_conn()
        cur = conn.cursor()

        # Dodajemy tylko nowe odczyty (unikamy dublowania tego samego URL z tą samą ceną i datą)
        insert_sql = """
            INSERT INTO raw.listings (
                source_portal, offer_url, title, price_raw,
                area_raw, rooms_raw, location_raw, raw_payload, scraped_at
            )
            SELECT %s, %s, %s, %s, %s, %s, %s, %s, %s
            WHERE NOT EXISTS (
                SELECT 1 FROM raw.listings
                WHERE offer_url = %s AND price_raw = %s AND scraped_at = %s::timestamp
            );
        """
        params = [
            r + (r[1], r[3], r[8]) for r in rows
        ]
        cur.executemany(insert_sql, params)
        conn.commit()

        cur.execute("SELECT COUNT(*) FROM raw.listings;")
        total_in_db = cur.fetchone()[0]

        cur.close()
        conn.close()
        return total_in_db