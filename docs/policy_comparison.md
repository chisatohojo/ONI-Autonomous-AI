# Phase 3：Policy比較・検証境界

対象は合成モデルだけです。Phase 0〜2のDB・遷移・テスト・ログ契約を保持し、[research.py](../src/oni_ai/research.py)と[comparison.py](../src/oni_ai/comparison.py)を別層に追加しました。実ゲームやモデルサービスへの接続はありません。

## Policyと共通入力

[ResearchPolicy](../src/oni_ai/research_policy.py)はPhase 2のPolicyインターフェースに、構造化主張を含むenvelopeを被せます。両Policyが同じmodel/building/rule検索を行い、同じ観測範囲・目標・検索結果・UNKNOWN・直近履歴を受け取ります。観測にはfixture名、元process名、split、環境seedを含めません。比較ペア内では初期状態・context ID・Policy seedも一致させます。行動が異なった後の状態や履歴は当然異なります。

- **exploration**：Phase 2のSeededTestPolicyを変更せず使用。追加wrapperは検索情報と主張の形式を共通化します。元の同seed・同contextで同じ行動を出すことをテストしています。
- **lookahead**：観測と検索した合成transition仕様から予測用環境を構成し、待機、各processの有効/無効切替、障害解除を列挙します。コピーで予測し、実行前提を満たさない有効process候補を除外します。1手目の上位8候補について2手先まで調べ、最初の行動だけを提案し、次の観測で再計画します。

lookaheadは辞書式に、既知の需要違反数、未知の需要数、正規化した目標不足量、需要/閾値を基準に上限3まで数えた資源余裕を評価します。資源名ごとに対応行動を決めません。入力費用・生成物・研究条件・障害は予測と実行可能性に反映されます。直近4件の失敗意図と反復回数を同点時の減点とし、残る同点をseed付き乱数で処理します。

これは正解表ではありませんが、人が選んだ探索深さ・beam幅・評価式を持つ合成モデル向けの非学習Policyです。深さ2を超える依存関係や非需要資源の長期保全を最適化する保証はありません。予測には既知の合成モデルを用い、実ONIを模倣できるとは扱いません。DBはstatus/版/出典/UNKNOWNを伴う背景知識として検索・引用し、実ゲームの主張を別物の合成transitionの根拠にはしません。

## 構造化主張と検証

[research_boundary.py](../src/oni_ai/research_boundary.py)で次のenvelopeを検証します。

```json
{
  "schema_version": 1,
  "proposal": {"schema_version": 1, "observation_digest": "…", "decision": {"action": {}, "rationale": "…", "evidence_refs": [], "unknowns": []}},
  "claims": [{"evidence_id": "取得したID", "pointer": "", "value": {}, "status": "元のstatus"}]
}
```

このJSONは構造を説明する省略例であり、実行用の有効な行動例ではありません。proposal自体はPhase 2契約です。claimsは1..64件で、根拠ID、JSON Pointer、取得値、statusを照合します。空Pointerは元の主張全体、非空Pointerはその一部を指します。行動が参照したmodel根拠は全体のclaimが必須です。数値0、false、null、文字列UNKNOWNは区別します。未知の主張の値やstatusをGAME_VERIFIED等へ書き換えると拒否します。

古いcontext/tick/digest、未取得の根拠、未対応操作、資源・研究・障害の前提、UNKNOWN未申告、同一行動の反復は既存EpisodeEngineと追加validatorで検査します。schema/claim拒否は実行口へ通さず、状態を変えない無効試行として記録します。自然言語の理由が主張を正しく解釈したか、主張から行動の最適性が導けるかは完全には検証しません。

## Policy時間制限

[policy_process.py](../src/oni_ai/policy_process.py)はspawnした専用プロセス内で信頼済みのPolicyだけを動かします。JSONを一時ファイルとEventで交換し、pickleによるPolicy応答の復元や、停止した受信側への無期限のpipe送信を避けます。子側でもsocket作成・名前解決を遮断します。

既定は1呼出し2秒、episode全体60秒、起動10秒、400呼出し、入力1MB、出力65,536 bytesです。全体時間には起動とrunner処理も含まれます。呼出し・バイト・時間の超過、子の異常終了、例外で終了します。期限超過時はterminate→最大2秒join→必要ならkill→最大2秒joinで生存を確認し、一時ファイルを削除します。終了確認できなければ完了ログを作らずエラーにします。スレッドが残ったままのtimeoutを強制停止とは呼びません。

これはOS sandboxではなく、任意の悪意あるコード・外部実行ファイル・子孫プロセスの完全隔離を保証しません。Pythonの起動やOS/ディスク操作自体のハードリアルタイム保証もありません。CLIのPolicy名は2つの組込み実装だけです。信頼できないプラグインの読込み口はありません。

## 比較プロトコルと分離

1. comparison-prepareがパッケージのPython/JSON/SQLのSHA256、設定、DB snapshot、全seedをplan.jsonへ記録します。以後ソースdigestが違う場合は実験を拒否します。
2. developmentだけを実行します。6環境seed×3 Policy seed×2 Policyで36件です。
3. comparison-freezeが開発ログ・JSON・CSV・Markdownを検証して、開発reportのSHA256とソースdigestをfreeze.jsonへ排他的に記録します。
4. その後regression/heldoutを解禁します。開発reportやソース変更を検出すると拒否します。出力先とログは上書きしません。

| 区分 | 環境seed | 位置付け |
| --- | --- | --- |
| development | 0, 1, 2, 17, 42, 101 | Phase 2の開発分布 |
| regression | 0, 1, 2, 17, 42, 101 | Phase 2で既に結果が公開された評価分布。保留評価とは呼ばない |
| heldout | 203, 307, 409, 503, 607, 709, 811, 907 | 設計前に列挙し、実装・開発固定後に初めて実行する新seed |

Policy seedは全区分で0,1,2。両Policyともmax_steps=30、no_progress=12、repeat=6、error=4、memory=16と上記ProcessBudgetを共用します。開発/評価はPhase 2の別乱数名前空間と非重複の初期食料範囲を継承し、評価にはUNKNOWN・追加process・研究条件があります。単体テストの比較seedは1000/2000/3000で、実験の保留seedはテストで使いません。

fixture生成コードや分布自体は既知です。新seedの結果未観測を保証する手順であり、完全に新しいゲームや未知分布への汎化試験ではありません。公開後はこのheldoutも回帰集合となり、次の調整では新しい保留集合が必要です。信頼済みPolicyにラベルを渡さない実装と手続き上の固定であり、評価データへの悪意あるファイルアクセスをOSで防ぐ仕組みではありません。

## ログと指標

research_headerにfixture・DB snapshot・設定・Policy・再現情報とdigest、research_stepに検索・応答envelope・検証失敗・Phase 2 step、research_summaryに指標と終了理由を保存します。Phase 2ログとは別versionです。最大20MBで、予算停止時は未記録の候補を破棄してLOG_SIZE_LIMITとsummaryを残します。プロセス中断・ディスク異常等でsummaryがなければ不完全ログとして拒否します。

- 目標：goal_met。UNKNOWNは欠損として分母から除き、既知件数/欠損件数を併記します。
- 資源：初期値・残量・純変化、状態減少量の代理指標、要求需要、合成のprocess入力＋実際に満たした需要の消費量。消費台帳は同時入力割当・障害・研究・UNKNOWNを反映し、毎stepの残高と照合します。UNKNOWNな需要の消費量はnullです。
- 需要充足：Phase 2の酸素/食料需要の代理指標。true/false/nullの分布を別に示し、生存そのものとは扱いません。
- 行動：attempt、適用、拒否、無効率、tick数、作業停滞、失敗step、終了理由。
- 再計画：意図変更、拒否後の変更・適用、失敗後に理由数が減った回数/作業が進んだ回数。変更が改善であると断定する指標ではありません。
- UNKNOWN：初期/終端の未知資源数、未申告拒否、claim拒否、step結果にUNKNOWN_RESOURCEを含む回数。最後の指標はwait中の他processの停止も含み、未知資源を対象にした不正命令の数とは限りません。

report.jsonとmetrics.csvに全指標、summary.mdに概要を出します。平均・母標準偏差・範囲・既知数・欠損数、終了理由分布を保存します。Policy seed反復は同一環境に従属するため、ペア差は環境内で平均してから環境間の分布を計算します。検定・有意差・優越性は主張しません。小さい差や需要UNKNOWNを無視して総合的な改善と結論しません。

research-replayはPolicy/元DB/プロセスなしでclaim照合・検証・遷移・指標・終了を再計算します。comparison-verifyはさらにペア条件、plan、集約、CSV、Markdownを照合します。timeoutや実行例外は記録イベントとして再現し、元のハングや例外原因を再実行しません。cleanup_verifiedも記録された実行時の確認であり、replay時の再実行証明ではありません。ログ署名はありません。
