"""schemas/{Model}/{Model}.schema.json の $ref を全て展開し、
外部ファイル参照を持たない自己完結型の公開用スキーマを docs/schemas/ に生成する。

schemas/ はDRYを優先した「マスター」(人間が編集する原本、$refで重複を排除)、
docs/schemas/ は可搬性を優先した「公開用成果物」(1ファイルで検証・利用が完結する。
GitHub Pagesの配信対象であるdocs/配下に置くことで安定した公開URLを持つ)。
"""
import json
import sys
from pathlib import Path

from refresolve import load_and_expand

REPO_ROOT = Path(__file__).resolve().parent.parent
SCHEMAS_DIR = REPO_ROOT / "schemas"
SCHEMA_DIR = REPO_ROOT / "docs" / "schemas"


def strip_unused_defs(schema: dict) -> dict:
    """展開済みスキーマは$refを含まないため、もはや参照されない$defsを取り除く。"""
    schema.pop("$defs", None)
    return schema


_STRIP_KEYS = {
    "x-partType",             # ドキュメント生成(generate_docs.py)専用
    "x-suggested-name",       # Parts テーブル生成(generate_parts_docs.py)専用
    "x-enumDescriptionLabels",# enum テーブル列見出し(generate_enum_docs.py)専用
}


def strip_tool_only_keys(obj):
    """公開スキーマに含めないツール専用キーを再帰的に除去する。"""
    if isinstance(obj, dict):
        for key in _STRIP_KEYS:
            obj.pop(key, None)
        for v in obj.values():
            strip_tool_only_keys(v)
    elif isinstance(obj, list):
        for item in obj:
            strip_tool_only_keys(item)


def main() -> None:
    SCHEMA_DIR.mkdir(parents=True, exist_ok=True)
    models = sorted(p.name for p in SCHEMAS_DIR.iterdir() if p.is_dir())

    for model in models:
        schema_path = SCHEMAS_DIR / model / f"{model}.schema.json"
        if not schema_path.exists():
            print(f"[skip] {model}: schema file not found", file=sys.stderr)
            continue

        expanded = load_and_expand(schema_path)
        expanded = strip_unused_defs(expanded)
        strip_tool_only_keys(expanded)

        out_path = SCHEMA_DIR / f"{model}.schema.json"
        out_path.write_text(
            json.dumps(expanded, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        print(f"[ok] {model} -> {out_path}")


if __name__ == "__main__":
    main()
