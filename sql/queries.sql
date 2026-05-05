-- QUERY: Q1_TOP_INVENTORS
SELECT i.inventor_id,
       i.name,
       COUNT(DISTINCT r.patent_id) AS patent_count
FROM inventors AS i
JOIN relationships AS r ON r.inventor_id = i.inventor_id
GROUP BY i.inventor_id, i.name
ORDER BY patent_count DESC
LIMIT 25;

-- QUERY: Q2_TOP_COMPANIES
SELECT c.company_id,
       c.name,
       COUNT(DISTINCT r.patent_id) AS patent_count
FROM companies AS c
JOIN relationships AS r ON r.company_id = c.company_id
GROUP BY c.company_id, c.name
ORDER BY patent_count DESC
LIMIT 25;

-- QUERY: Q3_TOP_COUNTRIES
SELECT COALESCE(NULLIF(TRIM(i.country), ''), '(unknown)') AS country,
       COUNT(DISTINCT r.patent_id) AS patent_count
FROM inventors AS i
JOIN relationships AS r ON r.inventor_id = i.inventor_id
GROUP BY country
ORDER BY patent_count DESC
LIMIT 25;

-- QUERY: Q4_YEARLY_TRENDS
SELECT year,
       COUNT(*) AS patents_in_year
FROM patents
WHERE year IS NOT NULL
GROUP BY year
ORDER BY year;

-- QUERY: Q5_JOIN_SAMPLE
SELECT p.patent_id,
       p.title,
       p.year,
       i.name AS inventor_name,
       i.country AS inventor_country,
       c.name AS company_name
FROM patents AS p
JOIN relationships AS r ON r.patent_id = p.patent_id
JOIN inventors AS i ON i.inventor_id = r.inventor_id
LEFT JOIN companies AS c ON c.company_id = r.company_id
ORDER BY p.patent_id
LIMIT 120;

-- QUERY: Q6_CTE_RECENT_INVENTORS
WITH recent_patents AS (
  SELECT patent_id
  FROM patents
  WHERE year >= 2000
),
recent_links AS (
  SELECT r.inventor_id, r.patent_id
  FROM relationships AS r
  JOIN recent_patents AS rp ON rp.patent_id = r.patent_id
),
counts AS (
  SELECT inventor_id,
         COUNT(DISTINCT patent_id) AS patent_count
  FROM recent_links
  GROUP BY inventor_id
)
SELECT i.inventor_id,
       i.name,
       c.patent_count
FROM counts AS c
JOIN inventors AS i ON i.inventor_id = c.inventor_id
ORDER BY c.patent_count DESC
LIMIT 60;

-- QUERY: Q7_RANKED_INVENTORS
WITH inventor_totals AS (
  SELECT i.inventor_id,
         i.name,
         COUNT(DISTINCT r.patent_id) AS patent_count
  FROM inventors AS i
  JOIN relationships AS r ON r.inventor_id = i.inventor_id
  GROUP BY i.inventor_id, i.name
)
SELECT inventor_id,
       name,
       patent_count,
       DENSE_RANK() OVER (ORDER BY patent_count DESC) AS rank_by_patents
FROM inventor_totals
ORDER BY rank_by_patents, patent_count DESC, name
LIMIT 80;
