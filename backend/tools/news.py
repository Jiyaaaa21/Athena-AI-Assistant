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