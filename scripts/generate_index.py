"""docs/schemas/ 配下の公開用スキーマ一覧から、簡単なリンク集
(docs/schemas/index.html, docs/index.html) を生成する。

GitHub Pagesはディレクトリの自動一覧表示を行わないため、index.htmlが
無いディレクトリへの直接アクセスは404になる。人間が興味を持って
アクセスした場合の案内用に、公開中のスキーマファイルへのリンク一覧を
用意する。ルート(docs/index.html)とdocs/schemas/index.htmlは同じ内容
とする。

スキーマが増減した際は、このスクリプトを再実行するだけで一覧が
自動的に更新される(手動でHTMLを編集しないこと)。
"""
import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCHEMAS_DIR = REPO_ROOT / "docs" / "schemas"


def build_entries() -> list[dict]:
    entries = []
    for path in sorted(SCHEMAS_DIR.glob("*.schema.json")):
        schema = json.loads(path.read_text(encoding="utf-8"))
        name = path.name.removesuffix(".schema.json")
        title = schema.get("title")
        # NGSI由来の長い技術的タイトルは一覧表示に向かないため使わない。
        if not title or "NGSI" in title:
            title = None
        entries.append({"file": path.name, "name": name, "title": title})
    return entries


def render_html(entries: list[dict], link_prefix: str) -> str:
    items = []
    for e in entries:
        label = e["name"]
        if e["title"]:
            label += f'（{e["title"]}）'
        items.append(
            f'      <li><a href="{link_prefix}{e["file"]}">{label}</a></li>'
        )

    return f"""<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="UTF-8">
<title>PPP Schema - 公開スキーマ一覧</title>
<style>
  body {{ font-family: system-ui, "Hiragino Sans", "Yu Gothic UI", sans-serif; max-width: 680px; margin: 2em auto; padding: 0 1em; line-height: 1.7; }}
  h1 {{ font-size: 1.3em; }}
  ul {{ padding-left: 1.4em; }}
  li {{ margin: 0.3em 0; }}
  a {{ text-decoration: none; }}
  a:hover {{ text-decoration: underline; }}
  .note {{ color: #666; font-size: 0.9em; }}
</style>
</head>
<body>
  <h1>PPP Schema - 公開スキーマ一覧</h1>
  <p class="note">PPP共通データ仕様協議会が公開するJSON Schema(<code>$ref</code>を含まない自己完結版)の一覧です。各データモデルの詳細は<a href="https://ppp-database.org/">ppp-database.org</a>を参照してください。</p>
  <ul>
{chr(10).join(items)}
  </ul>
</body>
</html>
"""


def main() -> None:
    entries = build_entries()

    # docs/schemas/index.html は同じディレクトリ内のファイルを指すため
    # プレフィックス無し、docs/index.html(ルート)はschemas/配下を指すため
    # "schemas/"を付ける。相対パスが異なるだけで内容(一覧の中身)は同じ。
    (SCHEMAS_DIR / "index.html").write_text(
        render_html(entries, link_prefix=""), encoding="utf-8"
    )
    (REPO_ROOT / "docs" / "index.html").write_text(
        render_html(entries, link_prefix="schemas/"), encoding="utf-8"
    )

    print(f"[ok] {len(entries)} schemas -> docs/schemas/index.html, docs/index.html")


if __name__ == "__main__":
    main()
