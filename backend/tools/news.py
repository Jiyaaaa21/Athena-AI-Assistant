import requests

from backend.core.config import (
    GNEWS_API_KEY
)


class NewsTool:

    name = "news"

    description = (
        "Get latest news headlines"
    )

    def run(self, topic):

        if not GNEWS_API_KEY:
            return (
                "News error: GNEWS_API_KEY is not configured on this "
                "deployment, so I can't fetch real headlines. Get a free "
                "key at https://gnews.io and set GNEWS_API_KEY."
            )

        url = (
            "https://gnews.io/api/v4/search"
        )

        params = {
            "q": topic,
            "lang": "en",
            "max": 10,
            "apikey": GNEWS_API_KEY
        }

        try:

            response = requests.get(
                url,
                params=params,
                timeout=10
            )

            data = response.json()

            if response.status_code == 401 or response.status_code == 403:
                # Phase 35 fix: previously this fell through to the
                # generic "articles" not in data -> "No news found."
                # path, which reads as "there's genuinely no news right
                # now" -- very different from "the API key is invalid",
                # and gave no actionable signal that anything needed
                # fixing on the deployment side.
                return (
                    f"News error: GNews rejected the request (HTTP {response.status_code}) "
                    f"-- the configured GNEWS_API_KEY is likely invalid or expired. "
                    f"Check it at https://gnews.io."
                )

            if response.status_code == 429:
                return "News error: GNews's free-tier rate limit has been hit for today. Try again later."

            if "articles" not in data:

                return "No news found."

            seen_titles = set()

            results = []

            count = 1

            for article in data["articles"]:

                title = article.get(
                    "title",
                    "No title"
                )

                if title in seen_titles:
                    continue

                seen_titles.add(
                    title
                )

                source = (
                    article.get(
                        "source",
                        {}
                    ).get(
                        "name",
                        "Unknown Source"
                    )
                )

                published = article.get(
                    "publishedAt",
                    "Unknown Date"
                )

                article_url = article.get(
                    "url",
                    ""
                )

                results.append(
                    f"{count}. {title}\n"
                    f"Source: {source}\n"
                    f"Published: {published}\n"
                    f"URL: {article_url}\n"
                )

                count += 1

                if count > 5:
                    break

            return "\n".join(
                results
            )

        except Exception as e:

            return (
                f"News error: {str(e)}"
            )