"""enums/{Name}.schema.json の各$defsから
WordPress埋め込み用の表データJSON (docs/enums/{Name}.json) を生成する。

出力フォーマット:
    {
      "source_file": "BuildingComponent",
      "defs": {
        "BuildingPartsEnum": {"columns": [...], "rows": [[...], ...]},
        "KitchenEquipmentEnum": {"level_count": 3, "rows": [[...], ...]},
        ...
      }
    }

1つのenums/{Name}.schema.jsonファイルに複数の$defsが入っている場合(例:
BuildingComponent.schema.jsonの10カテゴリ+統合版)でも、$defs全てをそのまま
出力する。ただし、他の$defsをoneOf+$refで束ねただけで独自のenum/
x-enumDescriptionsを持たない統合$def(BuildingComponentEnum等。モデルの
バリデーション専用で対応するWebページを持たない)は、出力対象から除外する
(build_def_table()がNoneを返す)。

x-enumDescriptionsの値の形によって表の形式を自動判定する:
    文字列                                          -> 用語/定義の2列("columns"付き)
    オブジェクト(x-enumDescriptionLabelsに対応するキー) -> 用語+各フィールドの列("columns"付き)
    上記以外(カテゴリ等のネスト、または値がリスト)        -> 階層形式。再帰的に平坦化し、
        各行は「レベル1, レベル2, ..., レベルN, 説明1, 説明2, ...」というフラットな
        配列にする(1行=1用語)。列名はenumごとにばらつきが大きいため、"columns"は
        出力せず"level_count"(先頭から何個が階層レベルか。残りは説明の列数)のみ
        出力する。ショートコード側のcolumns属性で列名を指定する運用とする。
        階層のキーが""(分類用語なし等のプレースホルダ)の場合もそのままレベル値と
        して残す(WordPress側で空セルを隣列とcolspan結合する判定に使うため)。
        説明の値が文字列なら列1つ、配列なら要素数ぶんの複数列になる(1つのenum内で
        全用語が同じ列数を持つ前提)。
x-enumDescription(単数形、enum全体への注記)は、x-enumDescriptionsが無い場合
に限り使う(例: LandUseZoneの様に全体注記だけで全用語を説明しているケース)。
この場合、1行目を[用語, 注記]のフル行、2行目以降を[用語]のみの短い行にする
ことで、ppp_render_datamodel_table()側の既存のrowspanロジック(フル行の後に
続く短い行の分だけ最終列をrowspan)がそのまま使え、注記が全行にまたがる1つの
セルとして表示される("note"というフィールドは出力しない)。
x-enumDescriptionsがある場合はx-enumDescriptionsを優先し、x-enumDescriptionは
表示上無視する。
"""
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
ENUMS_DIR = REPO_ROOT / "enums"
DOCS_DIR = REPO_ROOT / "docs" / "enums"


def classify(descriptions: dict, labels: dict | None) -> str:
    """x-enumDescriptionsの値の形を判定する。"""
    sample = next(iter(descriptions.values()), None)
    if isinstance(sample, str):
        return "flat"
    if isinstance(sample, dict):
        if labels and set(sample.keys()) <= set(labels.keys()):
            return "structured"
        return "hierarchical"
    if isinstance(sample, list):
        # 階層を持たず、説明だけが複数項目に分かれているケース。
        # flatten_hierarchy()的には「用語自身が唯一のレベル」として扱う。
        return "hierarchical"
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


def flatten_hierarchy(node: dict, path: tuple = ()) -> list:
    """再帰的に階層をたどり、末端(文字列またはリスト)に到達したら
    (パスのタプル, 末端の値)のペアをリストとして返す。

    パスの長さ(階層の深さ)と末端の値の型(str=1個/list=N個)を独立に
    追跡することで、呼び出し側で「レベル数」と「説明の列数」を正しく
    分離できるようにする(行の長さだけからは両者を区別できないため)。
    """
    results = []
    for key, value in node.items():
        current_path = path + (key,)
        if isinstance(value, dict):
            results.extend(flatten_hierarchy(value, current_path))
        else:
            results.append((current_path, value))
    return results


def build_hierarchical_table(descriptions: dict) -> dict:
    leaves = flatten_hierarchy(descriptions)
    if not leaves:
        return {"level_count": 0, "rows": []}

    level_count = len(leaves[0][0])
    rows = []
    for path, value in leaves:
        row = list(path)
        if isinstance(value, list):
            row.extend(value)
        else:
            row.append(value)
        rows.append(row)

    return {"level_count": level_count, "rows": rows}


def build_def_table(def_schema: dict) -> dict | None:
    descriptions = def_schema.get("x-enumDescriptions")
    labels = def_schema.get("x-enumDescriptionLabels")

    if "oneOf" in def_schema and not descriptions and "enum" not in def_schema:
        # 他の$defsをoneOf+$refで束ねただけの合成定義(例: BuildingComponentEnum
        # がカテゴリ別$defs10個をまとめてモデル側のバリデーションに使う場合)。
        # 独自の内容を持たず対応するWebページも無いため、出力対象から除外する。
        return None

    if not descriptions:
        # x-enumDescriptions(値ごとの説明)が無い場合のみ、x-enumDescription
        # (単数形、全体注記)を使う(例: LandUseZoneの様に全体注記だけで
        # 全用語を説明しているケース)。両方存在する場合はx-enumDescriptions
        # を優先し、x-enumDescriptionは表示上無視する。
        # 表示は「表の上に別枠のnote」ではなく、元表の構成(1行目は
        # [用語, 注記]のフル行、2行目以降は[用語]のみの短い行)に合わせる。
        # ppp_render_datamodel_table()の既存ロジック(フル行の後に続く
        # 短い行の分だけ最終列をrowspanする)がそのまま使えるため、
        # 注記は全行にまたがる1つのセルとして表示される。
        note = def_schema.get("x-enumDescription")
        enum_values = def_schema.get("enum", [])
        if note and enum_values:
            rows = [[enum_values[0], note]] + [[term] for term in enum_values[1:]]
        else:
            rows = [[term, ""] for term in enum_values]
        return {"columns": ["用語", "定義"], "rows": rows}

    shape = classify(descriptions, labels)
    if shape == "flat":
        columns = ["用語", "定義"]
        rows = build_flat_rows(descriptions)
        return {"columns": columns, "rows": rows}
    if shape == "structured":
        columns, rows = build_structured_rows(descriptions, labels)
        return {"columns": columns, "rows": rows}

    # hierarchical: 列名はショートコード側のcolumns属性で与える運用のため、
    # ここでは"columns"を出力せず"level_count"のみ出力する。
    return build_hierarchical_table(descriptions)


def main() -> None:
    DOCS_DIR.mkdir(parents=True, exist_ok=True)
    enum_files = sorted(p for p in ENUMS_DIR.glob("*.schema.json"))

    for path in enum_files:
        name = path.name.removesuffix(".schema.json")
        schema = json.loads(path.read_text(encoding="utf-8"))
        defs = schema.get("$defs", {})

        out_defs = {}
        for def_name, def_schema in defs.items():
            table = build_def_table(def_schema)
            if table is not None:
                out_defs[def_name] = table

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
