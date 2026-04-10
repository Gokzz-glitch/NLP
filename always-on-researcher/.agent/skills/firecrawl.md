---
name: firecrawl-scraper
description: Web scraping tool for the Scraper Sub-Agent.
---
# Firecrawl Skill
When instructed to scrape a URL, execute this command in the terminal:
`curl -X GET "https://api.firecrawl.dev/v1/scrape?url=TARGET_URL" -H "Authorization: Bearer YOUR_FIRECRAWL_KEY"`

Extract the markdown from the terminal response and save it locally as `scraped_data.md`.