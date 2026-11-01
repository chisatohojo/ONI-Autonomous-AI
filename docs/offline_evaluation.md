# オフライン実験・評価基盤 v1

実装は[simulation.py](../src/oni_ai/simulation.py)、[contracts.py](../src/oni_ai/contracts.py)、[evaluation.py](../src/oni_ai/evaluation.py)。全データはMOCK_SYNTHETIC_NOT_GAME_DATAです。ONIシミュレーション、MCPサーバー、ゲーム用実行アダプタではありません。

## fixture一覧

| fixture | 状態 | 評価で区別する点 |
| --- | --- | --- |
| normal | 合成資源に余裕、作業可能 | 不足なし・作業進捗 |
| oxygen_shortage | 酸素0、対応process無効 | 既知の0、不足した需要 |
| food_shortage | 食料0、対応process無効 | 食料の不足 |
| power_shortage | 電力相当0、供給process無効 | 入力不足と作業停滞 |
| work_stalled | 作業processに明示的な障害 | BLOCKEDと進捗なし |
| water_shortage | 水相当0 | 依存processの入力不足 |
| research_locked | 作業に未充足の合成研究条件 | 研究条件と作業停滞 |
| unknown_oxygen | 酸素観測null | UNKNOWNを0や十分な量へ変換しない |

データは[data/synthetic_fixtures.json](../src/oni_ai/data/synthetic_fixtures.json)に集約。独自のbaseに各初期状態を適用して読み込みます。実ゲーム由来fixtureは0件です。量・レート・閾値・単位・研究条件はすべて実験用で、ONIの資源値や設備性能から転記していません。1 tickはゲームの秒・cycleを表しません。

## 観測・行動スキーマ

[experiment_schemas.json](../src/oni_ai/data/experiment_schemas.json)はJSON Schema 2020-12の$defs/action、observation、decisionを提供します。参照先はローカルの定義で、実行時のスキーマ取得通信はしません。Python dataclass/validatorが実際の型・有限値・条件を検査し、外部jsonschemaパッケージは追加しません。

観測はschema_version、model_version、fixture_id、context_id、tick、資源、process、警告、provenanceを持ち、game_version/dlc_scopeはUNKNOWNです。資源nullは未知、0は測定された合成の0です。

| 合成行動 | 引数 | 効果 |
| --- | --- | --- |
| wait | ticks=1..10 | 入力された回数だけ合成遷移 |
| set_process | target、enabled(bool) | 指定processの有効状態を変更し1 tick進む |
| clear_blockage | target | 合成障害を解除し1 tick進む |

全行動にaction_id、context_id、expected_tickが必要です。古い観測、別context、既に適用したID、未知targetは状態を変えずREJECTED。dry_runはコピー上の予測をPREVIEWで返し、実状態・tick・ID使用状態を変えません。モデル数値のオーバーフロー時は行動全体を巻き戻します。

これら3行動に実ゲームAPIとの直接対応はありません。任意tool名、URL、コード、raw座標の実行口を設けません。将来の実ゲーム操作可否は[operation_catalog.json](../src/oni_ai/data/operation_catalog.json)の固定コード証跡に別記し、全件live_execution_allowed=falseです。コード経路の存在は実行許可や実機互換性を意味しません。

## 状態更新の約束

各tickでは、有効かつ障害がなく合成研究条件を満たすprocessを候補とします。入力/出力に未知の資源があればそのprocessを進めません。同時に必要な入力の総量が在庫を超える場合、その資源を取り合うprocessをすべて見送り、勝手に優先するprocessを選びません。

実行可能なprocessの入出力を同時適用した後、合成需要を差し引きます。在庫を負にせず、満たせなかった需要を別の失敗要因として記録します。同一tickの新しい出力を別processの入力として先取りしません。ONIの電網・地形・拡散・温度・複製人間AI・レシピ・経路探索はモデル化していません。

## ログ・評価・再現

run_experimentは1..100件の明示的なDecisionを受け、排他的新規作成のJSONLにheader、step、summaryを保存します。headerにはfixture全体、モデル版、初期観測、fixture hash、stepには行動・判断根拠・evidence_refs・unknowns・前後状態・適用/拒否/preview・失敗要因・指標を記録します。既存ログを上書きしません。

指標は資源の不足/未知、需要不足、作業・研究の差分、未完作業の停滞です。APPLIEDは入力した合成行動を受け付けた意味で、目的達成や生存を保証しません。固定の攻略順や単一の総合点は作らず、目標に応じた比較は将来のエージェントへ分離します。

replayは同じfixture・行動から再計算し、記録の順序・初期状態・結果・最終状態を照合します。不完全ログや状態/fixtureの不一致を拒否します。これは自己整合性の検証であり、第三者署名や判断根拠の真実性の証明ではありません。evidence_refsは呼出側の申告として明記し、Phase 2でDBの出典へ照合します。

生成ログはdata/localへ置き、*.jsonlもGit対象外です。判断根拠へ秘密情報を入力しないでください。実行時のネットワーク、モデルAPI、ゲーム接続は使用しません。
