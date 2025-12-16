```mermaid
flowchart TD
    Start([セッション開始 /start]) --> Init[全候補者をロード]
    Init --> CheckCount{候補者数は？}

    %% 質問ループ
    CheckCount -- 2人以上 --> CalcScore[全質問のスコア計算\n(Yes/No分割効率 x 重み)]
    CalcScore --> SelectQ[最高スコアの質問を選択]
    SelectQ --> AskQ[/質問を表示/]
    AskQ --> UserAns[/ユーザー回答 Yes/No/Unknown/]
    
    UserAns -- Yes --> FilterYes[特徴を持つ候補のみ残す\n(矛盾する特徴も自動除外)]
    UserAns -- No --> FilterNo[特徴を持たない候補のみ残す]
    UserAns -- Unknown --> KeepAll[絞り込まず維持]
    
    FilterYes --> UpdateHist[履歴・ステップ数更新]
    FilterNo --> UpdateHist
    KeepAll --> UpdateHist
    UpdateHist --> CheckCount

    %% 推測フェーズ
    CheckCount -- 残り1人 --> Guess[/その人物を推測/表示/]
    Guess --> IsCorrect{正解？}
    IsCorrect -- Yes --> Win([正解画面表示 / 終了])
    IsCorrect -- No --> Exclude[その人物を除外リストへ]
    Exclude --> RunnerUp{次点の候補\n(不一致少)はいる？}
    RunnerUp -- Yes --> Guess
    RunnerUp -- No --> RecoveryCheck

    %% リカバリーフェーズ
    CheckCount -- 0人 --> RecoveryCheck{リカバリー\n試行回数 < 3 ?}
    RecoveryCheck -- Yes --> SearchMiss[全データから不一致\n3つ以内の人物を探索]
    SearchMiss --> Found{見つかった？}
    Found -- Yes --> Restore[候補リストを復元]
    Restore --> CheckCount
    Found -- No --> GiveUp
    RecoveryCheck -- No --> GiveUp([降参 / ユーザーに正解を聞く])
    
    GiveUp --> Learn[/新規学習: 入力された名前を\nWikiから収集して追加/]
    Learn --> End([終了])
```