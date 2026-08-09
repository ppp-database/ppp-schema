"""enums/{Name}.schema.json の各$defsから
WordPress埋め込み用の表データJSON (docs/enums/{Name}.json) を生成する。

出力フォーマット:
    {
      "source_file": "BuildingComponent",
      "defs": {
        "BuildingPartsEnum": {"columns": [...], "rows": [[...], ...], "note": "..."},
        ...
      }
    }

1つのenums/{Name}.schema.jsonファイルに複数の$defsが入っている場合(例:
BuildingComponent.schema.jsonの10カテゴリ+統合版)でも、$defs全てをそのまま
出力する。モデルのバリデーション専用で対応するWebページを持たない統合$def
(BuildingComponentEnum等)が含まれていても、ショートコード側で参照しなければ
実害は無いため、生成側で除外する判定は行わない。

x-enumDescriptionsの値の形によって表の形式を自動判定する:
    文字列                          -> 用語/定義の2列
    オブジェクト(x-enumDescriptionLabelsに対応するキー) -> 用語+各フィールドの列
    オブジェクト(上記に該当しない、カテゴリ等のネスト)   -> 再帰的に平坦化し、
                                       グループ見出し行+インデント付き用語/定義の2列
x-enumDescription(単数形、enum全体への注記)がある場合はrowsとは別にnoteとして格納する。
"""
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
ENUMS_DIR = REPO_ROOT / "enums"
DOCS_DIR = REPO_ROOT / "docs" / "enums"

INDENT = "　"  # 全角スペース。入れ子の深さぶん繰り返す


def indent_prefix(depth: int) -> str:
    """深さに応じたインデントを返す。直前の1つだけ枝記号「∟」にする。"""
    if depth <= 0:
        return ""
    return INDENT * (depth - 1) + "∟"


def classify(descriptions: dict, labels: dict | None) -> str:
    """x-enumDescriptionsの値の形を判定する。"""
    sample = next(iter(descriptions.values()), None)
    if isinstance(sample, str):
        return "flat"
    if isinstance(sample, dict):
        if labels and set(sample.keys()) <= set(labels.keys()):
            return "structured"
        return "nested"
    return "empty"


def build_flat_rows(descriptions: dict) -> list:
    return [[term, desc] for term, desc in descriptions.items()]


def build_structured_rows(descriptions: dict, labels: dict) -> tuple:
    field_order = list(labels.keys())
    columns = ["用語"] + [labels[k] for k in field_order]
    rows = []
    for term, obj in descriptions.items():
        rows.append([term] + [obj.get(k, "") for k in field_order])
    return columns, rows


def flatten_nested(node: dict, depth: int = 0) -> list:
    """再帰的にネストしたx-enumDescriptionsを(インデント付き用語, 定義)の行に変換する。

    キーが""(分類用語なしのプレースホルダ)の場合は見出し行を作らず、
    同じ深さのまま子を展開する。
    """
    rows = []
    for key, value in node.items():
        if isinstance(value, str):
            rows.append([f"{indent_prefix(depth)}{key}", value])
        elif isinstance(value, dict):
            if key == "":
                rows.extend(flatten_nested(value, depth))
            else:
                rows.append([f"{indent_prefix(depth)}{key}", ""])
                rows.extend(flatten_nested(value, depth + 1))
    return rows


def build_def_table(def_schema: dict) -> dict:
    note = def_schema.get("x-enumDescription")
    descriptions = def_schema.get("x-enumDescriptions")
    labels = def_schema.get("x-enumDescriptionLabels")

    if not descriptions:
        # x-enumDescriptions(値ごとの説明)が無い場合、enum配列があればそれを
        # そのまま行として出力する(例: LandUseZoneの様にx-enumDescription
        # (単数形、全体注記)だけで全用語を説明しているケース)。
        enum_values = def_schema.get("enum", [])
        rows = [[term, ""] for term in enum_values]
        return {"columns": ["用語", "定義"], "rows": rows, "note": note}

    shape = classify(descriptions, labels)
    if shape == "flat":
        columns = ["用語", "定義"]
        rows = build_flat_rows(descriptions)
    elif shape == "structured":
        columns, rows = build_structured_rows(descriptions, labels)
    else:  # nested
        columns = ["用語", "定義"]
        rows = flatten_nested(descriptions)

    return {"columns": columns, "rows": rows, "note": note}


def main() -> None:
    DOCS_DIR.mkdir(parents=True, exist_ok=True)
    enum_files = sorted(p for p in ENUMS_DIR.glob("*.schema.json"))

    for path in enum_files:
        name = path.name.removesuffix(".schema.json")
        schema = json.loads(path.read_text(encoding="utf-8"))
        defs = schema.get("$defs", {})

        out_defs = {}
        for def_name, def_schema in defs.items():
            out_defs[def_name] = build_def_table(def_schema)

        out = {"source_file": name, "defs": out_defs}
        out_path = DOCS_DIR / f"{name}.json"
        out_path.write_text(
            json.dumps(out, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        total_rows = sum(len(d["rows"]) for d in out_defs.values())
        print(f"[ok] {name}: {len(out_defs)} defs, {total_rows} rows -> {out_path}")


if __name__ == "__main__":
    main()
