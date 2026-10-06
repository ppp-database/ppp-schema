"""JSON Schema内の$refをローカルファイル参照として解決し、展開済みスキーマを返す。

C:\\Tools\\stos.py の展開アルゴリズム（再帰的なインライン展開、#/$defs/Name形式の
フラグメント解決）を踏襲しつつ、参照先の取得をHTTP(requests)ではなく
リポジトリ内のファイルパス（$refを含むファイル自身の場所からの相対パス）として行う。

対応する$ref形式:
    "#/$defs/Name"                          同一ファイル内の$defs参照
    "../CommonParts.schema.json#/$defs/Name" 相対パスの他ファイル$defs参照
"""
import json
from pathlib import Path


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _resolve_ref_target(ref: str, current_file: Path, cache: dict):
    """$ref文字列をcurrent_fileからの相対パスとして解決する。

    戻り値: (参照先の中身, その中身が属するファイルパス)
    """
    ref_path_part, _, fragment = ref.partition("#")
    target_file = current_file if ref_path_part == "" else (current_file.parent / ref_path_part).resolve()

    if target_file not in cache:
        cache[target_file] = _load_json(target_file)
    target_schema = cache[target_file]

    if not fragment:
        return target_schema, target_file

    if not fragment.startswith("/$defs/"):
        raise ValueError(f"未対応の$ref形式です(#/$defs/以外): {ref}")

    def_name = fragment.split("/$defs/", 1)[1]
    return target_schema["$defs"][def_name], target_file


def expand_schema(schema, current_file: Path, cache: dict = None, visited: frozenset = frozenset()):
    """スキーマ内の$refを再帰的にローカルファイル参照として展開する。"""
    if cache is None:
        cache = {}

    if isinstance(schema, list):
        return [expand_schema(item, current_file, cache, visited) for item in schema]

    if not isinstance(schema, dict):
        return schema

    if "$ref" in schema:
        ref = schema["$ref"]
        visit_key = (str(current_file), ref)
        if visit_key in visited:
            return schema  # 循環参照: それ以上は展開しない

        next_visited = visited | {visit_key}
        target, target_file = _resolve_ref_target(ref, current_file, cache)
        target = expand_schema(target, target_file, cache, next_visited)

        if schema.keys() == {"$ref"}:
            return target

        # $refと同居する他キーがある場合、兄弟キーが参照先を上書きする(JSON Schema sibling semantics)
        if isinstance(target, dict):
            merged = dict(target)
            merged.update({k: v for k, v in schema.items() if k != "$ref"})
        else:
            merged = {k: v for k, v in schema.items() if k != "$ref"}
        return expand_schema(merged, current_file, cache, next_visited)

    return {k: expand_schema(v, current_file, cache, visited) for k, v in schema.items()}


def load_and_expand(schema_path: Path) -> dict:
    """スキーマファイルを読み込み、$refを全て展開したdictを返す。"""
    schema = _load_json(schema_path)
    cache = {schema_path.resolve(): schema}
    return expand_schema(schema, schema_path.resolve(), cache)
