WITH raw_source AS (
    SELECT * FROM "real_estate"."raw"."listings"
),

cleaned AS (
    SELECT
        id AS raw_id,
        source_portal,
        offer_url,
        TRIM(title) AS title,
        NULLIF(REGEXP_REPLACE(price_raw, '[^0-9]', '', 'g'), '')::NUMERIC(12, 2) AS price_pln,
        NULLIF(REPLACE(REGEXP_REPLACE(area_raw, '[^0-9.,]', '', 'g'), ',', '.'), '')::NUMERIC(8, 2) AS area_sqm,
        NULLIF(REGEXP_REPLACE(rooms_raw, '[^0-9]', '', 'g'), '')::INT AS rooms_count,
        location_raw,
        CASE
            WHEN location_raw ILIKE '%Łódź%' OR offer_url ILIKE '%lodz%' THEN 'Łódź'
            WHEN location_raw ILIKE '%Warszawa%' OR offer_url ILIKE '%warszawa%' THEN 'Warszawa'
            WHEN location_raw ILIKE '%Wrocław%' OR offer_url ILIKE '%wroclaw%' THEN 'Wrocław'
            WHEN location_raw ILIKE '%Katowice%' OR offer_url ILIKE '%katowice%' THEN 'Katowice'
            WHEN location_raw ILIKE '%Kraków%' OR offer_url ILIKE '%krakow%' THEN 'Kraków'
            WHEN location_raw ILIKE '%Poznań%' OR offer_url ILIKE '%poznan%' THEN 'Poznań'
            WHEN location_raw ILIKE '%Gdańsk%' OR offer_url ILIKE '%gdansk%' THEN 'Gdańsk'
            ELSE 'Łódź'
        END AS city,
        CASE
            WHEN location_raw ILIKE '%Polesie%' THEN 'Polesie'
            WHEN location_raw ILIKE '%Bałuty%' THEN 'Bałuty'
            WHEN location_raw ILIKE '%Widzew%' THEN 'Widzew'
            WHEN location_raw ILIKE '%Górna%' THEN 'Górna'
            WHEN location_raw ILIKE '%Śródmieście%' THEN 'Śródmieście'
            ELSE 'Pozostałe'
        END AS district,
        raw_payload,
        scraped_at
    FROM raw_source
)

SELECT
    *,
    ROUND(price_pln / NULLIF(area_sqm, 0), 2) AS price_per_sqm,
    MD5(
        LOWER(city) || '|' ||
        LOWER(district) || '|' ||
        ROUND(area_sqm, 1)::TEXT || '|' ||
        COALESCE(rooms_count, 0)::TEXT
    ) AS property_fingerprint
FROM cleaned
WHERE price_pln IS NOT NULL
  AND area_sqm IS NOT NULL
  AND area_sqm > 10