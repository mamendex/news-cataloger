"""Orchestrates reader → classifier → extractor → storage pipeline."""
import config
from agents.reader import fetch_all, Article
from agents.classifier import classify
from agents.extractor import extract_companies
from storage.database import (
    init_db, upsert_news,
    get_or_create_theme, get_or_create_company,
    link_news_theme, link_news_company,
    resolve_alias, record_cooccurrences,
    get_active_feeds, stats,
)


def process_article(article: Article, db_path: str = config.DB_PATH) -> bool:
    news_id = upsert_news(
        title=article.title,
        url=article.url,
        summary=article.summary,
        published_at=article.published_at,
        source=article.source,
        db_path=db_path,
    )
    if news_id is None:
        return False  # duplicate

    text = f"{article.title} {article.summary}"

    for theme_name in classify(text):
        theme_id = get_or_create_theme(theme_name, db_path)
        link_news_theme(news_id, theme_id, db_path)

    company_ids = []
    for company_name in extract_companies(text):
        # resolve alias → nome canônico antes de gravar (ex: "RFB" → "Receita Federal")
        canonical = resolve_alias(company_name, context=text, db_path=db_path)
        company_id = get_or_create_company(canonical, db_path)
        link_news_company(news_id, company_id, db_path)
        company_ids.append(company_id)

    # registra co-ocorrência para cada par de entidades da mesma notícia
    if len(company_ids) >= 2:
        record_cooccurrences(company_ids, db_path)

    return True


def run(feed_urls: list[str] = None, db_path: str = config.DB_PATH):
    init_db(db_path)

    # usa feeds passados explicitamente ou lê os ativos do banco
    if feed_urls is None:
        feed_urls = get_active_feeds(db_path)

    print(f"[coordinator] fetching {len(feed_urls)} feed(s)...")
    articles = fetch_all(feed_urls)
    print(f"[coordinator] {len(articles)} article(s) retrieved")

    new_count = 0
    for article in articles:
        if process_article(article, db_path):
            new_count += 1
            print(f"  [+] {article.title[:80]}")

    s = stats(db_path)
    print(f"\n[coordinator] done — {new_count} new | DB: {s['news']} news, {s['themes']} themes, {s['companies']} companies")


if __name__ == "__main__":
    run()
