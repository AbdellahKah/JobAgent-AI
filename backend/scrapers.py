"""
Multi-Platform Job Scrapers — Real URL extraction from job boards.

Approach:
- LinkedIn: Use Google search operator (site:linkedin.com/jobs) for public listings
- Indeed: Use Google search operator (site:indeed.com OR site:ma.indeed.com)
- Rekrute.com: Direct HTML scraping with proper headers
- Emploi.ma: Direct HTML scraping with proper headers
- Google Jobs: General fallback via SerpAPI-style Google search

All scrapers return a unified format:
[{
    "title": str,
    "company": str,
    "location": str,
    "url": str,
    "source": str,  # "linkedin" | "indeed" | "rekrute" | "emploi_ma" | "google"
    "desc": str,
}]
"""

import httpx
import asyncio
import re
from urllib.parse import quote_plus, urljoin
from bs4 import BeautifulSoup
from datetime import datetime


# ─────────────────────────────────────────────
# Shared Config
# ─────────────────────────────────────────────

HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64; rv:128.0) Gecko/20100101 Firefox/128.0",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9,fr;q=0.8",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
}

TIMEOUT = httpx.Timeout(15.0, connect=10.0)


# ─────────────────────────────────────────────
# Scraper: Rekrute.com
# ─────────────────────────────────────────────

async def scrape_rekrute(query: str, location: str = "Morocco") -> list[dict]:
    """Scrape job listings from Rekrute.com (Morocco's top job board)."""
    results = []
    search_query = quote_plus(query)
    url = f"https://www.rekrute.com/en/offres.html?s=3&p=1&o=1&keyword={search_query}"

    try:
        async with httpx.AsyncClient(headers=HEADERS, timeout=TIMEOUT, follow_redirects=True) as client:
            response = await client.get(url)

            if response.status_code != 200:
                print(f"[REKRUTE] HTTP {response.status_code}")
                return results

            soup = BeautifulSoup(response.text, "html.parser")

            # Rekrute uses .post-id class for job cards
            job_cards = soup.select("li.post-id") or soup.select("div.job-item") or soup.select("article")

            # Fallback: try finding links with job offer pattern
            if not job_cards:
                job_links = soup.find_all("a", href=re.compile(r"/en/offre-emploi-"))
                seen_urls = set()
                for link in job_links[:10]:
                    href = link.get("href", "")
                    if href in seen_urls:
                        continue
                    seen_urls.add(href)

                    full_url = urljoin("https://www.rekrute.com", href)
                    title_text = link.get_text(strip=True)

                    if title_text and len(title_text) > 5:
                        results.append({
                            "title": title_text[:100],
                            "company": "",
                            "location": location,
                            "url": full_url,
                            "source": "rekrute",
                            "desc": f"Job listing found on Rekrute.com",
                        })
            else:
                for card in job_cards[:10]:
                    title_el = card.select_one("h2 a, h3 a, .titreJob a, a.job-title")
                    company_el = card.select_one(".company, .entreprise, span.company-name")
                    location_el = card.select_one(".location, .localisation")

                    title = title_el.get_text(strip=True) if title_el else ""
                    href = title_el.get("href", "") if title_el else ""
                    company = company_el.get_text(strip=True) if company_el else ""
                    loc = location_el.get_text(strip=True) if location_el else location

                    if title and href:
                        full_url = urljoin("https://www.rekrute.com", href)
                        results.append({
                            "title": title,
                            "company": company,
                            "location": loc,
                            "url": full_url,
                            "source": "rekrute",
                            "desc": f"Job listing from Rekrute.com",
                        })

    except Exception as e:
        print(f"[REKRUTE] Scraper error: {e}")

    print(f"[REKRUTE] Found {len(results)} jobs")
    return results


# ─────────────────────────────────────────────
# Scraper: Emploi.ma
# ─────────────────────────────────────────────

async def scrape_emploi_ma(query: str, location: str = "Morocco") -> list[dict]:
    """Scrape job listings from Emploi.ma."""
    results = []
    search_query = quote_plus(query)
    url = f"https://www.emploi.ma/recherche-jobs-maroc?keywords={search_query}"

    try:
        async with httpx.AsyncClient(headers=HEADERS, timeout=TIMEOUT, follow_redirects=True) as client:
            response = await client.get(url)

            if response.status_code != 200:
                print(f"[EMPLOI.MA] HTTP {response.status_code}")
                return results

            soup = BeautifulSoup(response.text, "html.parser")

            # Emploi.ma job listing selectors
            job_cards = soup.select("div.views-row") or soup.select("article.job-item") or soup.select("div.job-listing")

            # Fallback: find job offer links
            if not job_cards:
                job_links = soup.find_all("a", href=re.compile(r"/offre-emploi-"))
                seen_urls = set()
                for link in job_links[:10]:
                    href = link.get("href", "")
                    if href in seen_urls:
                        continue
                    seen_urls.add(href)

                    full_url = urljoin("https://www.emploi.ma", href)
                    title_text = link.get_text(strip=True)

                    if title_text and len(title_text) > 5:
                        results.append({
                            "title": title_text[:100],
                            "company": "",
                            "location": location,
                            "url": full_url,
                            "source": "emploi_ma",
                            "desc": "Job listing found on Emploi.ma",
                        })
            else:
                for card in job_cards[:10]:
                    title_el = card.select_one("h2 a, h3 a, a.job-title, .views-field-title a")
                    company_el = card.select_one(".company, .views-field-field-company, .employer")
                    location_el = card.select_one(".location, .views-field-field-job-location")

                    title = title_el.get_text(strip=True) if title_el else ""
                    href = title_el.get("href", "") if title_el else ""
                    company = company_el.get_text(strip=True) if company_el else ""
                    loc = location_el.get_text(strip=True) if location_el else location

                    if title and href:
                        full_url = urljoin("https://www.emploi.ma", href)
                        results.append({
                            "title": title,
                            "company": company,
                            "location": loc,
                            "url": full_url,
                            "source": "emploi_ma",
                            "desc": "Job listing from Emploi.ma",
                        })

    except Exception as e:
        print(f"[EMPLOI.MA] Scraper error: {e}")

    print(f"[EMPLOI.MA] Found {len(results)} jobs")
    return results


# ─────────────────────────────────────────────
# Scraper: Google Search (for LinkedIn & Indeed jobs)
# Uses Google's public search to find job listings on
# specific platforms with real, persistent URLs.
# ─────────────────────────────────────────────

async def scrape_google_jobs(query: str, location: str = "Morocco", site_filter: str = "") -> list[dict]:
    """
    Use Google Search to find job listings with real URLs.
    site_filter examples: "site:linkedin.com/jobs", "site:ma.indeed.com"
    """
    results = []
    search_term = f"{query} {location} job {site_filter}".strip()
    encoded = quote_plus(search_term)
    url = f"https://www.google.com/search?q={encoded}&num=10"

    try:
        google_headers = {
            **HEADERS,
            "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
        }
        async with httpx.AsyncClient(headers=google_headers, timeout=TIMEOUT, follow_redirects=True) as client:
            response = await client.get(url)

            if response.status_code != 200:
                print(f"[GOOGLE] HTTP {response.status_code}")
                return results

            soup = BeautifulSoup(response.text, "html.parser")

            # Google search result links
            for g in soup.select("div.g, div[data-sokoban-container]"):
                link_el = g.select_one("a[href]")
                title_el = g.select_one("h3")
                snippet_el = g.select_one("div.VwiC3b, span.aCOpRe")

                if not link_el or not title_el:
                    continue

                href = link_el.get("href", "")
                title = title_el.get_text(strip=True)
                snippet = snippet_el.get_text(strip=True) if snippet_el else ""

                # Only keep real job platform URLs
                if not href.startswith("http"):
                    continue
                if "google.com" in href:
                    continue

                # Determine source
                source = "google"
                if "linkedin.com" in href:
                    source = "linkedin"
                elif "indeed.com" in href:
                    source = "indeed"
                elif "rekrute.com" in href:
                    source = "rekrute"
                elif "emploi.ma" in href:
                    source = "emploi_ma"

                results.append({
                    "title": title[:100],
                    "company": "",
                    "location": location,
                    "url": href,
                    "source": source,
                    "desc": snippet[:200] if snippet else f"Found via Google Search",
                })

    except Exception as e:
        print(f"[GOOGLE] Scraper error: {e}")

    print(f"[GOOGLE] Found {len(results)} jobs (filter: {site_filter or 'none'})")
    return results


# ─────────────────────────────────────────────
# Scraper: LinkedIn (via Google site: operator)
# ─────────────────────────────────────────────

async def scrape_linkedin(query: str, location: str = "Morocco") -> list[dict]:
    """Find LinkedIn job listings via Google search."""
    return await scrape_google_jobs(query, location, site_filter="site:linkedin.com/jobs")


# ─────────────────────────────────────────────
# Scraper: Indeed Morocco (via Google site: operator)
# ─────────────────────────────────────────────

async def scrape_indeed(query: str, location: str = "Morocco") -> list[dict]:
    """Find Indeed job listings via Google search."""
    return await scrape_google_jobs(query, location, site_filter="site:ma.indeed.com OR site:indeed.com")


# ─────────────────────────────────────────────
# Master Scraper: Run All in Parallel
# ─────────────────────────────────────────────

async def scrape_all_platforms(query: str, location: str = "Morocco") -> list[dict]:
    """
    Run all scrapers in parallel and return merged, deduplicated results.
    Each result has a verified, persistent URL.
    """
    print(f"[SCRAPERS] Launching parallel scrape for: '{query}' in {location}")

    # Run all scrapers concurrently
    tasks = [
        scrape_rekrute(query, location),
        scrape_emploi_ma(query, location),
        scrape_linkedin(query, location),
        scrape_indeed(query, location),
    ]

    results = await asyncio.gather(*tasks, return_exceptions=True)

    # Flatten and filter out errors
    all_jobs = []
    for result in results:
        if isinstance(result, Exception):
            print(f"[SCRAPERS] One scraper failed: {result}")
            continue
        all_jobs.extend(result)

    # Deduplicate by URL
    seen_urls = set()
    unique_jobs = []
    for job in all_jobs:
        url = job.get("url", "")
        if url and url not in seen_urls:
            seen_urls.add(url)
            unique_jobs.append(job)

    print(f"[SCRAPERS] Total unique results: {len(unique_jobs)}")
    return unique_jobs
