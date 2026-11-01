# 設備知識DB設計（Schema 1/2）

Phase 0は設備の知識を根拠付きで保持し、AIへ検索結果を渡す基盤です。攻略手順・設備配置・最適解は埋め込みません。ゲーム状態の一時的な在庫や研究進捗と、設備の恒久仕様は分離します。

## 保存構造

実装：[schema.sql](../src/oni_ai/data/schema.sql)、[knowledge.py](../src/oni_ai/knowledge.py)、[seed.json](../src/oni_ai/data/seed.json)。

| テーブル | キー・項目 | 意味 |
| --- | --- | --- |
| source | source_id、kind、url、revision、accessed_on、content_sha256、note | 根拠資料と版・取得日・テキストハッシュ |
| building_variant | variant_id、building_id、game_version、dlc_scope、identity_status、identity_source_id、identity_locator | ゲーム版とDLC範囲ごとの設備識別子と根拠 |
| fact | variant_id + field、value_json、unit、status、source_id、locator、note | 属性ごとの値・単位・出典・検証状態 |

全テーブルをSQLite STRICTとし、外部キー、主キー、JSON型・数値条件を制約します。user_version=1/2と専用application_idを読み取り時に確認し、未知の版は拒否します。Phase 1の新規DBはSchema 2です。Schema 1は書き換えず読めます。移行はmigrate-dbで別ファイルへコピーする明示的な操作に限ります。

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

Phase 1のcatalog validatorは配列内の型、単位、有限値、material ID、重複、項目単位の根拠、温度上下限、研究条件のALL/ANYを検査します。部分的な数量UNKNOWNはnullとし、既知の0と区別します。SQL制約だけでは配列内の業務ルールを検証できないため、import-catalog前の検証とaudit-dbを併用します。入力は梱包済みのレビュー済みcatalogのみで、Webデータの自動取り込みはしません。

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

読み取りは `mode=ro` と `PRAGMA query_only=ON`。自動作成・暗黙の修復をしません。初期化・コピー移行・catalog取込みだけが明示的な書込みです。新規出力は排他的に作成し、既存ファイルを上書きしません。DBはローカル生成物でGit対象外、SQLとseed/catalogをバージョン管理します。

テストでは一時SQLiteを使用し、UNKNOWNの維持、出典、数値型と単位、SQL注入、版の厳密フィルタ、読み取り専用、上書き防止、DB整合性を確認します。ネットワークsocketを遮断し、ゲームデータに依存しません。

## Schema 2の追加と互換性

schema.sqlは元のSchema 1を維持し、[schema_v2.sql](../src/oni_ai/data/schema_v2.sql)で補助テーブルを追加します。source/building_variant/factの列と既存行は変えません。

| テーブル | 内容 |
| --- | --- |
| source_review | sourceの対象版、根拠箇所、再配布判断、権利メモ、hash範囲 |
| game_rule | 酸素/食料/電力/水/研究の版限定の事実、パラメータ、出典、status |
| rule_binding | 設備バリアントと同じ版/DLC範囲の動作ルールへの関連 |
| resource_identifier | 配列内で使用するmaterial IDの登録。採用前の正規化を明示 |
| catalog_import | catalog IDと内容digest。完全一致の再取込みはno-op、異なる内容の同IDは拒否 |

移行は元DBをmode=roで開いてSQLite backupで新規DBにコピーし、そのコピーへトランザクションで追加します。元の独自行・注記・UNKNOWNは保持します。destinationが存在する場合は停止します。Schema 2から別のSchema 2へのコピーも可能です。

既存sourceには対象版UNKNOWNとREFERENCE_ONLYのレビュー行を追加します。これは再配布許諾を推定するものではありません。既存の未検証な数値は消さず、auditで版の根拠不足を指摘します。Schema 1の読取結果では新しいreview情報はnullですが、取得日等の既存source情報は返します。

catalog取込みは全件検証後に1トランザクションで実施し、途中の衝突は全件rollbackします。出典ID衝突も黙って上書きしません。取込み後は名前だけの元seed3件に加え、Batteryの新IDとPlanterBoxの版別記録、5ルールを保持します。件数と未採用事項は[出典レビュー](phase1_sources.md)を参照してください。

source metadataとルールを設備属性と分離し、UI改善を設備の環境条件として転用しません。ビルド番号は根拠資料の対象版であって実機検証の宣言ではありません。過去ビルドと現行MODによるID対応の関連はSOURCE_REVIEWEDにとどめます。SOURCE_REVIEWEDやREFERENCE_ONLYをGAME_VERIFIEDや包括的転載許可として利用しません。

## Phase 2以降の拡張

特定のゲーム版を検証できる公式資料または使用が認められたexportから、設備の用途・定義を項目単位で追加します。Wiki等を使う場合はライセンス・revision・一次資料との整合も確認します。多言語alias、競合主張の複数保持、履歴、実ゲーム版間の移行は今後の課題です。合成fixtureの任意の量・レートを本DBへ登録しません。
