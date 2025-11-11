import collections

# --- 1. 仮の著名人データ (データ解析班からもらう想定) ---
sample_data = [
    {"name": "ビートたけし", "attributes": [{"key": "職業", "value": "お笑い芸人"}, {"key": "職業", "value": "映画監督"}, {"key": "出身地", "value": "東京都"}, {"key": "性別", "value": "男性"}]},
    {"name": "タモリ", "attributes": [{"key": "職業", "value": "お笑い芸人"}, {"key": "職業", "value": "司会者"}, {"key": "出身地", "value": "福岡県"}, {"key": "性別", "value": "男性"}]},
    {"name": "新垣結衣", "attributes": [{"key": "職業", "value": "俳優"}, {"key": "職業", "value": "モデル"}, {"key": "出身地", "value": "沖縄県"}, {"key": "性別", "value": "女性"}]},
    {"name": "大谷翔平", "attributes": [{"key": "職業", "value": "野球選手"}, {"key": "出身地", "value": "岩手県"}, {"key": "性別", "value": "男性"}]}
]


# --- 2. 自然言語処理班が作るメイン機能 ---

def generate_question_text(attribute):
    """
    属性データ（辞書）を受け取り、自然な質問文を生成する関数
    {"key": "職業", "value": "お笑い芸人"} -> 「職業は お笑い芸人 ですか？」
    """
    key = attribute["key"]
    value = attribute["value"]

    # keyに応じて質問のテンプレートを変える（ここを工夫すると自然になる）
    if key == "出身地":
        return f"その人は {value} 出身ですか？"
    if key == "性別":
        return f"性別は {value} ですか？"
    
    # デフォルトの質問文
    return f"{key} は {value} ですか？"


def find_best_question(remaining_celebs, asked_attributes):
    """
    残っている候補者リストから、最も効率よく絞り込めそうな質問（属性）を見つける関数
    """
    
    # まだ聞いていない属性をすべてカウントする
    attribute_counts = collections.Counter()
    
    for celeb in remaining_celebs:
        for attr in celeb["attributes"]:
            # 属性をタプルに変換（辞書はCounterのキーにできないため）
            attr_tuple = (attr["key"], attr["value"])
            
            # まだ聞いていない質問ならカウント
            if attr_tuple not in asked_attributes:
                attribute_counts[attr_tuple] += 1

    if not attribute_counts:
        return None # 聞ける質問がもうない

    # 最も多く出現する属性（＝多くの候補者に共通する属性）を見つける
    # (注: 本当のアキネータは、候補をちょうど半分に分けられる質問を「良い質問」としますが、
    #  ここでは実装を簡単にするため「最も多く出現する質問」を選んでいます)
    best_attr_tuple = attribute_counts.most_common(1)[0][0]
    
    # タプルを辞書に戻して返す
    return {"key": best_attr_tuple[0], "value": best_attr_tuple[1]}


def filter_celebs(celebs, attribute, answer_is_yes):
    """
    回答（はい/いいえ）に基づいて、候補者リストを絞り込む関数
    """
    new_celebs_list = []
    for celeb in celebs:
        # 属性を持っているかチェック
        has_attribute = attribute in celeb["attributes"]
        
        if answer_is_yes and has_attribute:
            # 「はい」と答えて、実際に属性を持っていたらリストに残す
            new_celebs_list.append(celeb)
        elif not answer_is_yes and not has_attribute:
            # 「いいえ」と答えて、属性を持っていなかったらリストに残す
            new_celebs_list.append(celeb)
            
    return new_celebs_list


# --- 3. メインの実行部分 (シミュレーション) ---

def main():
    # ゲーム開始時は、全員が候補
    remaining_celebs = sample_data
    # 聞いた質問を記録するセット
    asked_attributes = set()

    print("--- 著名人当てゲームを開始します ---")
    print("「yes」「no」または「y」「n」で答えてください。")

    while len(remaining_celebs) > 1:
        # 1. 最適な質問を見つける
        best_attribute = find_best_question(remaining_celebs, asked_attributes)
        
        if best_attribute is None:
            print("（これ以上絞り込める質問がありません）")
            break

        # 2. 質問文を生成する
        question_text = generate_question_text(best_attribute)
        
        # 3. 質問して回答をもらう
        answer_raw = input(f"\n質問: {question_text} (残り候補: {len(remaining_celebs)}人) > ").strip().lower()

        # 属性をタプルに変換して「聞いた」リストに追加
        asked_attributes.add( (best_attribute["key"], best_attribute["value"]) )

        if answer_raw in ["yes", "y", "はい"]:
            answer_is_yes = True
        elif answer_raw in ["no", "n", "いいえ"]:
            answer_is_yes = False
        else:
            print("yes/noで答えてください。")
            continue

        # 4. 回答に基づいて候補者を絞り込む
        remaining_celebs = filter_celebs(remaining_celebs, best_attribute, answer_is_yes)

    # --- 5. 結果発表 ---
    print("\n--- 結果 ---")
    if len(remaining_celebs) == 1:
        print(f"あなたが思い浮かべたのは... 【{remaining_celebs[0]['name']}】 ですね！")
    elif len(remaining_celebs) == 0:
        print("あれ...？ 該当する人がデータにいませんでした。")
    else:
        print("すみません、特定できませんでした。以下の人たちの可能性があります。")
        for celeb in remaining_celebs:
            print(f"- {celeb['name']}")

# このファイルが直接実行された時だけ、main()を動かす
if __name__ == "__main__":
    main()