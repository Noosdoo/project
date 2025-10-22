import pandas as pd
import time

def setup_database():
    """
    対象（キャラクター）とその特徴（質問）のデータベースを作成します。
    1 = Yes (はい), 0 = No (いいえ)
    """
    data = {
        '対象': [
            'ドラえもん', 'ピカチュウ', '孫悟空', '江戸川コナン', 
            'ハローキティ', 'アイアンマン', 'エルサ', 'マリオ'
        ],
        '人間ですか？':          [0, 0, 1, 1, 0, 1, 1, 1],
        '日本出身ですか？':        [1, 1, 1, 1, 1, 0, 0, 1],
        '戦いますか？':          [1, 1, 1, 0, 0, 1, 1, 1],
        '黄色いですか？':          [0, 1, 0, 0, 0, 0, 0, 0],
        'ヒゲがありますか？':      [1, 0, 0, 0, 1, 0, 0, 1],
        '魔法や超能力を使いますか？': [0, 0, 1, 0, 0, 0, 1, 0],
        '子供の姿ですか？':        [0, 0, 0, 1, 0, 0, 0, 0],
        '動物がモチーフですか？':    [1, 1, 0, 0, 1, 0, 0, 0],
        '赤い服（または帽子）を着ていますか？': [0, 0, 0, 0, 0, 1, 0, 1],
    }
    
    # DataFrameを作成し、「対象」列をインデックス（行名）に設定
    df = pd.DataFrame(data).set_index('対象')
    return df

def find_best_question(current_df):
    """
    現在の候補（DataFrame）を最も効率よく半分に絞り込める質問を見つけます。
    """
    if current_df.empty:
        return None

    # まだ聞いていない質問（＝値が全員同じではない列）を探す
    remaining_questions = []
    for q in current_df.columns:
        # もしその列の値が全て同じなら（例：全員0）、もう質問する意味がない
        if len(current_df[q].unique()) > 1:
            remaining_questions.append(q)

    if not remaining_questions:
        return None # 聞ける質問がもうない

    best_question = None
    # 理想は「Yes/Noが50%/50%」になること。
    # 候補者数（len(current_df)）の半分（target_split）に最も近い質問を探す。
    target_split = len(current_df) / 2
    
    # 理想値との「差」が最小になる質問を探す
    min_diff = float('inf') 

    for q in remaining_questions:
        # その質問で 'Yes (1)' と答える人の数を数える
        yes_count = current_df[q].sum()
        
        # 理想（半分）との差
        diff = abs(yes_count - target_split)
        
        if diff < min_diff:
            min_diff = diff
            best_question = q
            
    return best_question

def main():
    # 1. データベースの準備
    df = setup_database()
    candidates = df.copy() # 候補者リスト（最初は全員）
    
    asked_questions = [] # 一度聞いた質問は除外するリスト
    
    print("頭の中に、誰か（何か）を思い浮かべてください...")
    print("（対象リスト: {}）".format(", ".join(df.index)))
    print("私が質問しますので、'yes' か 'no' で答えてください。\n")
    time.sleep(2)

    # 2. 対話ループ
    # 候補が1人になるか、聞く質問がなくなるまでループ
    while len(candidates) > 1:
        
        # 3. 最適な質問の選択 (データ解析)
        # 候補リストから、聞いた質問を除外したDataFrameを一時的に作成
        temp_df = candidates.drop(columns=asked_questions, errors='ignore')
        question = find_best_question(temp_df)
        
        if question is None:
            # もう絞り込むための質問がない
            print("うーん、これ以上絞り込む質問がありません...")
            break
            
        asked_questions.append(question) # この質問は「聞いた」ことにする

        # 4. 質問の実行 (NLPが活躍する部分)
        print(f"--- 質問 {len(asked_questions)} ---")
        print(f"その対象は... 【{question}】 (yes / no)")
        
        # 5. 回答の解釈 (NLPが活躍する部分)
        ans_text = input("> ").strip().lower()
        
        if ans_text == 'yes' or ans_text == 'y':
            answer_value = 1
        elif ans_text == 'no' or ans_text == 'n':
            answer_value = 0
        else:
            print("'yes' か 'no' で答えてください。")
            asked_questions.pop() # 聞き直しのため、リストから戻す
            continue

        # 6. 候補の絞り込み (データ解析)
        candidates = candidates[candidates[question] == answer_value]
        
        print(f"(現在の候補者数: {len(candidates)}人)")
        # print(f"(候補: {list(candidates.index)})") # デバッグ用
        print("\n")
        time.sleep(1)

    # 7. 結果の発表
    print("--- 結果発表 ---")
    if len(candidates) == 1:
        result = candidates.index[0]
        print(f"あなたが思い浮かべたのは... \n\n【{result}】\n\nですね！")
    elif len(candidates) > 1:
        print("うーん、最後は絞りきれませんでした。")
        print(f"候補: {list(candidates.index)}")
    else:
        print("あれ？ データベースにいないか、途中で回答が間違っていたかもしれません。")

# プログラムの実行
if __name__ == "__main__":
    main()