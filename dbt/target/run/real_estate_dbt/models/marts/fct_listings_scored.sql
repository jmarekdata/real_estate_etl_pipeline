
  
    

  create  table "real_estate"."analytical"."fct_listings_scored__dbt_tmp"
  
  
    as
  
  (
    WITH latest_per_url AS (
    SELECT *
    FROM "real_estate"."analytical"."dim_price_history"
    WHERE is_current = TRUE
),

with_fingerprint AS (
    SELECT
        l.*,
        s.property_fingerprint
    FROM latest_per_url l
    JOIN "real_estate"."analytical"."stg_listings" s
      ON l.offer_url = s.offer_url
     AND l.valid_from = s.scraped_at
),

-- Postgres nie trawi DISTINCT wewnątrz funkcji okna, więc agregujemy to po staremu (GROUP BY)
portal_agg AS (
    SELECT
        property_fingerprint,
        COUNT(*) AS portal_listings_count,
        STRING_AGG(DISTINCT source_portal, ', ') AS listed_on_portals
    FROM with_fingerprint
    GROUP BY property_fingerprint
),

deduplicated AS (
    SELECT
        wf.property_fingerprint,
        wf.offer_url AS primary_offer_url,
        wf.source_portal AS primary_portal,
        wf.title,
        wf.city,
        wf.district,
        wf.area_sqm,
        wf.rooms_count,
        wf.price_pln,
        wf.price_per_sqm,
        wf.price_change_pln,
        wf.price_change_pct,
        wf.valid_from AS last_scraped_at,
        pa.portal_listings_count,
        pa.listed_on_portals,
        ROW_NUMBER() OVER (
            PARTITION BY wf.property_fingerprint
            ORDER BY CASE WHEN wf.source_portal = 'otodom' THEN 1 ELSE 2 END, wf.valid_from ASC
        ) AS dedup_rank
    FROM with_fingerprint wf
    JOIN portal_agg pa ON wf.property_fingerprint = pa.property_fingerprint
),

unique_properties AS (
    SELECT * FROM deduplicated WHERE dedup_rank = 1
),

market_benchmarks AS (
    SELECT
        *,
        ROUND(AVG(price_per_sqm) OVER (PARTITION BY city, district), 2) AS district_avg_sqm,
        CASE
            WHEN city = 'Łódź' THEN 8650.00
            WHEN city = 'Warszawa' THEN 16200.00
            WHEN city = 'Kraków' THEN 14100.00
            WHEN city = 'Wrocław' THEN 12800.00
            WHEN city = 'Gdańsk' THEN 12500.00
            WHEN city = 'Poznań' THEN 11200.00
            WHEN city = 'Katowice' THEN 8200.00
            ELSE 8650.00
        END AS nbp_benchmark_sqm
    FROM unique_properties
)

SELECT
    property_fingerprint,
    primary_portal,
    listed_on_portals,
    portal_listings_count,
    title,
    city,
    district,
    rooms_count,
    area_sqm,
    price_pln,
    price_per_sqm,
    price_change_pln,
    price_change_pct,
    district_avg_sqm,
    nbp_benchmark_sqm,
    ROUND(((price_per_sqm - district_avg_sqm) / NULLIF(district_avg_sqm, 0)) * 100, 2) AS vs_district_avg_pct,
    ROUND(((price_per_sqm - nbp_benchmark_sqm) / nbp_benchmark_sqm) * 100, 2) AS vs_nbp_benchmark_pct,
    CASE
        WHEN price_per_sqm <= nbp_benchmark_sqm * 0.95 THEN 'OKAZJA INWESTYCYJNA (Poniżej NBP)'
        WHEN price_per_sqm <= district_avg_sqm * 0.95 THEN 'PONIŻEJ ŚREDNIEJ DZIELNICY'
        WHEN price_per_sqm <= district_avg_sqm * 1.05 THEN 'CENA RYNKOWA'
        ELSE 'PRZEPŁACONA / PREMIUM'
    END AS investment_score,
    primary_offer_url,
    last_scraped_at
FROM market_benchmarks
ORDER BY price_per_sqm ASC
  );
  