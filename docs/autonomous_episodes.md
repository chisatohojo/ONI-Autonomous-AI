# Phase 2：合成環境の自律エージェント基盤

対象は任意の合成資源モデルだけです。実ゲーム接続、外部LLM、課金、学習済み攻略Policyはありません。実装は[episodes.py](../src/oni_ai/episodes.py)、[policy.py](../src/oni_ai/policy.py)、[episode_knowledge.py](../src/oni_ai/episode_knowledge.py)、[benchmarks.py](../src/oni_ai/benchmarks.py)です。

## 処理の流れ

```mermaid
flowchart LR
    O[匿名化観測 / digest] --> Q[Policy.queries]
    Q --> K[合成仕様・DB snapshot検索]
    K --> P[Policy.propose]
    P --> V[スキーマ・根拠・UNKNOWN・前提検証]
    V --> D[コピー上のdry-run]
    D --> S[合成環境へ適用]
    S --> E[独立した指標・終了条件]
    E --> M[不変の履歴]
    M --> O
```

1 attemptは検索と提案を1回試みる単位です。拒否・Policy例外もattemptとして記録します。適用された行動だけが合成tickを進めます。終了判定は初期目標、実行エラー、同じ行動の反復、目標到達、連続エラー、進展停止、最大attemptの順に処理します。

## 交換可能なPolicy

Policyはname、queries(PolicyInput)、propose(PolicyContext)を実装します。queriesは1..8件のKnowledgeQueryを返し、proposeは構造化JSONオブジェクトまたはJSON文字列を返します。Policy自身には環境の実行口を渡しません。

PolicyInputは現在観測と目標のJSON文字列、過去のMemoryEntryのtupleです。PolicyContextには取得されたEvidenceのtupleと、明示すべきUNKNOWN/適用不明のID一覧を加えます。各dataclassはfrozenで、入れ子もJSON文字列・tupleとして共有可変状態を避けます。

梱包するSeededTestPolicyはseedで再現できる汎用の操作スキーマ探索です。観測中に存在するprocessに対してwait/set_process/clear_blockageから候補を生成し、乱数で選びます。特定の資源名、危機別の正解、建設順、fixture名で分岐しません。知能や攻略性能を示すPolicyではなく、無効な提案も発生するテスト用です。受け取った履歴を理由に含め、別Policyへの交換と失敗履歴による提案修正はテストしています。

Policyへ渡す観測にfixture_id、description、split、環境seed、元process名はありません。episodeには不透明なUUIDを発行し、process名をp0000等へ置換します。processの実際の入出力・研究条件・現在の有効/障害状態は観測可能です。分布の違いを状態から推測できることを防ぐ仕組みではなく、正解ラベルを渡さない境界です。

## スキーマと根拠

[policy_schemas.json](../src/oni_ai/data/policy_schemas.json)はPolicy用の観測schema_version=2、提案schema_version=1、Decision、KnowledgeQueryを定義します。Phase 1の観測schema_version=1と明示行動CLIは変更していません。

提案のトップレベルはschema_version、observation_digest、decisionだけです。decisionには既存のaction、rationale、evidence_refs、unknownsを含めます。actionにはepisode context、現在tick、一意のaction_idが必要です。理由は簡潔な説明として保存し、内部の思考過程や未提供の推論記録は求めません。

知識を次の2種類に分けます。

- model:actions、model:transition、model:objective、model:process:p0000等は、そのepisodeの合成仕様です。processの仕様と現在のenabled/blockedは分離し、後者を静的知識から推定しません。
- db:fact、db:ruleは既存SQLiteから読み取り専用で取り出すsnapshotです。版・DLCは完全一致で検索し、status、出典、UNKNOWNを保存します。実ゲームの事実を別物の合成モデルの実行根拠には使えません。初期テストPolicyはmodelを検索し、独自Policyはbuilding/ruleも検索できます。

検索結果は最大64件、DB snapshotは最大512件です。取得されていないIDや存在しない根拠は拒否します。観測のscalarはobs:/resources/energy等のJSON Pointerで参照でき、nullを既知の数値として参照できません。全行動にmodel:actions、対象processがある場合はそのmodel仕様の参照も必要です。取得した根拠の存在は、自由記述の理由の真実性を自然言語で証明することとは別です。

## 検証と模擬実行

- 観測digest、context、tick、提案IDを照合し、古い状態・別episode・重複提案を拒否します。
- 未対応の操作、未知target、空の理由、根拠不足、不適合なDB根拠、未知情報の未申告を拒否します。UNKNOWNを0へ補完しません。
- Policyからのdry_runだけの提案は実行行動として拒否します。runnerは実行前に別のコピーでdry-runします。
- 有効になる対象processについて、入力不足、未知の入出力、未達研究条件、障害を検査します。他のprocessとの同時入力競合もPhase 1の保守的な規則で判定します。
- waitは資源を消費する設備命令ではなく時間進行です。待機後の需要不足や他processの停滞は結果として記録し、生存の代理指標へ反映します。需要不足を隠すために待機を一律拒否しません。
- 適用は環境のコピー上で実行し、成功時だけ公開します。予期しない実行例外では元の状態を維持し、エピソードを終了します。

## 終了条件と記憶

EpisodeConfigはmax_steps=30、no_progress_limit=12、repeat_limit=6、error_limit=4、memory_limit=16が既定で、各1..200に制限します。step上限は試行回数であり、tick上限とは異なります（1行動は最大10 ticks）。

提案は最大64K文字、ログは最大20MBです。ログ予算に近づいた場合は未記録の状態変化を公開せず、LOG_SIZE_LIMITイベントとsummaryを残して停止します。過大なheaderは作成前に拒否します。プロセス強制終了やディスク書込み失敗による不完全ログは、replayで完了した結果として扱いません。

進展は指定した目標資源の、これまでの最良値の改善で判定します。資源の単位を混ぜた総合報酬は作りません。同一行動の判定ではaction_id・context・tickを除外し、IDの付け替えで反復判定を回避できないようにします。同一意図がrepeat_limit回目に達した提案は適用しません。Policy例外や拒否が連続した場合はerror_limitで停止します。

最初から目標達成ならGOAL_ALREADY_MET、目標値自体を観測できなければUNKNOWN_GOALで、Policyを呼ばず終了します。履歴は全件ログへ保存し、Policyには直近memory_limit件を渡します。履歴には決定・前後観測・失敗・指標が含まれます。

## 指標とfixtureの分離

各episodeでsurvival、resources、progress、validityを独立に記録します。

- survival.synthetic_demand_proxyは、実行中に合成の酸素/食料需要を満たせたかの代理指標です。違反を確認すればfalse、確認できなければnullです。死亡・人口の物理モデルではありません。
- resourcesは現在量をそのまま保持し、未知値はnullです。
- progressはwork/researchの初期値との差と、独立に指定された目標の到達状態です。
- validityはattempt・applied・rejectedと無効試行率です。無効試行率は拒否/全attemptで、Policy例外も拒否として含みます。試行0件なら率はnullです。

開発用と評価用はsynthetic-benchmark/1の別乱数名前空間を使います。開発の初期食料量は10..20、評価は0..7で重複しません。評価には追加process、研究条件、複数の障害、seedに応じた酸素/水/研究のUNKNOWNを含めます。環境seedとPolicy seedは別々です。これらは合成の保留条件であり、汎化やONI攻略性能を主張するベンチマークではありません。

## エピソードログと再現

episode_headerには元のfixture、設定、目標、知識snapshot、それらのdigest、Policy名、再現用split/seedを記録します。episode_stepには検索、取得根拠、提案、検証結果、前後状態、失敗、指標、終了判定を記録し、episode_summaryで完結します。既存ファイル・benchmark出力ディレクトリは上書きしません。JSONLはGit対象外です。

episode-replayは元DBやPolicyを使わず、snapshotから検索し直し、提案の妥当性・状態遷移・指標・終了条件を再計算します。切れたログ、差分のある状態/根拠/指標/終了判定を拒否します。Policy/実行例外は記録済みの故障イベントとして再現します（元の例外原因の再実行ではありません）。改ざん防止署名やPolicyの内部判断の証明はありません。

## 今後のLLM接続案と制限

将来のLLMアダプタも同じPolicyを実装し、匿名化観測・検索可能な仕様・取得根拠・目標・直近履歴だけを入力にします。検索要求と提案は構造化JSONに限定し、実行権限・検証・予算・停止・ログはrunner側に残します。fixtureラベル、評価seed、正解行動表をプロンプトに入れません。

導入前に提供元・料金上限・送信範囲・キー管理・応答期限・再試行上限を決め、APIキーは環境変数等から渡してログに残さない設計にします。今回API通信やSDK追加はありません。同期Policyが永久に戻らない場合を中断する強制タイムアウトや、信頼できないPythonコードのsandboxは未実装です。将来は別プロセス/期限管理を検討します。

現モデルには地形・移動・温度・実電網・複製人間AI・実レシピはなく、根拠照合も自然言語の理由すべてを意味的に検証するものではありません。知識DBのUNKNOWN、OniMcpの文書差異、実機互換性、規約と許諾の未確認は引き続き残ります。
