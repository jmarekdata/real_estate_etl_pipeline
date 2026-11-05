import os
import re
import scrapy
import psycopg2


class OtodomSpider(scrapy.Spider):
    name = "otodom"

    # Scrapy 2.19.0 (AsyncCrawlerProcess) wymaga start_urls zamiast starego start_requests()
    start_urls = ["file:///app/scrapers/debug_otodom.html"]

    custom_settings = {
        "ROBOTSTXT_OBEY": False,
        "LOG_LEVEL": "INFO",
        "STATS_DUMP": False,  # Wyłącza długi słownik statystyk na końcu, który przewijał terminal
    }

    def parse(self, response):
        print("\n" + "=" * 65, flush=True)
        print("🚀 START ELT: Odczytano plik debug_otodom.html! Wyciągam oferty...", flush=True)

        extracted_rows = []
        seen_urls = set()

        # Wyciągamy wszystkie oferty bezpośrednio ze zrzutu HTML z Łodzi
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
            loc_match = re.search(r"([^|]*Łódź[^|]*)", raw_card_text)

            extracted_rows.append((
                "otodom",
                full_url,
                title or "Oferta mieszkania Łódź",
                price_match.group(1).strip() if price_match else "Brak",
                area_match.group(1).strip() if area_match else "Brak",
                rooms_match.group(1).strip() if rooms_match else "Brak",
                loc_match.group(1).strip() if loc_match else "Łódź, łódzkie",
                raw_card_text[:1000],
                "2026-11-01 12:00:00",
            ))

        # Rekordy kontrolne (w tym oferty z Twojego screena + duplikat z OLX i historia cen pod dbt)
        seed_records = [
            (
                "otodom",
                "https://www.otodom.pl/pl/oferta/mieszkanie-6-sierpnia-polesie-ID1",
                "2-pokojowe mieszkanie 88m2 + balkon Bez Prowizji",
                "899 000",
                "88.55",
                "2",
                "ul. 6 Sierpnia, Stare Polesie, Polesie, Łódź, łódzkie",
                "Historyczny odczyt ceny sprzed obniżki (wersjonowanie)",
                "2026-10-15 10:00:00",
            ),
            (
                "otodom",
                "https://www.otodom.pl/pl/oferta/mieszkanie-6-sierpnia-polesie-ID1",
                "2-pokojowe mieszkanie 88m2 + balkon Bez Prowizji",
                "874 431",
                "88.55",
                "2",
                "ul. 6 Sierpnia, Stare Polesie, Polesie, Łódź, łódzkie",
                "Aktualny odczyt ceny po obniżce (wersjonowanie) | Murapol Deweloper | 3 piętro",
                "2026-11-05 12:00:00",
            ),
            (
                "olx",
                "https://www.olx.pl/d/oferta/mieszkanie-6-sierpnia-polesie-CID3-ID1",
                "Mieszkanie 2 pokoje 88.55m2 Łódź Stare Polesie ul. 6 Sierpnia",
                "874 431",
                "88.55",
                "2",
                "ul. 6 Sierpnia, Stare Polesie, Polesie, Łódź, łódzkie",
                "Duplikat tej samej oferty wystawiony na portalu OLX (deduplikacja)",
                "2026-11-05 12:05:00",
            ),
            (
                "otodom",
                "https://www.otodom.pl/pl/oferta/mieszkanie-inflancka-baluty-ID2",
                "3-pokojowe mieszkanie 60m2 + balkon",
                "612 060",
                "60.6",
                "3",
                "ul. Inflancka 120, Marysin, Bałuty, Łódź, łódzkie",
                "Madey Development Sp. z o.o 4 Sp. komandytowa | 2 piętro",
                "2026-11-05 12:10:00",
            ),
            (
                "otodom",
                "https://www.otodom.pl/pl/oferta/mieszkanie-zagloby-widzew-ID3",
                "62m² Janów- Olechów 3 pokoje , BALKON, stan do zamieszkania",
                "494 000",
                "62.5",
                "3",
                "ul. Jana Onufrego Zagłoby, Olechów, Widzew, Łódź, łódzkie",
                "Centrum Nieruchomości sc Julita Galant, Monika Strycharek | 4 piętro",
                "2026-11-05 12:15:00",
            ),
            (
                "otodom",
                "https://www.otodom.pl/pl/oferta/mieszkanie-piekarska-baluty-ID4",
                "3-pokojowe mieszkanie 58m2 + loggia",
                "616 390",
                "58.15",
                "3",
                "ul. Piekarska, Stare Bałuty, Bałuty, Łódź, łódzkie",
                "Oferta deweloperska | 10 piętro",
                "2026-11-05 12:20:00",
            ),
        ]
        extracted_rows.extend(seed_records)

        self.save_to_postgres(extracted_rows)

    def save_to_postgres(self, rows):
        conn = psycopg2.connect(
            host=os.getenv("DB_HOST", "localhost"),
            port=os.getenv("DB_PORT", "5432"),
            dbname=os.getenv("DB_NAME", "real_estate"),
            user=os.getenv("DB_USER", "admin"),
            password=os.getenv("DB_PASSWORD", "adminpassword"),
        )
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
        cur.execute("TRUNCATE TABLE raw.listings;")

        insert_sql = """
            INSERT INTO raw.listings (
                source_portal, offer_url, title, price_raw,
                area_raw, rooms_raw, location_raw, raw_payload, scraped_at
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s);
        """
        cur.executemany(insert_sql, rows)
        conn.commit()

        # Sprawdzamy bezpośrednio w bazie ile rekordów fizycznie siedzi w tabeli
        cur.execute("SELECT COUNT(*) FROM raw.listings;")
        total_in_db = cur.fetchone()[0]

        cur.close()
        conn.close()

        print(f"✅ SUKCES! W bazie PostgreSQL (raw.listings) siedzi fizycznie {total_in_db} ofert!", flush=True)
        print("=" * 65 + "\n", flush=True)