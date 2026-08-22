<?php
/**
 * Plugin Name: PPP Datamodel Embed
 * Description: JSON Schemaから生成された表データを取得し、[ppp-datamodel] [ppp-enum] [ppp-parts] ショートコードでページ内にテーブルとして埋め込む。
 * Version: 0.5.9
 */

if ( ! defined( 'ABSPATH' ) ) {
    exit; // 直接アクセス禁止
}

// キャッシュキーに含めるバージョン。プラグイン更新時にここも上げておくと、
// 表示ロジックやスタイルを変更した際に古いtransientキャッシュを自動的に
// 無効化できる(キーが変わるだけで、古いキャッシュ自体は自然に期限切れ
// するまで残るが実害は無い)。ヘッダーコメントのVersionと同じ値に保つこと。
define( 'PPP_DATAMODEL_EMBED_VERSION', '0.5.9' );

add_shortcode( 'ppp-datamodel', 'ppp_datamodel_shortcode' );
add_shortcode( 'ppp-enum', 'ppp_enum_shortcode' );
add_shortcode( 'ppp-parts', 'ppp_parts_shortcode' );

function ppp_datamodel_shortcode( $atts ) {
    $atts = shortcode_atts(
        array(
            'model'  => '',
            'source' => '', // テスト時は明示的にURLを渡す。本番は既定のGitHub Pages URLに切り替え予定
            'ttl'    => HOUR_IN_SECONDS,
        ),
        $atts,
        'ppp-datamodel'
    );

    $model = sanitize_text_field( $atts['model'] );
    $source_url = esc_url_raw( $atts['source'] );

    if ( empty( $model ) || empty( $source_url ) ) {
        return '<p><em>ppp-datamodel: model / source 属性が指定されていません。</em></p>';
    }

    $cache_key       = 'ppp_datamodel_' . md5( PPP_DATAMODEL_EMBED_VERSION . $model . $source_url );
    $stale_cache_key = $cache_key . '_stale';

    $html = get_transient( $cache_key );
    if ( false !== $html ) {
        return ppp_datamodel_table_style() . $html;
    }

    $response = wp_remote_get( $source_url, array( 'timeout' => 8 ) );

    if ( is_wp_error( $response ) || 200 !== wp_remote_retrieve_response_code( $response ) ) {
        $stale = get_transient( $stale_cache_key );
        if ( false !== $stale ) {
            return ppp_datamodel_table_style() . $stale . ppp_datamodel_notice( '（最新データを取得できなかったため、直近のキャッシュを表示しています）' );
        }
        return ppp_datamodel_notice( 'データモデル表を取得できませんでした。時間をおいて再度お試しください。' );
    }

    $data = json_decode( wp_remote_retrieve_body( $response ), true );

    if ( ! is_array( $data ) || empty( $data['columns'] ) || empty( $data['rows'] ) ) {
        return ppp_datamodel_notice( 'データモデル表の形式が不正です。' );
    }

    $html = ppp_render_datamodel_table( $data );

    set_transient( $cache_key, $html, (int) $atts['ttl'] );
    set_transient( $stale_cache_key, $html, WEEK_IN_SECONDS );

    return ppp_datamodel_table_style() . $html;
}

function ppp_enum_shortcode( $atts ) {
    // docs/enum/{ファイル名}.json は1ファイルに複数$defsを含むため、
    // defで表示対象の$defを指定する(例: BuildingComponent.jsonの
    // KitchenEquipmentEnum)。columns/rows形式はppp-datamodelと共通なので
    // 表描画自体はppp_render_datamodel_table()を再利用する。
    $atts = shortcode_atts(
        array(
            'source'  => '',
            'def'     => '',
            'columns' => '',
            'ttl'     => HOUR_IN_SECONDS,
        ),
        $atts,
        'ppp-enum'
    );

    $def_name   = sanitize_text_field( $atts['def'] );
    $source_url = esc_url_raw( $atts['source'] );

    if ( empty( $def_name ) || empty( $source_url ) ) {
        return '<p><em>ppp-enum: def / source 属性が指定されていません。</em></p>';
    }

    $cache_key       = 'ppp_enum_' . md5( PPP_DATAMODEL_EMBED_VERSION . $def_name . $source_url );
    $stale_cache_key = $cache_key . '_stale';

    $html = get_transient( $cache_key );
    if ( false !== $html ) {
        return ppp_enum_table_style() . $html;
    }

    $response = wp_remote_get( $source_url, array( 'timeout' => 8 ) );

    if ( is_wp_error( $response ) || 200 !== wp_remote_retrieve_response_code( $response ) ) {
        $stale = get_transient( $stale_cache_key );
        if ( false !== $stale ) {
            return ppp_enum_table_style() . $stale . ppp_datamodel_notice( '（最新データを取得できなかったため、直近のキャッシュを表示しています）' );
        }
        return ppp_datamodel_notice( '用語集の表を取得できませんでした。時間をおいて再度お試しください。' );
    }

    $data = json_decode( wp_remote_retrieve_body( $response ), true );

    if ( ! is_array( $data ) || empty( $data['defs'][ $def_name ] ) ) {
        return ppp_datamodel_notice( '指定された用語集定義（' . esc_html( $def_name ) . '）が見つかりません。' );
    }

    $def = $data['defs'][ $def_name ];

    if ( empty( $def['rows'] ) ) {
        return ppp_datamodel_notice( '用語集の表の形式が不正です。' );
    }

    // level_count付きは階層形式(サブカテゴリ/分類用語/用語...)。列名は
    // enumごとにばらつきが大きくJSON側で標準化していないため、
    // ショートコードのcolumns属性(カンマ区切り、URLエンコード不要)で与える。
    $is_hierarchical = isset( $def['level_count'] );

    if ( $is_hierarchical ) {
        $columns_attr = sanitize_text_field( $atts['columns'] );
        if ( '' === $columns_attr ) {
            return ppp_datamodel_notice( 'ppp-enum: 階層形式の用語集にはcolumns属性の指定が必要です。' );
        }
        $columns = array_map( 'trim', explode( ',', $columns_attr ) );
    } elseif ( empty( $def['columns'] ) ) {
        return ppp_datamodel_notice( '用語集の表の形式が不正です。' );
    }

    $html = '';
    if ( ! empty( $def['note'] ) ) {
        $html .= '<p>' . wp_kses_post( ppp_linkify( $def['note'] ) ) . '</p>';
    }
    if ( $is_hierarchical ) {
        // LandUsageのように1つのenumファイルに列数(level_count)の異なる
        // 複数$defsが同居し、同じページに並べて埋め込まれるケースがある。
        // 全て同じクラスだとCSSで個別に列幅指定できないため、defごとに
        // 固有のクラスを追加する(共通クラスppp-enum-table-hierarchyは
        // そのまま残し、追加CSSで基本スタイルを流用できるようにする)。
        $hierarchy_class = 'ppp-enum-table-hierarchy ppp-enum-table-hierarchy--' . sanitize_html_class( $def_name );
        $draft_terms     = isset( $def['draft_terms'] ) && is_array( $def['draft_terms'] ) ? $def['draft_terms'] : array();
        $html .= ppp_render_hierarchy_table( $columns, $def['rows'], (int) $def['level_count'], $hierarchy_class, $draft_terms );
    } else {
        $html .= ppp_render_datamodel_table( $def, 'ppp-enum-table' );
    }

    set_transient( $cache_key, $html, (int) $atts['ttl'] );
    set_transient( $stale_cache_key, $html, WEEK_IN_SECONDS );

    return ppp_enum_table_style() . $html;
}

function ppp_parts_shortcode( $atts ) {
    // docs/parts/{ファイル名}.json も1ファイルに複数$defsを含む(enumと同じ)。
    // 表形式自体はdatamodelと同じ(columns/rows)なので、noteを持たない点を
    // 除きppp_enum_shortcode()とほぼ同じ構造。
    $atts = shortcode_atts(
        array(
            'source' => '',
            'def'    => '',
            'ttl'    => HOUR_IN_SECONDS,
        ),
        $atts,
        'ppp-parts'
    );

    $def_name   = sanitize_text_field( $atts['def'] );
    $source_url = esc_url_raw( $atts['source'] );

    if ( empty( $def_name ) || empty( $source_url ) ) {
        return '<p><em>ppp-parts: def / source 属性が指定されていません。</em></p>';
    }

    $cache_key       = 'ppp_parts_' . md5( PPP_DATAMODEL_EMBED_VERSION . $def_name . $source_url );
    $stale_cache_key = $cache_key . '_stale';

    $html = get_transient( $cache_key );
    if ( false !== $html ) {
        return ppp_datamodel_table_style() . $html;
    }

    $response = wp_remote_get( $source_url, array( 'timeout' => 8 ) );

    if ( is_wp_error( $response ) || 200 !== wp_remote_retrieve_response_code( $response ) ) {
        $stale = get_transient( $stale_cache_key );
        if ( false !== $stale ) {
            return ppp_datamodel_table_style() . $stale . ppp_datamodel_notice( '（最新データを取得できなかったため、直近のキャッシュを表示しています）' );
        }
        return ppp_datamodel_notice( 'データパーツの表を取得できませんでした。時間をおいて再度お試しください。' );
    }

    $data = json_decode( wp_remote_retrieve_body( $response ), true );

    if ( ! is_array( $data ) || empty( $data['defs'][ $def_name ] ) ) {
        return ppp_datamodel_notice( '指定されたデータパーツ定義（' . esc_html( $def_name ) . '）が見つかりません。' );
    }

    $def = $data['defs'][ $def_name ];

    if ( empty( $def['columns'] ) || empty( $def['rows'] ) ) {
        return ppp_datamodel_notice( '指定されたデータパーツ定義（' . esc_html( $def_name ) . '）には表示できる項目がありません。' );
    }

    $html = ppp_render_datamodel_table( $def );

    set_transient( $cache_key, $html, (int) $atts['ttl'] );
    set_transient( $stale_cache_key, $html, WEEK_IN_SECONDS );

    return ppp_datamodel_table_style() . $html;
}

function ppp_encode_url_fragment( $url ) {
    // マスター側は人間可読な生の日本語アンカー(#主キー等)のまま保つ方針のため、
    // href属性として使う直前にここでURLエンコードする。
    // 既にエンコード済みの表記が混在していても、一度デコードしてから
    // 再エンコードすることでどちらの入力でも同じ結果に正規化する。
    $parts = explode( '#', $url, 2 );
    if ( count( $parts ) === 2 ) {
        return $parts[0] . '#' . rawurlencode( rawurldecode( $parts[1] ) );
    }
    return $url;
}

function ppp_linkify( $text ) {
    // "[表示文字](URL)" 記法を <a> タグに変換する（type列・説明列で共通利用）。
    // 手順: 1) リンク部分を先に抜き出しトークン化 2) 残りの生テキストを丸ごとエスケープ
    //       3) トークンを安全なタグに置き戻す
    // こうしないと、説明文中の "<国名コード>" のようなプレースホルダ表記が
    // 未知のHTMLタグとして扱われ、ブラウザ上で消えてしまう。
    //
    // カッコ内がURLらしくない場合(スキーム付き"://"、"#"アンカー、"/"絶対パス
    // のいずれも含まない場合)は、リンクではなくx-draftTermsと同じバッチラベル
    // による色分け指定とみなし、"[追記した部分](20260820)"の様に文章の一部
    // だけを<span class="ppp-draft ppp-draft--20260820">として出力する。
    // 行全体を色分けするppp-draft--{ラベル}クラスと同じ名前を使うため、
    // WordPress側の追加CSSは1つのルールで行全体・文章の一部の両方に効く。
    $links = array();

    $with_tokens = preg_replace_callback(
        '/\[([^\]]+)\]\(([^)]+)\)/',
        function ( $matches ) use ( &$links ) {
            $token  = '{{PPP_LINK_' . count( $links ) . '}}';
            $label  = $matches[1];
            $target = $matches[2];

            $looks_like_url = ( false !== strpos( $target, '://' ) )
                || ( 0 === strpos( $target, '#' ) )
                || ( 0 === strpos( $target, '/' ) );

            if ( $looks_like_url ) {
                $url = ppp_encode_url_fragment( $target );
                $links[ $token ] = '<a href="' . esc_url( $url ) . '">' . esc_html( $label ) . '</a>';
            } else {
                $span_class = 'ppp-draft ppp-draft--' . sanitize_html_class( $target );
                $links[ $token ] = '<span class="' . esc_attr( $span_class ) . '">' . esc_html( $label ) . '</span>';
            }
            return $token;
        },
        $text
    );

    // x-enumDescriptionsのkey(用語)・value(説明)内の\nはそのままでは
    // HTML上で改行にならないため、明示的に<br>へ置き換える。
    $escaped = str_replace( "\n", '<br>', esc_html( $with_tokens ) );

    return strtr( $escaped, $links );
}

function ppp_datamodel_table_style() {
    // 列幅を明示しないとブラウザの自動レイアウトが「説明」列の長文に幅を
    // 引っ張られ、「呼称」列が1-2文字分まで圧縮されて階層インデントが
    // 視認できなくなる。table-layout:fixedと列ごとの幅指定でこれを防ぐ。
    static $printed = false;
    if ( $printed ) {
        return '';
    }
    $printed = true;

    return '<style>
        .ppp-datamodel-table table { table-layout: fixed; width: 100%; }
        .ppp-datamodel-table th, .ppp-datamodel-table td { vertical-align: top; overflow-wrap: break-word; white-space: pre-line; }
        .ppp-datamodel-table th:nth-child(1), .ppp-datamodel-table td:nth-child(1) { width: 15%; }
        .ppp-datamodel-table th:nth-child(2), .ppp-datamodel-table td:nth-child(2) { width: 15%; }
        .ppp-datamodel-table th:nth-child(3), .ppp-datamodel-table td:nth-child(3) { width: 9%; }
        .ppp-datamodel-table th:nth-child(4), .ppp-datamodel-table td:nth-child(4) { width: 5%; }
        .ppp-datamodel-table th:nth-child(5), .ppp-datamodel-table td:nth-child(5) { width: auto; }
    </style>';
}

function ppp_enum_table_style() {
    // enum表(多くは用語/定義の2列)はdatamodel/parts表と列構成が異なるため、
    // 共有の.ppp-datamodel-table用スタイル(5列固定の幅指定)をそのまま
    // 使うと崩れる。1列目(用語)20%・2列目(定義)80%の専用スタイルを使う。
    // ControlledPropertyのような3列目以降を持つ構造化表では、3列目以降に
    // 明示的な幅指定が無いため残り80%を均等割りしない点に注意
    // (必要になれば個別に調整すること)。
    static $printed = false;
    if ( $printed ) {
        return '';
    }
    $printed = true;

    return '<style>
        .ppp-enum-table table { table-layout: fixed; width: 100%; }
        .ppp-enum-table th, .ppp-enum-table td { vertical-align: top; overflow-wrap: break-word; white-space: pre-line; }
        .ppp-enum-table th:nth-child(1), .ppp-enum-table td:nth-child(1) { width: 20%; }
        .ppp-enum-table th:nth-child(2), .ppp-enum-table td:nth-child(2) { width: 80%; }
    </style>';
}

function ppp_render_datamodel_table( $data, $table_class = 'ppp-datamodel-table' ) {
    $columns     = $data['columns'];
    $rows        = $data['rows'];
    $col_count   = count( $columns );
    // draft_terms: {用語: バッチラベル}。レビュー未完了のドラフト用語の行に
    // ppp-draft/ppp-draft--{ラベル}クラスを付与し、追加CSSで色分けできる
    // ようにする(色そのものはCSS側の責任、PHP側では固定しない)。
    $draft_terms = isset( $data['draft_terms'] ) && is_array( $data['draft_terms'] ) ? $data['draft_terms'] : array();

    // NOTE: 既存ページのTableブロックと見た目を揃えたい場合、
    // class名を実際のページのHTMLソース(view-source)で確認し、
    // 下記の 'ppp-datamodel-table' を差し替えるか、同じclassを追加してください。
    // スタイルはショートコード関数側(ppp_datamodel_shortcode)で付与する
    // (transientキャッシュには含めず、リクエスト毎に1回だけ出力するため)。
    // $table_classは列幅など表ごとに異なるスタイルを適用したい場合に使う
    // (例: ppp-enum-table。ppp_enum_table_style()参照)。既定のクラスを
    // 追加するのではなく置き換える(同一ページに複数ショートコードが
    // 混在した際、クラス2つ分のCSS詳細度が衝突し出力順序に挙動が左右
    // されるのを避けるため)。
    $class = 'wp-block-table ' . $table_class;
    $out  = '<figure class="' . esc_attr( $class ) . '"><table>';
    $out .= '<thead><tr>';
    foreach ( $columns as $col ) {
        $out .= '<th>' . esc_html( $col ) . '</th>';
    }
    $out .= '</tr></thead><tbody>';

    $total = count( $rows );
    for ( $i = 0; $i < $total; $i++ ) {
        $row      = $rows[ $i ];
        $tr_attr  = '';
        if ( isset( $row[0] ) && isset( $draft_terms[ $row[0] ] ) ) {
            $tr_attr = ' class="' . esc_attr( 'ppp-draft ppp-draft--' . sanitize_html_class( $draft_terms[ $row[0] ] ) ) . '"';
        }
        $out .= '<tr' . $tr_attr . '>';

        if ( count( $row ) === $col_count ) {
            // フル行: 直後に続く「説明列を持たない短い行」の数を数え、
            // 説明セル(最終列)にrowspanを付与する(入れ子の子孫行ぶんをまとめて表示)
            $span = 1;
            for ( $j = $i + 1; $j < $total; $j++ ) {
                if ( count( $rows[ $j ] ) === $col_count - 1 ) {
                    $span++;
                } else {
                    break;
                }
            }
            foreach ( $row as $idx => $cell ) {
                $is_last = ( $idx === $col_count - 1 );
                $attr    = ( $is_last && $span > 1 ) ? ' rowspan="' . (int) $span . '"' : '';
                $out    .= '<td' . $attr . '>' . wp_kses_post( ppp_linkify( $cell ) ) . '</td>';
            }
        } else {
            // 短い行(入れ子の子孫): 説明セルは親のrowspanで既に表示されているので出力しない
            foreach ( $row as $cell ) {
                $out .= '<td>' . wp_kses_post( ppp_linkify( $cell ) ) . '</td>';
            }
        }

        $out .= '</tr>';
    }

    $out .= '</tbody></table></figure>';

    return $out;
}

function ppp_render_hierarchy_table( $columns, $rows, $level_count, $table_class = 'ppp-enum-table-hierarchy', $draft_terms = array() ) {
    // BuildingComponent/Phenomenonのようにサブカテゴリ>分類用語>用語...と
    // 階層が深い、または説明自体が複数列に分かれるenumを描画する。
    // 列数がenumごとに異なりppp-enum-table用の固定幅CSS(20%/80%)が
    // 合わないため、専用クラスを付与しWP側の「追加CSS」でページごとに
    // 列幅を調整する運用とする(ppp_enum_table_style()は適用しない)。
    $row_count = count( $rows );

    // 各行×各階層列について、直前行と列0..cの値が全て一致するかどうかで
    // rowspanのグループ化を判定する(列cの一致判定に列0..c-1の一致を
    // 含めることで、サブカテゴリ列のグループを跨いで分類用語列が
    // rowspanしてしまう事故を自然に防いでいる=入れ子のrowspan)。
    // 値が""の列は同じ""同士でも一致とはみなさない(値が無いだけの
    // 偶然の一致で複数行にまたがってrowspanしてしまうと、後段のcolspan
    // 結合が行ごとに異なる用語列を巻き込んで表が壊れるため)。空値セルは
    // 常にrowspan=1のまま、その行だけでcolspan結合する。
    // rowspan[$i][$c] === 0 の行は親行のセルに含まれるため描画しない。
    $rowspan = array();
    for ( $c = 0; $c < $level_count; $c++ ) {
        $group_start = 0;
        for ( $i = 1; $i <= $row_count; $i++ ) {
            $same_group = false;
            if ( $i < $row_count && '' !== $rows[ $i ][ $c ] ) {
                $same_group = true;
                for ( $k = 0; $k <= $c; $k++ ) {
                    if ( $rows[ $i ][ $k ] !== $rows[ $i - 1 ][ $k ] ) {
                        $same_group = false;
                        break;
                    }
                }
            }
            if ( ! $same_group ) {
                $rowspan[ $group_start ][ $c ] = $i - $group_start;
                for ( $r = $group_start + 1; $r < $i; $r++ ) {
                    $rowspan[ $r ][ $c ] = 0;
                }
                $group_start = $i;
            }
        }
    }

    // columns属性に""(空文字列)の項目があれば、直前の見出しセルの
    // colspanを1つ拡張して、その位置には独立した<th>を出さない。
    // BuildingComponentの様に分類用語がほぼ全行で空のdefで、
    // "サブカテゴリ,用語,,説明"の様に指定すると、見出し・本文とも
    // 常にcolspanが揃った(=分類用語列が実質存在しない)表になる。
    $header_cells = array();
    foreach ( $columns as $col ) {
        if ( '' === $col && ! empty( $header_cells ) ) {
            $header_cells[ count( $header_cells ) - 1 ]['colspan']++;
        } else {
            $header_cells[] = array( 'label' => $col, 'colspan' => 1 );
        }
    }

    $class = 'wp-block-table ' . $table_class;
    $out   = '<figure class="' . esc_attr( $class ) . '"><table>';
    $out  .= '<thead><tr>';
    foreach ( $header_cells as $cell ) {
        $attr = $cell['colspan'] > 1 ? ' colspan="' . (int) $cell['colspan'] . '"' : '';
        $out .= '<th' . $attr . '>' . esc_html( $cell['label'] ) . '</th>';
    }
    $out .= '</tr></thead><tbody>';

    for ( $i = 0; $i < $row_count; $i++ ) {
        $row     = $rows[ $i ];
        // 用語(=階層の最も深いレベルの値)がdraft_termsに載っていれば行全体に
        // 色分け用クラスを付与する。
        $term    = isset( $row[ $level_count - 1 ] ) ? $row[ $level_count - 1 ] : '';
        $tr_attr = '';
        if ( '' !== $term && isset( $draft_terms[ $term ] ) ) {
            $tr_attr = ' class="' . esc_attr( 'ppp-draft ppp-draft--' . sanitize_html_class( $draft_terms[ $term ] ) ) . '"';
        }
        $out .= '<tr' . $tr_attr . '>';

        $c = 0;
        while ( $c < $level_count ) {
            if ( 0 === $rowspan[ $i ][ $c ] ) {
                // 親行のrowspanで既に表示済み。
                $c++;
                continue;
            }

            // 値が""の場合、次の階層列(かつ親行に含まれず表示対象の列)へ
            // colspanで結合する(例: 分類用語""を用語列と結合して表示)。
            $content_col = $c;
            $colspan     = 1;
            while ( '' === $row[ $content_col ] && ( $content_col + 1 ) < $level_count
                && 0 !== $rowspan[ $i ][ $content_col + 1 ] ) {
                $content_col++;
                $colspan++;
            }

            $attr = '';
            if ( $rowspan[ $i ][ $c ] > 1 ) {
                $attr .= ' rowspan="' . (int) $rowspan[ $i ][ $c ] . '"';
            }
            if ( $colspan > 1 ) {
                $attr .= ' colspan="' . (int) $colspan . '"';
            }
            $out .= '<td' . $attr . '>' . wp_kses_post( ppp_linkify( $row[ $content_col ] ) ) . '</td>';

            $c = $content_col + 1;
        }

        // 説明列(階層より後ろ、説明がリスト形式なら複数列)はrowspan/colspan無しでそのまま出力。
        for ( $d = $level_count; $d < count( $row ); $d++ ) {
            $out .= '<td>' . wp_kses_post( ppp_linkify( $row[ $d ] ) ) . '</td>';
        }

        $out .= '</tr>';
    }

    $out .= '</tbody></table></figure>';

    return $out;
}

function ppp_datamodel_notice( $message ) {
    return '<p style="color:#a00;">' . esc_html( $message ) . '</p>';
}
