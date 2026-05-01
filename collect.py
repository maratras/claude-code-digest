#!/usr/bin/env python3
"""Daily Claude Code news digest collector."""

import json
import os
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone

import requests

HEADERS = {"User-Agent": "claude-code-digest/1.0 (github.com/maratras/claude-code-digest)"}
SINCE = datetime.now(timezone.utc) - timedelta(days=1)


def fetch_hackernews():
    ts = int(SINCE.timestamp())
    url = (
        f"https://hn.algolia.com/api/v1/search"
        f"?query=%22claude+code%22&tags=story&numericFilters=created_at_i>{ts}&hitsPerPage=15"
    )
    try:
        data = requests.get(url, headers=HEADERS, timeout=15).json()
        items = []
        for h in data.get("hits", []):
            item_url = h.get("url") or f"https://news.ycombinator.com/item?id={h.get('objectID')}"
            items.append(
                {
                    "title": h.get("title", ""),
                    "url": item_url,
                    "hn_url": f"https://news.ycombinator.com/item?id={h.get('objectID')}",
                    "points": h.get("points", 0),
                    "comments": h.get("num_comments", 0),
                    "author": h.get("author", ""),
                }
            )
        return sorted(items, key=lambda x: x["points"], reverse=True)
    except Exception as e:
        print(f"  HN error: {e}")
        return []


def fetch_reddit():
    subreddits = ["ClaudeAI", "MachineLearning", "LocalLLaMA", "artificial", "ChatGPT"]
    items = []
    for sub in subreddits:
        try:
            url = f"https://www.reddit.com/r/{sub}/search.json?q=claude+code&sort=new&t=day&limit=5"
            data = requests.get(url, headers=HEADERS, timeout=15).json()
            for post in data.get("data", {}).get("children", []):
                p = post["data"]
                created = datetime.fromtimestamp(p.get("created_utc", 0), tz=timezone.utc)
                if created < SINCE:
                    continue
                items.append(
                    {
                        "title": p.get("title", ""),
                        "url": f"https://reddit.com{p.get('permalink', '')}",
                        "subreddit": p.get("subreddit", sub),
                        "score": p.get("score", 0),
                        "comments": p.get("num_comments", 0),
                    }
                )
        except Exception as e:
            print(f"  Reddit r/{sub} error: {e}")
    return sorted(items, key=lambda x: x["score"], reverse=True)


def fetch_github_releases():
    repos = [
        "anthropics/claude-code",
        "anthropics/anthropic-sdk-python",
        "anthropics/anthropic-sdk-typescript",
        "anthropics/anthropic-sdk-go",
    ]
    items = []
    for repo in repos:
        try:
            url = f"https://api.github.com/repos/{repo}/releases?per_page=5"
            resp = requests.get(url, headers=HEADERS, timeout=15)
            if resp.status_code != 200:
                continue
            for rel in resp.json():
                created = datetime.fromisoformat(rel["created_at"].replace("Z", "+00:00"))
                if created < SINCE:
                    continue
                body = rel.get("body") or ""
                first_line = next((l.strip() for l in body.splitlines() if l.strip()), "")
                items.append(
                    {
                        "repo": repo,
                        "tag": rel.get("tag_name", ""),
                        "name": rel.get("name", ""),
                        "url": rel.get("html_url", ""),
                        "note": first_line[:200],
                    }
                )
        except Exception as e:
            print(f"  GitHub {repo} error: {e}")
    return items


def fetch_npm_releases():
    packages = ["@anthropic-ai/claude-code", "@anthropic-ai/sdk"]
    items = []
    for pkg in packages:
        try:
            encoded = pkg.replace("/", "%2F")
            url = f"https://registry.npmjs.org/{encoded}"
            data = requests.get(url, headers=HEADERS, timeout=15).json()
            times = data.get("time", {})
            for version, ts in sorted(times.items(), key=lambda x: x[1], reverse=True):
                if version in ("created", "modified"):
                    continue
                pub = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                if pub < SINCE:
                    break
                items.append(
                    {
                        "package": pkg,
                        "version": version,
                        "url": f"https://www.npmjs.com/package/{pkg}/v/{version}",
                        "published": pub.strftime("%H:%M UTC"),
                    }
                )
        except Exception as e:
            print(f"  npm {pkg} error: {e}")
    return items


def fetch_anthropic_changelog():
    """Try to get latest entries from Anthropic changelog."""
    items = []
    try:
        resp = requests.get("https://docs.anthropic.com/changelog", headers=HEADERS, timeout=15)
        # Simple heuristic: look for date patterns in the last 24h
        # The changelog is an SPA so we get raw HTML; just note it's available
        if resp.status_code == 200:
            items.append(
                {
                    "title": "Anthropic Changelog (проверь вручную для свежих записей)",
                    "url": "https://docs.anthropic.com/changelog",
                }
            )
    except Exception as e:
        print(f"  Anthropic changelog error: {e}")
    return items


def fetch_youtube_anthropic():
    """Fetch Anthropic's YouTube channel via RSS."""
    # Anthropic channel ID (verified)
    channel_id = "UCwGU-tVEiMBuQfHFJIfQp7g"
    items = []
    try:
        url = f"https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}"
        resp = requests.get(url, headers=HEADERS, timeout=15)
        if resp.status_code != 200:
            return items
        ns = {
            "atom": "http://www.w3.org/2005/Atom",
            "media": "http://search.yahoo.com/mrss/",
        }
        root = ET.fromstring(resp.content)
        for entry in root.findall("atom:entry", ns)[:10]:
            pub_el = entry.find("atom:published", ns)
            if pub_el is None:
                continue
            pub = datetime.fromisoformat(pub_el.text.replace("Z", "+00:00"))
            if pub < SINCE:
                continue
            title_el = entry.find("atom:title", ns)
            link_el = entry.find("atom:link", ns)
            items.append(
                {
                    "title": title_el.text if title_el is not None else "",
                    "url": link_el.get("href", "") if link_el is not None else "",
                }
            )
    except Exception as e:
        print(f"  YouTube error: {e}")
    return items


def build_digest(hn, reddit, github, npm, youtube):
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    lines = [
        f"# Claude Code Digest — {today}",
        "",
        f"*Автоматический дайджест | {datetime.now(timezone.utc).strftime('%H:%M UTC')}*",
        "",
    ]

    if npm:
        lines += ["## 📦 Новые версии пакетов"]
        for item in npm:
            lines.append(f"- **[{item['package']} {item['version']}]({item['url']})** — {item['published']}")
        lines.append("")

    if github:
        lines += ["## 🚀 GitHub Releases"]
        for item in github:
            lines.append(f"- **[{item['repo']} {item['tag']}]({item['url']})**")
            if item["note"]:
                lines.append(f"  > {item['note']}")
        lines.append("")

    if youtube:
        lines += ["## 📺 YouTube — Anthropic"]
        for item in youtube:
            lines.append(f"- [{item['title']}]({item['url']})")
        lines.append("")

    if hn:
        lines += ["## 🔶 Hacker News"]
        for item in hn:
            lines.append(
                f"- [{item['title']}]({item['url']}) "
                f"— {item['points']} pts, {item['comments']} комм. "
                f"| [обсуждение]({item['hn_url']})"
            )
        lines.append("")

    if reddit:
        lines += ["## 💬 Reddit"]
        for item in reddit:
            lines.append(
                f"- [{item['title']}]({item['url']}) "
                f"— r/{item['subreddit']}, {item['score']} очков"
            )
        lines.append("")

    if not any([npm, github, youtube, hn, reddit]):
        lines.append("*Новостей за последние 24 часа не найдено.*")
        lines.append("")

    lines += [
        "---",
        "",
        "**Источники:** "
        "[HN](https://news.ycombinator.com/item?q=claude+code) · "
        "[Reddit r/ClaudeAI](https://reddit.com/r/ClaudeAI) · "
        "[GitHub anthropics](https://github.com/anthropics) · "
        "[npm](https://www.npmjs.com/search?q=%40anthropic-ai) · "
        "[Anthropic Changelog](https://docs.anthropic.com/changelog) · "
        "[YouTube](https://youtube.com/@anthropic-ai)",
    ]

    return "\n".join(lines)


if __name__ == "__main__":
    print("Fetching HackerNews...")
    hn = fetch_hackernews()
    print(f"  {len(hn)} items")

    print("Fetching Reddit...")
    reddit = fetch_reddit()
    print(f"  {len(reddit)} items")

    print("Fetching GitHub releases...")
    github = fetch_github_releases()
    print(f"  {len(github)} items")

    print("Fetching npm releases...")
    npm = fetch_npm_releases()
    print(f"  {len(npm)} items")

    print("Fetching YouTube...")
    youtube = fetch_youtube_anthropic()
    print(f"  {len(youtube)} items")

    digest = build_digest(hn, reddit, github, npm, youtube)

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    os.makedirs("digests", exist_ok=True)
    path = f"digests/{today}.md"
    with open(path, "w", encoding="utf-8") as f:
        f.write(digest)

    print(f"\nSaved: {path}")
    print(digest[:500])
