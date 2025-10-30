import requests
import time
import json
import os
import re
import random
import wikipediaapi
import random

# Wikipediaにアクセスする際のユーザーエージェント
USER_AGENT = "CelebrityAkinatorBot/1.0 (https://github.com/yourproject; contact@example.com)"
WIKI_API = "https://ja.wikipedia.org/w/api.php"
WIKIDATA_ENTITY_URL = "https://www.wikidata.org/wiki/Special:EntityData/{}.json"

# 保存先ファイル名
PEOPLE_LIST_FILE = "people_list.json"  # 取得した人物タイトルのリスト
DATASET_FILE = "people_dataset.json"   # 各人物の属性データ

# 取得対象カテゴリ（必要に応じて増やす）
CATEGORIES = [
    # 俳優・芸能
    "日本の俳優", "日本の女優", "お笑い芸人", "日本の声優", "日本のアイドル", "日本のモデル", "日本の歌手",
    "日本の作曲家", "日本の映画監督", "日本の舞台俳優", "日本のアナウンサー", "日本のYouTuber",

    # 文学・学問
    "日本の作家", "日本の漫画家", "日本の小説家", "日本の詩人", "日本の科学者", "日本の数学者", "日本の物理学者",
    "日本の化学者", "日本の医師", "日本の哲学者", "日本の歴史学者", "日本の教育者", "日本の研究者", "日本の発明家",

    # 政治・社会
    "日本の政治家", "日本の外交官", "日本の官僚", "日本の経営者", "日本の起業家", "日本の弁護士", "日本の裁判官",

    # スポーツ
    "日本のスポーツ選手", "日本のサッカー選手", "日本の野球選手", "日本の柔道家", "日本のレスリング選手", "日本のオリンピック選手",
    "日本の水泳選手", "日本の陸上競技選手", "日本のテニス選手", "日本のバレーボール選手", "日本のバスケットボール選手",

    # 芸術・文化
    "日本の画家", "日本の彫刻家", "日本の写真家", "日本の建築家", "日本のデザイナー", "日本の陶芸家", "日本の演出家",
    "日本の音楽家", "日本の指揮者", "日本の舞踏家",
]

# Wikipedia APIに送る際のヘッダー
HEADERS = {"User-Agent": USER_AGENT}

# -----------------------
# 除外ルール: 人物ページかどうか判定
# -----------------------
def is_person_page(title):
    """
    タイトルに特定のキーワードが含まれていたら除外
    """
    exclude_keywords = ["一覧", "号", "歴史", "編"]
    return not any(k in title for k in exclude_keywords)

# -----------------------
# ユーティリティ: Wikipediaカテゴリからタイトル取得（cmcontinue対応）
# -----------------------
def get_category_members(category, cmlimit=50, depth=1, collected=None, sleep=0.8):
    if collected is None:
        collected = set()

    cmtitle = f"Category:{category}"
    params = {
        "action": "query",
        "list": "categorymembers",
        "cmtitle": cmtitle,
        "cmlimit": str(cmlimit),
        "format": "json"
    }

    cont = None
    while True:
        if cont:
            params.update(cont)
        try:
            res = requests.get(WIKI_API, params=params, headers=HEADERS, timeout=15)
        except Exception as e:
            print("HTTPエラー:", e)
            return collected

        if res.status_code == 403:
            print("403 Forbidden: Wikipediaがアクセスを拒否しました。")
            return collected

        try:
            data = res.json()
        except Exception as e:
            print("JSONデコード失敗:", e)
            return collected

        for m in data.get("query", {}).get("categorymembers", []):
            title = m.get("title")
            if not title:
                continue
            if title.startswith("Category:"):
                if depth > 0:
                    subcat = title[len("Category:"):]
                    time.sleep(sleep)
                    get_category_members(subcat, cmlimit=cmlimit, depth=depth-1, collected=collected, sleep=sleep)
                continue
            
            # 除外ルール
            if any(x in title for x in ["協会", "連合", "論争", "番組", "映画", "会社", "局", "団体", "目録"]) or not is_person_page(title):
                continue

            collected.add(title)

        if "continue" in data:
            cont = data["continue"]
            time.sleep(sleep)
        else:
            break
    return collected

# -----------------------
# カテゴリ選択
# -----------------------
def choose_categories():
    print("=== カテゴリを選択してください ===")
    for i, cat in enumerate(CATEGORIES, 1):
        print(f"{i}. {cat}")
    print("複数選ぶ場合はカンマ区切りで番号を入力してください (例: 1,3,5) / 全ての場合は Enter")

    choice = input("> ").strip()
    if not choice:
        print("全カテゴリを対象にします。")
        return CATEGORIES
        
    selected = []
    for part in choice.split(","):
        try:
            idx = int(part)-1
            if 0 <= idx < len(CATEGORIES):
                selected.append(CATEGORIES[idx])
        except:
            pass
            
    if not selected:
        print("カテゴリが選択されなかったため、全カテゴリを対象にします。")
        return CATEGORIES
    
    print(f"選択されたカテゴリ: {', '.join(selected)}")
    return selected

# -----------------------
# Step1: 全カテゴリから人物を収集して保存
# -----------------------
def collect_people(categories=CATEGORIES, cmlimit=50, depth=0, sleep=0.8, save_path=PEOPLE_LIST_FILE):
    if os.path.exists(save_path):
        print(f"{save_path} が既に存在するため、collect はスキップします。")
        with open(save_path, "r", encoding="utf-8") as f:
            return json.load(f)

    print("=== カテゴリから人物リストを収集します ===")
    all_people = set()
    for cat in categories:
        print(f"取得中: {cat}")
        people = get_category_members(cat, cmlimit=cmlimit, depth=depth, sleep=sleep)
        print(f"  → {len(people)} 人取得")
        all_people.update(people)
        time.sleep(sleep)

    people_list = sorted(list(all_people))
    with open(save_path, "w", encoding="utf-8") as f:
        json.dump(people_list, f, ensure_ascii=False, indent=2)
    print(f"保存しました: {save_path} （合計 {len(people_list)} 人）")
    return people_list

# -----------------------
# Wikidata取得補助: Wikipediaページからwikibase_itemを得る
# -----------------------
def get_wikibase_item_from_wikipedia(title):
    params = {
        "action": "query",
        "titles": title,
        "prop": "pageprops",
        "format": "json"
    }
    try:
        res = requests.get(WIKI_API, params=params, headers=HEADERS, timeout=15)
        data = res.json()
        pages = data.get("query", {}).get("pages", {})
        if not pages:
            return None
        page = next(iter(pages.values()))
        pp = page.get("pageprops", {})
        return pp.get("wikibase_item")
    except Exception:
        return None

# -----------------------
# Wikidataから構造化属性を取得
# -----------------------
def fetch_wikidata_entity(wikibase_id):
    try:
        url = WIKIDATA_ENTITY_URL.format(wikibase_id)
        res = requests.get(url, headers=HEADERS, timeout=15)
        data = res.json()
        entity = data.get("entities", {}).get(wikibase_id, {})
        claims = entity.get("claims", {})
        result = {}
        # occupation (P106) -> list of ids
        if "P106" in claims:
            occ = []
            for c in claims["P106"]:
                mainsnak = c.get("mainsnak", {})
                dv = mainsnak.get("datavalue", {})
                if dv:
                    v = dv.get("value")
                    if isinstance(v, dict) and "id" in v:
                        occ.append(v["id"])
            result["occupation_qids"] = occ
        # gender (P21)
        if "P21" in claims:
            try:
                v = claims["P21"][0]["mainsnak"]["datavalue"]["value"]
                if isinstance(v, dict) and "id" in v:
                    result["gender_qid"] = v["id"]
            except Exception: pass
        # birth (P569)
        if "P569" in claims:
            try:
                t = claims["P569"][0]["mainsnak"]["datavalue"]["value"]["time"]
                result["birth_time"] = t
            except Exception: pass
        # death (P570)
        if "P570" in claims:
            try:
                t = claims["P570"][0]["mainsnak"]["datavalue"]["value"]["time"]
                result["death_time"] = t
            except Exception: pass
        return result
    except Exception:
        return None

# -----------------------
# summaryからキーワードベースで特徴を抽出する
# -----------------------
FEATURE_KEYWORDS = {
    "taiga": ["大河ドラマ", "大河"],
    "tokusatsu": ["仮面ライダー", "スーパー戦隊", "ウルトラマン", "特撮"],
    "romance_drama": ["恋愛", "ラブストーリー", "恋人"],
    "movie": ["映画", "劇場版"],
    "action": ["アクション", "殺陣", "アクション俳優"],
    "seiyuu": ["声優", "アニメで声"],
    "singer": ["歌手", "シンガー", "ボーカル"],
    "stage": ["舞台", "ミュージカル", "劇団"],
    "model": ["モデル", "ファッションモデル"],
    "comedian": ["お笑い", "芸人", "コント"],
    "anime": ["アニメ"],
    "hollywood": ["ハリウッド", "海外映画"],
    "idol": ["アイドル", "グループ"],
    "award": ["受賞", "賞を受賞", "主演男優賞", "最優秀"],
    "nhk": ["NHK", "連続テレビ小説", "朝ドラ"],
    "youtuber": ["YouTube", "チャンネル"],
    "director": ["監督"],
    "athlete": ["選手", "オリンピック", "サッカー", "野球", "柔道", "レスリング"],
    "politician": ["政治家", "衆議院", "参議院", "首相"]
}

def extract_features_from_summary(summary):
    s = summary or ""
    features = {}
    for k, keywords in FEATURE_KEYWORDS.items():
        features[k] = int(any(kw in s for kw in keywords))
    
    m = re.search(r'(\d{4})年', s)
    birth_year = None
    if m:
        try:
            birth_year = int(m.group(1))
        except:
            birth_year = None
    features["birth_year"] = birth_year
    features["alive_text"] = 0 if ("没" in s or "死去" in s or "亡くな" in s) else 1
    return features

# -----------------------
# Step2: people list -> build dataset (逐次処理版)
# -----------------------
def build_dataset(people_list_path=PEOPLE_LIST_FILE, dataset_path=DATASET_FILE, limit=None, sleep=0.8):
    if not os.path.exists(people_list_path):
        print("人物リストが存在しません。まず collect_people を実行してください。")
        return None

    with open(people_list_path, "r", encoding="utf-8") as f:
        people = json.load(f)

    existing = {}
    if os.path.exists(dataset_path):
        with open(dataset_path, "r", encoding="utf-8") as f:
            try:
                existing = {p["name"]: p for p in json.load(f)}
                print(f"{len(existing)} 件の既存データを読み込みました。未処理の人物のみ処理します。")
            except:
                existing = {}

    wiki = wikipediaapi.Wikipedia(user_agent=USER_AGENT, language="ja")
    new_records = []
    processed = 0

    for name in people:
        if limit and processed >= limit:
            break
        if name in existing:
            # print(f"処理済み: {name} ... スキップ") # スキップログが多すぎる場合はコメントアウト
            continue 

        print(f"処理中: {name}  ...", end=" ")
        rec = {"name": name, "summary": None, "features": None, "wikidata": None}
        try:
            page = wiki.page(name)
            if not page.exists():
                print("ページなし")
                processed += 1
                continue
            
            summary = page.summary
            rec["summary"] = summary
            rec["features"] = extract_features_from_summary(summary)
            
            wikibase_id = get_wikibase_item_from_wikipedia(name)
            if wikibase_id:
                wd = fetch_wikidata_entity(wikibase_id)
                rec["wikidata"] = wd
                if wd:
                    # gender (Q6581097 male, Q6581072 female)
                    g = wd.get("gender_qid")
                    if g == "Q6581097":
                        rec["features"]["gender"] = "male"
                    elif g == "Q6581072":
                        rec["features"]["gender"] = "female"
                    
                    # occupation qids
                    occ_qs = wd.get("occupation_qids", [])
                    if "Q33999" in occ_qs:  # actor
                        rec["features"]["actor_wikidata"] = 1
                    if "Q177220" in occ_qs or "Q639669" in occ_qs:  # singer
                        rec["features"]["singer_wikidata"] = 1
                    if "Q82955" in occ_qs:  # politician
                        rec["features"]["politician_wikidata"] = 1
                    
                    # birth/death
                    if wd.get("birth_time"):
                        rec["features"]["birth_time"] = wd.get("birth_time")
                    if wd.get("death_time"):
                        rec["features"]["death_time"] = wd.get("death_time")
                        # Wikidataに死亡日があれば、alive_textを上書き
                        rec["features"]["alive_text"] = 0 
            print("OK")
        except Exception as e:
            print("失敗:", e)
        
        new_records.append(rec)
        processed += 1
        time.sleep(sleep) # APIリクエストの合間にスリープ

    # 既存 + 新規データをマージして保存
    merged = list(existing.values()) + new_records
    with open(dataset_path, "w", encoding="utf-8") as f:
        json.dump(merged, f, ensure_ascii=False, indent=2)

    print(f"データセットを保存しました: {dataset_path}（合計 {len(merged)} 件）")
    return merged

# -----------------------
# Step3: アキネーター本体（datasetを読み込んで対話で絞り込み）
# -----------------------
def load_dataset(dataset_path=DATASET_FILE):
    if not os.path.exists(dataset_path):
        print("データセットが見つかりません。まず build_dataset を実行してください。")
        return None
    with open(dataset_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return data

# -----------------------
# 質問マップの自動生成（改良版）
# -----------------------
def generate_question_map(dataset):
    """
    データセットの特徴量(features)キーに基づいて、
    質問マップ（階層化された辞書）を自動生成します。
    """
    qm = {"occupation": [], "activity": [], "feature": [], "common": []}
    added_keys = set() # 質問の重複を防ぐ

    # --- 1. 共通質問 (Wikidata由来の信頼できる情報) ---
    common_questions_def = [
        ("gender_male", "男性ですか？", "common"),
        ("gender_female", "女性ですか？", "common"),
        ("alive_text", "現在もご存命ですか？", "common"),
        ("actor_wikidata", "本業は俳優ですか？", "occupation"),
        ("singer_wikidata", "本業は歌手ですか？", "occupation"),
        ("politician_wikidata", "本業は政治家ですか？", "occupation"),
    ]

    for key, text, category in common_questions_def:
        key_exists = any(key in rec.get("features", {}) for rec in dataset)
        if key_exists and key not in added_keys:
            qm[category].append({
                "key": key,
                "text": text,
                "check": lambda rec, k=key: rec.get("features", {}).get(k) == 1
            })
            added_keys.add(key)

    # --- 2. FEATURE_KEYWORDS に基づく質問 (NLP由来) ---
    feature_questions_def = {
        # 職業系
        "comedian": ("お笑い芸人ですか？", "occupation"),
        "seiyuu": ("声優として活動していますか？", "occupation"),
        "athlete": ("スポーツ選手ですか？", "occupation"),
        "model": ("モデルとして活動していますか？", "occupation"),
        "idol": ("アイドル活動をしていましたか（していますか）？", "occupation"),
        "youtuber": ("YouTuberとして活動していますか？", "occupation"),
        "director": ("監督（映画やアニメなど）ですか？", "occupation"),
        
        # 活動・特徴系
        "taiga": ("大河ドラマに出演しましたか？", "activity"),
        "tokusatsu": ("特撮作品（仮面ライダーなど）に出演しましたか？", "activity"),
        "romance_drama": ("恋愛ドラマに出演しましたか？", "activity"),
        "movie": ("映画に出演していますか？", "activity"),
        "action": ("アクション作品に出演していますか？", "activity"),
        "stage": ("舞台（演劇・ミュージカル）に出演していますか？", "activity"),
        "anime": ("アニメ作品に関わっていますか？", "activity"),
        "hollywood": ("海外（ハリウッド等）の作品に出演していますか？", "activity"),
        "nhk": ("NHK（朝ドラなど）に出演したことがありますか？", "activity"),
        "award": ("（演技賞や作品賞など）を受賞したことがありますか？", "feature"),
    }

    for key in FEATURE_KEYWORDS.keys():
        if key in feature_questions_def and key not in added_keys:
            text, category = feature_questions_def[key]
            
            qm[category].append({
                "key": key,
                "text": text,
                "check": lambda rec, k=key: rec.get("features", {}).get(k) == 1
            })
            added_keys.add(key)
        
    print(f"質問を生成しました (職業: {len(qm['occupation'])}, 活動: {len(qm['activity'])}, 特徴: {len(qm['feature'])}, 共通: {len(qm['common'])})")
    return qm

#-----------------------
# アキネーター対話部分（階層化対応・改良版）
#-----------------------
def akinator_play(dataset, max_questions=30, check_every=10):
    candidates = dataset.copy()
    
    # データセットを渡して質問マップを生成
    qm_dict = generate_question_map(dataset) 
    
    print("=== アキネーター開始 ===")
    print(f"候補人数: {len(candidates)} 件")

    asked_keys = set() # 質問の重複を防ぐ
    asked_count = 0

    # 質問ループを階層化 (重要な順: 職業 -> 共通 -> 活動 -> 特徴)
    for q_category in ["occupation", "common", "activity", "feature"]:
        
        if len(candidates) <= 1 or asked_count >= max_questions:
            break 

        question_list = qm_dict[q_category]
        random.shuffle(question_list) # カテゴリ内ではシャッフル

        for question in question_list:
            if asked_count >= max_questions or len(candidates) <= 1:
                break
            
            key, q_text, test = question.get("key"), question.get("text"), question.get("check")

            if key in asked_keys:
                continue
            
            # 「賢いスキップ」: 候補者全員がYes/Noになる質問は無駄
            yes_count = 0
            no_count = 0
            for c in candidates:
                if test(c):
                    yes_count += 1
                else:
                    no_count += 1
            
            if yes_count == 0 or no_count == 0:
                asked_keys.add(key) # 聞いたことにしてスキップ
                continue

            # --- 質問実行 ---
            ans = input(q_text + " （はい/いいえ/わからない） > ").strip()
            asked_keys.add(key) 

            if ans not in ["はい", "いいえ"]:
                print("スキップ")
                continue

            # 絞り込み
            if ans == "はい":
                candidates = [c for c in candidates if test(c)]
            else:
                candidates = [c for c in candidates if not test(c)]
            
            asked_count += 1
            print(f"(現在の候補数: {len(candidates)}人)")

            # --- 途中確認ロジック ---
            if (asked_count % check_every == 0 or len(candidates) <= 3) and len(candidates) > 0:
                print(f"\nここまでの質問で絞り込んだ候補（上位3件）:")
                for j, c in enumerate(candidates[:3], 1):
                    print(f"{j}. {c['name']}")
                choice = input("上の中にあなたの思い浮かべた人物はいますか？ (番号 または なし) > ").strip()
                if choice.isdigit():
                    idx = int(choice)-1
                    if 0 <= idx < len(candidates[:3]):
                        print(f"それでは、あなたが思い浮かべた人物は『{candidates[idx]['name']}』ですね！")
                        return candidates[idx]
                elif choice.lower() in ["なし", "n", "no"]:
                    print("わかりました。質問を続けます。")

    # --- 最終結果の発表 ---
    if not candidates:
        print("候補が見つかりませんでした。")
        return None

    print("\n最終候補（上位3件）:")
    for i, c in enumerate(candidates[:3], 1):
        print(f"{i}. {c['name']}")
    choice = input("上の中にあなたの思い浮かべた人物はいますか？ (番号 または なし) > ").strip()
    if choice.isdigit():
        idx = int(choice)-1
        if 0 <= idx < len(candidates[:3]):
            print(f"それでは、あなたが思い浮かべた人物は『{candidates[idx]['name']}』ですね！")
            return candidates[idx]

    print(f"私の推測：『{candidates[0]['name']}』かもしれません。")
    return candidates[0]

# -----------------------
# エントリポイント用関数
# -----------------------
def run_step(step="collect", **kwargs):
    step = step.lower()

    if step == "collect":
        return collect_people(categories=kwargs.get("categories", CATEGORIES),
                              cmlimit=kwargs.get("cmlimit", 50),
                              depth=kwargs.get("depth", 1),
                              sleep=kwargs.get("sleep", 0.8))

    elif step == "build":
        return build_dataset(limit=kwargs.get("limit", None),
                             sleep=kwargs.get("sleep", 0.8))

    elif step == "play":
        ds = load_dataset()
        if not ds:
            return None
        # dataset を akinator_play に渡す
        return akinator_play(ds, max_questions=kwargs.get("max_questions", 30))

    else:
        raise ValueError("step must be one of: collect, build, play")

# -----------------------
# 実行部分
# -----------------------
if __name__ == "__main__":
    # --- 実行パラメータ ---
    # APIへの負荷を考慮し、sleepは 0.5 以上を推奨
    # cmlimit: 1回のリクエストで取得する件数 (50-500)
    # depth: サブカテゴリを掘る深さ (0 or 1推奨)
    # limit: build_dataset で処理する人数の上限 (Noneで全員)
    # max_questions: ゲームの最大質問数
    
    SLEEP = 0.5     # APIアクセス間隔 (秒)
    CMLIMIT = 50
    DEPTH = 1
    BUILD_LIMIT = 200 # お試しビルドの人数上限 (Noneで無制限)
    MAX_QUESTIONS = 25

    # --- 実行フロー ---
    try:
        selected_categories = choose_categories()
        
        # データ収集
        run_step("collect", 
                 categories=selected_categories, 
                 cmlimit=CMLIMIT, 
                 depth=DEPTH, 
                 sleep=SLEEP)
        
        # データセットを構築
        run_step("build", 
                 limit=BUILD_LIMIT, 
                 sleep=SLEEP)
        
        # アキネーターをプレイ
        run_step("play", 
                 max_questions=MAX_QUESTIONS)
                 
    except KeyboardInterrupt:
        print("\n処理が中断されました。")
    except Exception as e:
        print(f"\nエラーが発生しました: {e}")