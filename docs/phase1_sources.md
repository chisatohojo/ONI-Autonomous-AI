# Phase 1：知識の採否と出典

取得・確認日：2026-11-01（Asia/Tokyo）。追加データは一次資料を読んで独自に記述した少数の事実要約です。攻略手順・記事本文・画像・ゲームアセット・第三者DBのdumpは含めません。

## 採用範囲

| source_id | URL・対象ビルド | 根拠箇所 | 採用した事実 |
| --- | --- | --- | --- |
| klei_210320 | [Klei 210320](https://kleiforums.com/game-updates/oni-alpha/210320-r221/) | Update Information / planter box side screen | 植物の必要条件を表示するUIの改善。必要量や研究条件は記載なし |
| klei_326232 | [Klei 326232](https://kleiforums.com/game-updates/oni-alpha/326232-r734/) | Fixes and Improvements / Buildings | 酸素が少ないときの呼吸不能領域での息止め、消耗した電池から変圧器へ給電しないこと |
| klei_348553 | [Klei 348553](https://kleiforums.com/game-updates/oni-alpha/348553-r798/) | 冒頭の出力温度計算変更 | 従来固定温度だった出力を下限とする変更、水浄化設備の例40°C。現行版への継続適用は未確認 |
| klei_659901 | [Klei 659901](https://kleiforums.com/game-updates/oni-alpha/659901-r2496/) | QoL & bugs for all versions | 建設メニュー・研究画面で曖昧/同義語/頭字語検索。研究前提を示す資料ではない |
| aliases | [OniMcp固定コード](https://github.com/LIghtJUNction/OniMods/blob/14c08591cbd0bf66cd0f53b37bfb498bdef4abf6/mods/OniMcp/Tools/Impl/Build/BuildPlanTextAliases.cs) | PlanBuildingAliases() | PlanterBox/Batteryの識別子の対応。ゲーム版UNKNOWN、過去ビルドのID実機照合は未実施 |

追加は設備ID **1件（Battery）**、版別バリアント **2件（PlanterBox/210320、Battery/326232）**、ルール **5件**、設備とルールの関連 **2件**です。元の3バリアントと既知属性は保持します。取込み後は4設備ID・5バリアント・50属性（既知の名称5件、UNKNOWN45件）です。

UIの情報を環境制約へ転記せず、ルールとして保存します。今回新たな設備入出力レート、建設資材量、消費/発電電力、研究前提、DLC要件を確定した件数は**0件**です。水のルールに記録した40°Cは資料の例示であり、設備全体の仕様を補完する値ではありません。

ビルド番号は資料が対象とする版を示し、その版を実行して測定したという意味ではありません。全件SOURCE_REVIEWED、GAME_VERIFIEDは0件。版/DLCは検索時に完全一致し、UNKNOWNやALL_DECLAREDは現在版・未来のDLCへのワイルドカードにはなりません。ALL_DECLAREDは659901の記事がその時点の全バージョン向けと説明している範囲だけです。

## 権利と証跡

各sourceに取得日、URL、revision、target_version、locator、content_sha256、hash_scope、redistribution、rights_noteを記録します。公式記事はREFERENCE_ONLYで、本文・アセットの包括的な再配布許可はUNKNOWNです。独自の短い事実要約と参照だけを公開候補にします。上流コードも本文を組み込まず、識別子と参照のみです。

公式記事のcontent_sha256は、根拠確認時に選んだ短い抜粋をUTF-8/LFにしたハッシュであり、ページ全体のハッシュではありません。抜粋はGit対象外の.tools/phase1-evidenceに保持します。hash_scopeにこの範囲を明記しています。これはページの不変性や権利許諾を証明するハッシュではありません。OniMcpコードは固定コミットとblob SHAに加え、取得テキスト全体のハッシュを記録します。

## 採用しなかった情報

- Wiki/第三者設備DBからのレート・資材・研究データの一括取得は実施していません。現在版・再配布条件・一次根拠を揃えられない値は入れません。
- 219035の旧フォーラム記事は検索結果で内容を確認できましたが、直接取得が403でした。今回は直接本文を確認できた210320のUI記録に絞りました。
- 古い不具合報告や利用者コメント、攻略サイトの数値は確定仕様として採用していません。
- ONI本体のDLL、ゲーム内DB、セーブ、Workshop配布物は取得・解析・実行していません。

酸素・食料・電力・水・研究の基本設備仕様は依然不足しています。次は、使用が認められた特定版の公式exportや資料を確保し、項目ごとの根拠を追加します。件数を増やす目的で未知の設備を登録しません。
