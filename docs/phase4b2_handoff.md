# Phase 4B2：実モデル導入・計測・評価の引継ぎ

2026-11-06。B1では全て設計のみです。モデル・tokenizer・runtimeの取得、保存先の作成、サービス起動、HTTP通信、課金は実施していません。[Phase 4A計画](phase4b_implementation_plan.md)を以下のgateで具体化します。

## 導入候補・容量・保存先

| 対象 | 候補と確認できた情報 | 未確認・導入前の条件 |
| --- | --- | --- |
| 第一モデル | Qwen3.5-4B、Ollama qwen3.5:4b。tag表示7f3251fa6878、全体4.0GB。model層d8b0f5e9760c、3.3GB、Q4_K_M、4.21B。別に334M/BF16 projectorを含む | 完全digest、全blob容量、tokenizer/template、再配布/利用条件と取得版を再確認。text-onlyでもprojector等の保存/ロードを実測 |
| 小型代替 | qwen3.5:2bはtag dfaf2605162e、全体3.1GB。model層0689d44085e0、2.7GB、Q8_0、projector331M/BF16 | このtagをQ4と扱わない。小型化だけで実メモリ適合を保証しない |
| runtime | Ollama Windows版を第一候補。代替は明示的tokenizer/template制御を検討できるllama.cpp | 導入版・署名/hash・実配布サイズ・自動起動/保存挙動はUNKNOWN。選定と導入を先に承認範囲へ含める |
| モデル保存 | 提案先D:\ONI_AI_Models（未作成）。repo・ユーザープロファイルの外 | 承認された導入時だけ保存設定。実際の設定方法・書込権限・既存ファイル有無を確認 |
| runtime/一時領域 | 提案先D:\ONI_AI_Tools（未作成）。測定ログはrepoのdata/local/配下 | runtimeの実際の配置可否は未確認。ソース管理からモデル/ログを除外 |

公式metadata参照、取得日2026-11-06：[4B tag](https://ollama.com/library/qwen3.5:4b)、[2B tag](https://ollama.com/library/qwen3.5:2b)。metadataを閲覧しただけで重みは取得していません。短い表示digestは完全なartifact固定ではありません。[Phase 4Aの候補・ライセンス比較](phase4a_local_models.md)も再確認します。

読み取り専用の当日ディスク照会でD:の空き835,576,844,288 bytes（約778.19GiB）を確認しました。必要容量の見積りは**単一4Bモデル約4.0GB＋未確定runtime/展開・staging・ログ**で、運用上の初期予約枠を16GiBと提案します。16GiBは測定した必要容量ではありません。導入gateでは全blob＋runtime展開＋一時コピー/復元用コピー＋ログ上限を合計して空き容量と比較します。2Bを同時保存するならその全容量も加え、無料の容量や高速なdownloadを仮定しません。

Phase 4A調査ではi9-12900K、RAM16GiB、RTX4060専用VRAM8,188MiB、空きRAM約3.6GiB/VRAM約5.4GiBでした（11月2日時点）。現在の空きRAM/VRAM、実モデルピーク、速度はUNKNOWNです。重みだけでなくKV cache・context・runtime・projector・CPU offload用RAMを測定し、実行直前に再調査します。CUDAのdriver表示をToolkit導入済みと扱いません。

## B2の最小実装

1. 取得対象・ライセンス・完全digest・保存先・runtime版・容量を記した導入計画を確定し、ユーザーが許可した範囲でのみ導入する。cloud接続・鍵作成・ゲーム接続は含めない。
2. Policyのsocket遮断を維持し、brokerに固定loopback/固定port/固定chat経路のtransportを追加する。redirect、proxy経由、任意URL、任意model名、tools、shell、画像入力を許可しない。runtimeのcloud fallbackも無効であることを確認する。B1ではこのHTTP transportは未実装。
3. モデル＋tokenizer＋chat template＋schema注入の完全な版対応を実装する。正確な入力計数が得られない場合は**生成せず停止**する。UTF8 byte数や文字数/4を代用しない。runtime側のcontext切捨て・特殊token・thinkingを含むusageとの校正が必須。ローカルtokenizer導入が追加で必要なら取得対象に含める。
4. JSON schemaの実対応を短いprobeで確認する。初期案はcontext4,096、入力上限2,048、出力上限1,024（thinking含む）、並列1、同時モデル1。実際のtemplate/schemaで超過したら入力を黙って切らず、開発データ上で知識/履歴の選択設計を見直す。mockのbyte単位予算は流用しない。
5. broker/adapter/studyの三層予算、予約・不明usage、期限とプロセス後始末を実runtimeへ接続する。外部Ollamaサービスは子workerをkillしても生成停止しない可能性があるため、切断時のキャンセルとモデル/サービス資源の解放を実測する。確認できなければ次要求を禁止し、運用者の停止確認まで実験を再開しない。
6. 同じ観測・知識・履歴・操作予算・step上限でexploration、lookahead、LLM Policyを比較する。LLMだけのtoken/時間/費用も別記する。model registry・plan/reportは版を増やして追加し、B1/v1の固定意味を変更しない。

## 実測手順と停止条件

開発条件だけで、起動前RAM/VRAM、cold load、warm生成、入力/出力/思考token、first-token/全応答時間、token/s、ピークRAM/専用VRAM、JSON適合率、根拠整合率、再試行、不明usage、終了/解放を保存します。日本語・英語の同内容入力も開発で比較します。電力費・総所有費はAPI単価0から推定しません。

初期運用案は最大5step/episode、生成期限30秒、episode180秒、再試行は最大1回追加（合計2）、同時要求1。速度未測定のため妥当性は開発pilotで確認し、保留評価前に固定します。長時間放置実験は行いません。

停止条件は、正確counter未対応、schema非対応、usage不一致、残予算不足、部分/不正出力の再試行枯渇、観測/根拠不一致、秘密情報検出、期限超過、worker/runtime異常、キャンセル/解放未確認、OOMです。開始/実行中の空きRAM2GiB未満または空き専用VRAM512MiB未満も初期の保守的運用停止案とします。これらは物理的必要量の実測値ではありません。OSや他アプリを勝手に終了したり、メモリ不足時にcloudへ切り替えたりしません。

## 新しい開発・保留条件

B1のmock seed（4001/4003/5003/5009）とPhase 2/3の公開評価はすべて回帰用です。B2用案は開発1103/1201/1301/1409、保留2101/2203/2309/2411/2503/2609/2707/2801。B1では生成も実行もせず、CLIも実行を拒否します。seedが新しいだけで条件が未知になるとは扱いません。

初期条件の事前登録案（全て合成値、実ONIの仕様ではない）：

| 集合 | 初期資源・不確実性 | 新条件 |
| --- | --- | --- |
| 開発 | water 20～30、energy 8～14、food 10～20、研究値は既知 | 障害1箇所、観測されたwater需要の変動 |
| 保留 | water 3～9、energy 1～5、food 1～7、水/研究の2項目を同時UNKNOWN | 障害2箇所、water需要/研究要求の未使用組合せ |

これは未実装のDRAFTです。B2の開発開始前に全状態/需要の範囲・分布・seed生成法・process属性置換・未知値の配置・操作予算・客観目標を完全に定義し、**保留結果を見る前**にsource/条件hashを確定します。実現可能性の検査も必要ですが、評価seedの攻略結果で条件を選別しません。既存sample_fixtureを新seedで呼ぶだけの実装は採用しません。公開した条件が未見なのは当該モデル/開発手順に対する仮定で、モデル事前学習からの完全分離を保証しません。

開発だけでprompt、schema、時間、履歴長を調整し、固定後に保留を一度開きます。保留を見て修正した場合は回帰用へ降格し、新しい未使用条件を別計画で作ります。各指標の分布・失敗・費用・時間を分け、mock配線成功や合成得点を実ONIの攻略性能として報告しません。固定攻略順・危機別の正解行動表は追加しません。
