"""JSON Schema (schemas/{Model}/{Model}.schema.json) から
WordPress埋め込み用の表データJSON (docs/tables/{Model}.json) を生成する。

出力フォーマット（ppp-datamodel-embed プラグインの契約と一致させること）:
    {"model": "...", "columns": [...], "rows": [[...], ...]}

行の長さについて:
    トップレベル属性の行は列数と同じ長さ(説明列を含む)。
    その属性が入れ子構造(object/array of object)を持つ場合、直後に続く
    子孫行は列数より1つ少ない長さ(説明列を持たない)で出力する。
    WordPress側はこれを見て、説明セルに自動でrowspanを付与する。
"""
import json
import sys
from pathlib import Path

from refresolve import load_and_expand

REPO_ROOT = Path(__file__).resolve().parent.parent
SCHEMAS_DIR = REPO_ROOT / "schemas"
DOCS_DIR = REPO_ROOT / "docs" / "tables"

COLUMNS = ["呼称", "Attribute name", "type", "回数", "説明"]
INDENT = "　"  # 全角スペース。入れ子の深さぶん繰り返す

# https://ppp-database.org/spec/parts/ に実在するページ一覧(2026-07確認)
PART_LINKS = {
    "ContactPoint": "https://ppp-database.org/spec/parts/ContactPoint/",
    "IdentificationGroup": "https://ppp-database.org/spec/parts/IdentificationGroup/",
    "OpeningHours": "https://ppp-database.org/spec/parts/OpeningHours/",
    "Point": "https://ppp-database.org/spec/parts/Point/",
    "Polygon": "https://ppp-database.org/spec/parts/Polygon/",
    "PostalAddress": "https://ppp-database.org/spec/parts/PostalAddress/",
    "PriceSpecification": "https://ppp-database.org/spec/parts/PriceSpecification/",
    "Accessibility": "https://ppp-database.org/spec/parts/Accessibility/",
    "ChildCare": "https://ppp-database.org/spec/parts/ChildCare/",
    "ProcedureStep": "https://ppp-database.org/spec/parts/ProcedureStep/",
    "Id": "https://ppp-database.org/spec/parts/id/",
}

JSON_TYPE_DISPLAY = {
    "string": "Text",
    "number": "Number",
    "integer": "Integer",
    "boolean": "Boolean",
}


def linkify_type(type_name: str) -> str:
    """type列の値を、PART_LINKSに載っていれば [text](url) 記法に変換する。

    PART_LINKSは手動更新のホワイトリストで、トップレベル属性(NGSIラッパーの
    "type" const)にのみ適用される。新規追加分はx-partType([[linkify_part]]参照)
    を使うこと。PART_LINKSは既存の未移行フィールドとの互換性のために残している。
    """
    url = PART_LINKS.get(type_name)
    return f"[{type_name}]({url})" if url else type_name


def linkify_part(name: str) -> str:
    """x-partTypeで宣言された名前を、/spec/parts/{name}/ への固定パターンリンクに
    変換する。x-partTypeキーの存在自体が「対応する独自ページが実在する」という
    スキーマ側の明示的な宣言なので、linkify_type()と異なりホワイトリスト参照は
    行わない(URLパターンの組み立てのみ生成側の責務とする)。
    """
    return f"[{name}](https://ppp-database.org/spec/parts/{name}/)"


def display_json_type(json_type) -> str:
    if isinstance(json_type, list):
        return " / ".join(dict.fromkeys(display_json_type(t) for t in json_type))
    return JSON_TYPE_DISPLAY.get(json_type, json_type or "")


def resolve_geo_types(value_schema: dict) -> list[str]:
    """geo:json属性のvalueスキーマから実際のジオメトリ型名(Point/Polygon等)を取り出す。

    単一形式 {"properties": {"type": {"const": "Point"}, ...}} と、
    oneOf形式 {"oneOf": [{"properties": {"type": {"const": "Point"}}}, ...]} の
    両方に対応する。
    """
    variants = value_schema.get("oneOf") or [value_schema]
    names = []
    for variant in variants:
        const = variant.get("properties", {}).get("type", {}).get("const")
        if const:
            names.append(const)
    return names


def _json_type_of_const(value) -> str:
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, str):
        return "string"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    return ""


def infer_type_and_occurrence(prop_schema: dict):
    """1属性分のスキーマからNGSI型(type列)・単一/配列(回数列)・入れ子展開用の
    (value_schema, raw_ngsi_type)を推定する。

    NGSI-LDラッパー形式 {"properties": {"type": {"const": "Text"}, "value": {...}}}
    と、id/typeのようなフラットな形式 {"type": "string"} / {"const": "..."} の
    両方に対応する。属性直下がoneOf（例: Observation.performedAt）やgeo:json等の
    複合ケースでは、既に部品ページ等で表現済みのため入れ子展開は行わない
    (value_schema=Noneを返す)。属性直下がallOf（例: Organization.category、
    TextAttribute等の共通$defにvalueのenum制約だけ上乗せするケース)の場合は、
    先にmerge_allof()で単一のプレーンなスキーマに合成してから処理する。
    """
    prop_schema = merge_allof(prop_schema)

    if "oneOf" in prop_schema and "properties" not in prop_schema:
        types, occurrences = [], []
        for variant in prop_schema["oneOf"]:
            t, occ, _, _ = infer_type_and_occurrence(variant)
            types.append(t)
            occurrences.append(occ)
        uniq_types = list(dict.fromkeys(types))
        uniq_occurrences = list(dict.fromkeys(occurrences))
        return " / ".join(uniq_types), " / ".join(uniq_occurrences), None, None

    props = prop_schema.get("properties")
    if props and "type" in props and "value" in props:
        ngsi_type = props["type"].get("const", "")
        value_schema = props["value"]
    else:
        value_schema = prop_schema
        ngsi_type = prop_schema.get("type", "")
        if not ngsi_type and "const" in prop_schema:
            ngsi_type = _json_type_of_const(prop_schema["const"])

    if value_schema.get("type") == "array":
        max_items = value_schema.get("maxItems")
        occurrence = f"*(最大{max_items})" if max_items else "*"
    else:
        occurrence = "1"

    if ngsi_type == "geo:json":
        geo_names = resolve_geo_types(value_schema)
        display_type = " / ".join(linkify_type(n) for n in geo_names) if geo_names else ngsi_type
        return display_type, occurrence, None, None

    # x-partTypeはvalue側(NGSIラッパーのvalue直下、例: telephoneのitems)にも、
    # prop_schema側(title/descriptionと同じ$refの兄弟キーとしての配置、例:
    # Facility.postalCodeの様に共通$defを$refで参照しつつ属性固有に付与する
    # ケース)にも置かれうるため、両方をチェックする。
    part_type = value_schema.get("x-partType") or prop_schema.get("x-partType")
    if part_type:
        # 独自ページを持つ構造であることが明示されているため、既にそちらで
        # 説明済みとみなしサブ構造の展開は行わない(value_schema=None)。
        return linkify_part(part_type), occurrence, None, None

    return linkify_type(ngsi_type), occurrence, value_schema, ngsi_type


def merge_allof(schema: dict) -> dict:
    """allOfの各分岐を表示用に浅くマージする。

    JSON Schemaの検証としては各分岐が独立にANDされるだけだが、表生成では
    1つの実効的なスキーマとして扱いたいので、properties/requiredを合成し、
    それ以外のキーは先に見つかった値を採用する。$refは事前にrefresolve.pyで
    展開済みである前提。
    """
    if "allOf" not in schema:
        return schema

    merged = {k: v for k, v in schema.items() if k != "allOf"}
    merged_properties = dict(merged.get("properties", {}))
    merged_required = list(merged.get("required", []))

    for branch in schema["allOf"]:
        branch = merge_allof(branch)
        for key, value in branch.items():
            if key == "properties":
                for pname, pschema in value.items():
                    if pname in merged_properties:
                        merged_properties[pname] = {**merged_properties[pname], **pschema}
                    else:
                        merged_properties[pname] = pschema
            elif key == "required":
                for r in value:
                    if r not in merged_required:
                        merged_required.append(r)
            elif key not in merged:
                merged[key] = value

    if merged_properties:
        merged["properties"] = merged_properties
    if merged_required:
        merged["required"] = merged_required

    return merged


def analyze_nested(schema: dict):
    """ラッパーなしのプレーンなJSON Schemaフィールドを解析する。

    戻り値: (type列表示, 回数列表示, [(子のAttribute name, 子のschema), ...])
    子が無い場合は空リストを返す。
    """
    schema = merge_allof(schema)
    json_type = schema.get("type")

    if json_type == "array":
        items = schema.get("items")

        if isinstance(items, list):
            # タプル形式: 名前を持たない位置指定の要素群
            children = [(f"[{i}]", item) for i, item in enumerate(items)]
            return "Array", "1", children

        if "x-partType" in schema:
            # x-partTypeが配列フィールド自身(items内ではなく"type":"array"と
            # 同階層)に付与されているケース。items内に付与する場合(下記)とは
            # 意味が異なり、「配列の各要素がXである」ではなく「この配列全体が
            # 既にX自身として定義済み」であることを示す(例: childCareFeeは
            # PriceSpecificationValue自体が配列だが、childCareFee自身が
            # PriceSpecificationという概念そのものであり、Xの配列ではない)。
            # そのためArray()で包まずlinkify_part()の結果をそのまま使う
            # (x-suggested-name付き$defの自己行と同じ考え方)。回数(occurrence)
            # 列には引き続き配列としての実際のカーディナリティを表示する。
            # 既にそのページで説明済みのためサブ構造の展開は行わない
            # (x-refTypeより優先度が高い、より具体的なシグナルなので先にチェックする)。
            max_items = schema.get("maxItems")
            occurrence = f"*(最大{max_items})" if max_items else "*"
            return linkify_part(schema["x-partType"]), occurrence, []

        if "x-refType" in schema:
            # x-refTypeが配列フィールド自身(items内ではなく"type":"array"と
            # 同階層)に付与されているケース。値がnull(13モデル外への参照)
            # でもキー自体はRelationshipであることを示すため、値の真偽では
            # なくキーの存在で判定すること。
            max_items = schema.get("maxItems")
            occurrence = f"*(最大{max_items})" if max_items else "*"
            return "Array(Relationship)", occurrence, []

        if isinstance(items, dict):
            items = merge_allof(items)
            # 回数(occurrence)は「この配列自身」の要素数上限を示すべきなので、
            # schema自身のmaxItemsを見る(itemsのmaxItemsは入れ子側の制約であり別物。
            # 例: Polygon.coordinates→リング→頂点で、頂点自身のmaxItems:3が
            # リングの要素数だと誤認識されるバグがあった)
            max_items = schema.get("maxItems")
            occurrence = f"*(最大{max_items})" if max_items else "*"
            if "x-partType" in items:
                # x-partTypeがitems側に付与されているケース(同じ判定をここでも行う。
                # 例: ContactPoint.telephoneのitemsにx-partType: "Telephone")
                return f"Array({linkify_part(items['x-partType'])})", occurrence, []
            if items.get("type") == "object" and "properties" in items:
                # NGSI v2ではobjectをStructuredValueと表現する
                # (StructuredValueは本来array/object両方を含むが、arrayは
                # 別途"Array"と表現する運用のため、ここでは常にobjectを指す)
                return "Array(StructuredValue)", occurrence, list(items["properties"].items())
            if "x-refType" in items:
                # x-refTypeがitems側に付与されているケース(同じ判定をここでも行う)
                return "Array(Relationship)", occurrence, []
            if items.get("type") == "array":
                # 配列の配列(例: Polygon.coordinatesのリング)。各要素は均質な
                # ので、tuple形式と同じ命名規則で"[i]"という1件の代表子を返し、
                # itemsスキーマ自身(タイトル・説明・入れ子構造込み)をそのまま
                # 子として展開する(render_field()が再帰的にさらに展開する)。
                return "Array", occurrence, [("[i]", items)]
            item_type = display_json_type(items.get("type", ""))
            disp = f"Array({item_type})" if item_type else "Array"
            return disp, occurrence, []

        return "Array", "*", []

    if json_type == "object" and "properties" in schema:
        # NGSI v2ではobjectをStructuredValueと表現する(上記と同じ理由)
        return "StructuredValue", "1", list(schema["properties"].items())

    if "x-partType" in schema:
        # 配列と同様、ラッパー無しの単体フィールドについても同じ判定を行う
        return linkify_part(schema["x-partType"]), "1", []

    if "x-refType" in schema:
        # 配列と同様、ラッパー無しの単体フィールドについても同じ判定を行う
        return "Relationship", "1", []

    if json_type is None and "const" in schema:
        # stepType等、typeキーを持たずconstのみのフィールド。NGSI上、
        # サブ属性自体にtypeを明示する仕組みは無く、たまたま"type"という
        # 名前のサブ属性であっても(例: GeoJSONのPoint/Polygon判別子)値の
        # 実体はstringに過ぎないため、constの値ではなくJSON型を逆算して
        # 表示する(値そのものはdescription側で説明する)。
        return display_json_type(_json_type_of_const(schema["const"])), "1", []

    return display_json_type(json_type), "1", []


def indent_prefix(depth: int) -> str:
    """深さに応じたインデントを返す。直前の1つだけ枝記号「∟」にする。"""
    if depth <= 0:
        return ""
    return INDENT * (depth - 1) + "∟"


def render_field(name: str, schema: dict, depth: int) -> list:
    """1つのネストしたフィールドを、自身+子孫の行のリストとして返す。

    子孫自身にdescriptionがあれば5列目として含める(この行がWordPress側の
    rowspan計算上「フル行」となり、以降の子孫がdescriptionを持たない限り
    そちらに新たにrowspanされる)。descriptionが無ければ従来通り4列のままとし、
    直近の(親または兄弟の)フル行からrowspanで説明を継承させる。
    """
    indent = indent_prefix(depth)
    title = schema.get("title", "") or "-"
    description = schema.get("description", "")
    disp_type, occurrence, children = analyze_nested(schema)

    row = [f"{indent}{title}", f"{indent}{name}", disp_type, occurrence]
    if description:
        row.append(description)
    rows = [row]
    for child_name, child_schema in children:
        rows.extend(render_field(child_name, child_schema, depth + 1))
    return rows


def build_table(schema: dict, model: str) -> dict:
    rows = []
    for attr_name, prop_schema in schema.get("properties", {}).items():
        title = prop_schema.get("title", "") or "-"
        description = prop_schema.get("description", "")
        value_schema = None

        if attr_name == "id":
            ngsi_type, occurrence = linkify_type("Id"), "1"
        elif attr_name == "type":
            ngsi_type, occurrence = "Text", "1"  # /spec/parts/type/ は存在しないためリンクなし
        else:
            ngsi_type, occurrence, value_schema, raw_type = infer_type_and_occurrence(prop_schema)
            if raw_type in PART_LINKS:
                # 部品ページで説明済みの型(PostalAddress等)は中身を展開しない
                value_schema = None

        rows.append([title, attr_name, ngsi_type, occurrence, description])

        if value_schema is not None:
            _, _, children = analyze_nested(value_schema)
            for child_name, child_schema in children:
                rows.extend(render_field(child_name, child_schema, depth=1))

    return {"model": model, "columns": COLUMNS, "rows": rows}


def main() -> None:
    DOCS_DIR.mkdir(parents=True, exist_ok=True)
    models = sorted(p.name for p in SCHEMAS_DIR.iterdir() if p.is_dir())

    for model in models:
        schema_path = SCHEMAS_DIR / model / f"{model}.schema.json"
        if not schema_path.exists():
            print(f"[skip] {model}: schema file not found", file=sys.stderr)
            continue

        schema = load_and_expand(schema_path)  # $ref(同一ファイル/CommonParts等)を展開してから処理
        table = build_table(schema, model)

        out_path = DOCS_DIR / f"{model}.json"
        out_path.write_text(
            json.dumps(table, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        missing_titles = sum(1 for r in table["rows"] if r and r[0] == "-")
        print(f"[ok] {model}: {len(table['rows'])} rows, 呼称欠落 {missing_titles}件 -> {out_path}")


if __name__ == "__main__":
    main()
