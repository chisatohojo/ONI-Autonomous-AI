# 設備知識DB設計（Schema 1）

Phase 0は設備の知識を根拠付きで保持し、AIへ検索結果を渡す基盤です。攻略手順・設備配置・最適解は埋め込みません。ゲーム状態の一時的な在庫や研究進捗と、設備の恒久仕様は分離します。

## 保存構造

実装：[schema.sql](../src/oni_ai/data/schema.sql)、[knowledge.py](../src/oni_ai/knowledge.py)、[seed.json](../src/oni_ai/data/seed.json)。

| テーブル | キー・項目 | 意味 |
| --- | --- | --- |
| source | source_id、kind、url、revision、accessed_on、content_sha256、note | 根拠資料と版・取得日・テキストハッシュ |
| building_variant | variant_id、building_id、game_version、dlc_scope、identity_status、identity_source_id、identity_locator | ゲーム版とDLC範囲ごとの設備識別子と根拠 |
| fact | variant_id + field、value_json、unit、status、source_id、locator、note | 属性ごとの値・単位・出典・検証状態 |

全テーブルをSQLite STRICTとし、外部キー、主キー、JSON型・数値条件を制約します。user_version=1と専用application_idを読み取り時に確認し、未知のDBを誤って開かないようにします。スキーマ移行は未実装で、異なる版は明示的に拒否します。

同一building_idでもゲーム版・DLC組合せごとにvariantを分けます。dlc_scopeは将来「BASE_GAME」「有効DLCのソート済みID集合」等の正規表現に統一する予定です。現段階では資料不足のため `UNKNOWN` を使用し、どのゲーム版にも合うワイルドカードにはしません。バージョン・DLCフィルタは完全一致です。

## 属性と値の約束

| field | 既知値の型 | 単位・詳細 |
| --- | --- | --- |
| name | 文字列 | 資料上の表記。公式訳・別名・言語別名称の正規化は今後 |
| purpose | 文字列 | 用途の根拠がある場合だけ保存 |
| construction_materials | 配列 | 各itemにslot、material_category、候補tag、mass_kgとその根拠を持たせる想定 |
| power_consumption_w | 0以上の数 | unit=W、稼働時消費電力。待機・条件依存はnoteへ |
| power_generation_w | 0以上の数 | unit=W、発電出力。消費電力と別 |
| inputs / outputs | 配列 | material_id、amount、unit、条件、供給/排出方式を扱う想定 |
| temperature_constraints | 配列 | operating_min/max、overheat等の種類、値、unit=K、条件を扱う想定 |
| environment_constraints | 配列 | 圧力、液没、空間、床・支え、雰囲気等の条件 |
| research | 配列 | 研究IDとAND/OR関係。観測中のunlocked boolとは別 |

配列要素を取り込む自動インポータは未実装です。SQLはトップレベルの型・出典を検証し、配列内部の業務ルールまでは検証しません。今後インポータでレート単位（kg/s等）、有限値、material tag、条件、部分UNKNOWNを検証し、異なる根拠が混じる場合はitem単位の出典を必須にします。検証器ができるまで複雑な数値・配列の自動登録は行いません。

## UNKNOWNと検証状態

- **UNKNOWN**：SQL NULL、unit=NULL。検索結果では値を文字列 `UNKNOWN` として返します。0、false、空配列、設備に適用されないという意味にはしません。
- **SOURCE_REVIEWED**：固定資料中に記載を確認。実ゲーム検証済みではありません。
- **GAME_VERIFIED**：特定のゲーム版・DLC・環境で値を検証し、観測記録を根拠として保持した状態。Phase 0には存在しません。
- **CONFLICTED**：資料や観測が競合。決定用の確定値として利用しません。候補値と競合理由をローカル記録に残し、将来は複数主張テーブルへ拡張します。現スキーマは各属性につき現在の主張1件です。

既知値にはsource_idとlocatorが必須です。UNKNOWNに勝手な値を付けることをDB制約で拒否します。数値0は実際に根拠がある場合のみ保存でき、UNKNOWNとは区別します。資料の例示値をゲーム仕様に転用しません。既知の空配列を保存する場合も「該当なし」を確認した根拠が必要です。

AIは各factのstatusを必ず確認し、UNKNOWN・CONFLICTEDに依存する判断を確定しません。SOURCE_REVIEWEDも適用版UNKNOWNなら現在のゲーム仕様と断定しません。

## Phase 0サンプル

3件・30属性を持ち、既知属性は名称3件だけです。IDと名前の対応をOniMcpの固定ソース・資料から採りました。用途、建設資材、電力、入出力、温度・環境、研究、適用DLC、ゲーム版はUNKNOWNです。

| building_id | 名称 | 根拠 |
| --- | --- | --- |
| Tile | tile | PlanBuildingAliasesの英語keyとIDの対応 |
| PlanterBox | planter box | 同上 |
| ManualGenerator | Manual Generator | API開発者ガイドのpreview例の説明とprefabId |

根拠のコミットは `14c08591cbd0bf66cd0f53b37bfb498bdef4abf6`。URL・locator・SHA256はseedと検索結果に保存します。これは**インターフェース語彙のサンプル**で、ゲーム定義を網羅したDBではありません。ガイドの400kg等の例示値は取り込みません。

## 検索とファイル管理

`KnowledgeRepository.search(query, game_version=None, dlc_scope=None, limit=20)` はID・名称・用途の部分一致を返します。SQLパラメータを束縛し、%と_を通常文字としてエスケープします。空queryと範囲外limitを拒否、上限100、返却順を固定します。SQLite LIKEの英字大小無視を利用し、非ASCIIの大小・表記揺れ・日本語読みの正規化は未実装です。

読み取りは `mode=ro` と `PRAGMA query_only=ON`。自動作成・暗黙の修復をしません。初期化だけが明示的な書込みで、ファイルを排他的に作成し、既存DBを上書きしません。DBはローカル生成物でGit対象外、SQLとseedをバージョン管理します。

テストでは一時SQLiteを使用し、UNKNOWNの維持、出典、数値型と単位、SQL注入、版の厳密フィルタ、読み取り専用、上書き防止、DB整合性を確認します。ネットワークsocketを遮断し、ゲームデータに依存しません。

## 次の拡張

source取得許諾を確認した後、公式資料または承認された観測exportから、用途・定義を項目単位で追加します。Wiki等を使う場合はそのライセンス・revision・一次資料との整合も確認します。JSON配列の検証器、多言語alias、複数の競合主張、履歴、バージョン移行、ゲームルール・操作仕様の別テーブルは、必要なデータが得られた段階で追加します。
