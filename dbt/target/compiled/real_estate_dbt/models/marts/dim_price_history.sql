WITH staged AS (
    SELECT * FROM "real_estate"."analytical"."stg_listings"
),

versioned AS (
    SELECT
        offer_url,
        source_portal,
        title,
        city,
        district,
        area_sqm,
        rooms_count,
        price_pln,
        price_per_sqm,
        LAG(price_pln) OVER (
            PARTITION BY offer_url 
            ORDER BY scraped_at ASC
        ) AS previous_price_pln,
        scraped_at AS valid_from,
        LEAD(scraped_at) OVER (
            PARTITION BY offer_url 
            ORDER BY scraped_at ASC
        ) AS valid_to,
        ROW_NUMBER() OVER (
            PARTITION BY offer_url 
            ORDER BY scraped_at ASC
        ) AS version_number
    FROM staged
)

SELECT
    offer_url,
    source_portal,
    title,
    city,
    district,
    area_sqm,
    rooms_count,
    version_number,
    price_pln,
    previous_price_pln,
    COALESCE(price_pln - previous_price_pln, 0) AS price_change_pln,
    CASE 
        WHEN previous_price_pln IS NOT NULL AND previous_price_pln > 0 
        THEN ROUND(((price_pln - previous_price_pln) / previous_price_pln) * 100, 2)
        ELSE 0.00
    END AS price_change_pct,
    price_per_sqm,
    valid_from,
    valid_to,
    CASE WHEN valid_to IS NULL THEN TRUE ELSE FALSE END AS is_current
FROM versioned
ORDER BY offer_url, version_number