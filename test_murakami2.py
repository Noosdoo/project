import requests
import time
import json
import os
import re
import random
import wikipediaapi
from datetime import datetime # ★ 追加: 日付処理のため

# Wikipediaにアクセスする際のユーザーエージェント
USER_AGENT = "CelebrityAkinatorBot/1.0 (https://github.com/yourproject; contact@example.com)"
WIKI_API = "https://ja.wikipedia.org/w/api.php"
WIKIDATA_ENTITY_URL = "https://www.wikidata.org/wiki/Special:EntityData/{}.json"

# 保存先ファイル名
PEOPLE_LIST_FILE = "people_list.json"  # 取得した人物タイトルのリスト
DATASET_FILE = "people_dataset.json"   # 各人物の属性データ

# 取得対象カテゴリ（変更なし）　お笑い芸人ではだめ
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
# 除外ルール: 人物ページかどうか判定 (変更なし)
# -----------------------
def is_person_page(title):
    exclude_keywords = ["一覧", "号", "歴史", "編"]
    return not any(k in title for k in exclude_keywords)

# -----------------------
# ユーティリティ: Wikipediaカテゴリからタイトル取得（変更なし）
# -----------------------
def get_category_members(category, cmlimit=50, depth=1, collected=None, sleep=0.8):
    if collected is None:
        collected = set()
    cmtitle = f"Category:{category}"
    params = {
        "action": "query", "list": "categorymembers",
        "cmtitle": cmtitle, "cmlimit": str(cmlimit), "format": "json"
    }
    cont = None
    while True:
        if cont: params.update(cont)
        try:
            res = requests.get(WIKI_API, params=params, headers=HEADERS, timeout=15)
        except Exception as e:
            print("HTTPエラー:", e); return collected
        if res.status_code == 403:
            print("403 Forbidden: Wikipediaがアクセスを拒否しました。"); return collected
        try:
            data = res.json()
        except Exception as e:
            print("JSONデコード失敗:", e); return collected
        for m in data.get("query", {}).get("categorymembers", []):
            title = m.get("title")
            if not title: continue
            if title.startswith("Category:"):
                if depth > 0:
                    subcat = title[len("Category:"):]
                    time.sleep(sleep)
                    get_category_members(subcat, cmlimit=cmlimit, depth=depth-1, collected=collected, sleep=sleep)
                continue
            if any(x in title for x in ["協会", "連合", "論争", "番組", "映画", "会社", "局", "団体", "目録"]) or not is_person_page(title):
                continue
            collected.add(title)
        if "continue" in data:
            cont = data["continue"]; time.sleep(sleep)
        else:
            break
    return collected

# -----------------------
# カテゴリ選択 (変更なし)
# -----------------------
def choose_categories():
    print("=== カテゴリを選択してください ===")
    for i, cat in enumerate(CATEGORIES, 1):
        print(f"{i}. {cat}")
    print("複数選ぶ場合はカンマ区切りで番号を入力してください (例: 1,3,5) / 全ての場合は Enter")
    choice = input("> ").strip()
    if not choice:
        print("全カテゴリを対象にします。"); return CATEGORIES
    selected = []
    for part in choice.split(","):
        try:
            idx = int(part)-1
            if 0 <= idx < len(CATEGORIES): selected.append(CATEGORIES[idx])
        except: pass
    if not selected:
        print("カテゴリが選択されなかったため、全カテゴリを対象にします。"); return CATEGORIES
    print(f"選択されたカテゴリ: {', '.join(selected)}"); return selected

# -----------------------
# Step1: 全カテゴリから人物を収集して保存 (変更なし / 10/30 修正版)
# -----------------------
def collect_people(categories=CATEGORIES, cmlimit=50, depth=0, sleep=0.8, save_path=PEOPLE_LIST_FILE):
    target_categories = sorted(list(set(categories)))
    if os.path.exists(save_path):
        try:
            with open(save_path, "r", encoding="utf-8") as f: data = json.load(f)
            saved_categories = data.get("meta", {}).get("categories")
            people_list = data.get("people")
            if saved_categories == target_categories and people_list is not None:
                print(f"{save_path} が存在し、カテゴリが一致するため、collect はスキップします。")
                return people_list
            else:
                print("カテゴリが変更されたため、人物リストを再収集します。")
                if os.path.exists(DATASET_FILE):
                    print(f"古いデータセット {DATASET_FILE} をリセットします。")
                    os.remove(DATASET_FILE)
        except Exception as e:
            print(f"既存ファイルの形式が古いか壊れています: {e}。再収集します。")
            if os.path.exists(DATASET_FILE): os.remove(DATASET_FILE)

    print("=== カテゴリから人物リストを収集します ===")
    all_people = set()
    for cat in target_categories:
        print(f"取得中: {cat}")
        people = get_category_members(cat, cmlimit=cmlimit, depth=depth, sleep=sleep)
        print(f"  → {len(people)} 人取得")
        all_people.update(people); time.sleep(sleep)
    people_list = sorted(list(all_people))
    save_data = {
        "meta": {"categories": target_categories, "last_updated": time.strftime("%Y-%m-%dT%H:%M:%S")},
        "people": people_list
    }
    with open(save_path, "w", encoding="utf-8") as f:
        json.dump(save_data, f, ensure_ascii=False, indent=2)
    print(f"保存しました: {save_path} （合計 {len(people_list)} 人）"); return people_list

# -----------------------
# Wikidata取得補助 (変更なし)
# -----------------------
def get_wikibase_item_from_wikipedia(title):
    params = {"action": "query", "titles": title, "prop": "pageprops", "format": "json"}
    try:
        res = requests.get(WIKI_API, params=params, headers=HEADERS, timeout=15)
        data = res.json(); pages = data.get("query", {}).get("pages", {})
        if not pages: return None
        page = next(iter(pages.values())); pp = page.get("pageprops", {})
        return pp.get("wikibase_item")
    except Exception: return None

# -----------------------
# ★ Wikidataから構造化属性を取得 (拡張版) ★
# -----------------------
def fetch_wikidata_entity(wikibase_id):
    try:
        url = WIKIDATA_ENTITY_URL.format(wikibase_id)
        res = requests.get(url, headers=HEADERS, timeout=15)
        data = res.json()
        entity = data.get("entities", {}).get(wikibase_id, {})
        claims = entity.get("claims", {})
        result = {}
        
        # occupation (P106)
        if "P106" in claims:
            occ = []
            for c in claims["P106"]:
                try:
                    v = c["mainsnak"]["datavalue"]["value"]
                    if isinstance(v, dict) and "id" in v: occ.append(v["id"])
                except Exception: pass
            if occ: result["occupation_qids"] = occ
            
        # gender (P21)
        if "P21" in claims:
            try:
                v = claims["P21"][0]["mainsnak"]["datavalue"]["value"]
                if isinstance(v, dict) and "id" in v: result["gender_qid"] = v["id"]
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
            
        # ★ 追加: P19 (出身地)
        if "P19" in claims:
            try:
                v = claims["P19"][0]["mainsnak"]["datavalue"]["value"]
                if isinstance(v, dict) and "id" in v:
                    result["birth_place_qid"] = v["id"] # 例: "Q1490" (東京)
            except Exception: pass
            
        # ★ 追加: P69 (学歴)
        if "P69" in claims:
            edu_qids = []
            for c in claims["P69"]:
                try:
                    v = c["mainsnak"]["datavalue"]["value"]
                    if isinstance(v, dict) and "id" in v: edu_qids.append(v["id"])
                except Exception: pass
            if edu_qids: result["education_qids"] = edu_qids # 例: ["Q7981"] (東大)

        # ★ 追加: P166 (受賞歴)
        if "P166" in claims:
            award_qids = []
            for c in claims["P166"]:
                 try:
                    v = c["mainsnak"]["datavalue"]["value"]
                    if isinstance(v, dict) and "id" in v: award_qids.append(v["id"])
                 except Exception: pass
            if award_qids: result["award_qids"] = award_qids # 例: ["Q1138032"] (紫綬褒章)
        
        return result
    except Exception:
        return None

# -----------------------
# ★ summaryからキーワードベースで特徴を抽出 (拡張版) ★
# -----------------------
FEATURE_KEYWORDS = {
    # (既存)
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
    "politician": ["政治家", "衆議院", "参議院", "首相"],
    
    # ★ 追加
    "mc": ["司会", "MC", "司会者"],
    "radio": ["ラジオ", "パーソナリティ"],
    "cm": ["CM", "コマーシャル"],
    "married": ["結婚", "妻", "夫"],
    "author": ["執筆", "出版", "著書", "エッセイ"],
}

def extract_features_from_summary(summary):
    s = summary or ""
    features = {}
    for k, keywords in FEATURE_KEYWORDS.items():
        features[k] = int(any(kw in s for kw in keywords))
    
    m = re.search(r'(\d{4})年', s) # NLPでの生年判定 (簡易)
    if m:
        try: features["birth_year"] = int(m.group(1))
        except: pass
    features["alive_text"] = 0 if ("没" in s or "死去" in s or "亡くな" in s) else 1
    return features

# -----------------------
# Step2: people list -> build dataset (★ アイデア反映 修正版)
# -----------------------
def load_people_list(people_list_path=PEOPLE_LIST_FILE):
    if not os.path.exists(people_list_path): return None
    try:
        with open(people_list_path, "r", encoding="utf-8") as f: data = json.load(f)
        if isinstance(data, dict): return data.get("people")
        elif isinstance(data, list): return data
        return None
    except Exception: return None

def build_dataset(people_list_path=PEOPLE_LIST_FILE, dataset_path=DATASET_FILE, limit=None, sleep=0.8):
    people = load_people_list(people_list_path) 
    if people is None:
        print("人物リストが存在しません。まず collect_people を実行してください。")
        return None

    existing = {}
    if os.path.exists(dataset_path):
        with open(dataset_path, "r", encoding="utf-8") as f:
            try:
                existing = {p["name"]: p for p in json.load(f)}
                print(f"{len(existing)} 件の既存データを読み込みました。未処理の人物のみ処理します。")
            except: existing = {}

    wiki = wikipediaapi.Wikipedia(user_agent=USER_AGENT, language="ja")
    new_records = []
    processed = 0
    
    # ★ 年齢計算用の現在年
    try:
        current_year = datetime.now().year
    except:
        current_year = 2025 # フォールバック

    for name in people:
        if limit and processed >= limit: break
        if name in existing: continue 

        print(f"処理中: {name}  ...", end=" ")
        rec = {"name": name, "summary": None, "features": None, "wikidata": None}
        try:
            page = wiki.page(name)
            if not page.exists():
                print("ページなし"); processed += 1; continue
            
            summary = page.summary
            rec["summary"] = summary
            features = extract_features_from_summary(summary)
            
            # ★ 追加: 名前分析
            if re.search(r'[ァ-ヶ]', name):
                features["has_katakana"] = 1
            if re.fullmatch(r'[ぁ-ん]+', name):
                features["is_hiragana_only"] = 1

            rec["features"] = features
            
            wikibase_id = get_wikibase_item_from_wikipedia(name)
            if wikibase_id:
                wd = fetch_wikidata_entity(wikibase_id)
                rec["wikidata"] = wd
                if wd:
                    # (既存) gender
                    g = wd.get("gender_qid")
                    if g == "Q6581097": features["gender"] = "male"
                    elif g == "Q6581072": features["gender"] = "female"
                    
                    # (既存) occupation
                    occ_qs = wd.get("occupation_qids", [])
                    if "Q33999" in occ_qs: features["actor_wikidata"] = 1
                    if "Q177220" in occ_qs or "Q639669" in occ_qs: features["singer_wikidata"] = 1
                    if "Q82955" in occ_qs: features["politician_wikidata"] = 1
                    
                    # ★ 追加 (Wikidata由来)
                    place_qid = wd.get("birth_place_qid")
                    if place_qid == "Q1490": features["from_tokyo"] = 1
                    elif place_qid in ["Q172582", "Q16997", "Q486245"]: features["from_kansai"] = 1
                        
                    edu_qids = wd.get("education_qids", [])
                    if "Q7981" in edu_qids: features["grad_todai"] = 1
                    elif "Q174019" in edu_qids: features["grad_waseda"] = 1
                    elif "Q302302" in edu_qids: features["grad_keio"] = 1
                        
                    award_qids = wd.get("award_qids", [])
                    if "Q1138032" in award_qids: features["award_shiju"] = 1 # 紫綬褒章

                    # ★ 追加 (日付ロジック)
                    birth_time = wd.get("birth_time")
                    death_time = wd.get("death_time")
                    
                    if birth_time and birth_time.startswith("+"):
                        try:
                            birth_year = int(birth_time[1:5])
                            features["birth_year_wd"] = birth_year
                            if 1970 <= birth_year <= 1979: features["born_1970s"] = 1
                            elif 1980 <= birth_year <= 1989: features["born_1980s"] = 1
                            elif 1990 <= birth_year <= 1999: features["born_1990s"] = 1
                            elif 2000 <= birth_year <= 2009: features["born_2000s"] = 1
                            
                            if not death_time: # ご存命の場合
                                age = current_year - birth_year
                                if 20 <= age <= 29: features["age_20s"] = 1
                                elif 30 <= age <= 39: features["age_30s"] = 1
                                elif 40 <= age <= 49: features["age_40s"] = 1
                                elif 50 <= age <= 59: features["age_50s"] = 1
                        except Exception: pass
                        
                    if death_time:
                        features["alive_text"] = 0 # 確実な死亡フラグ
                        try:
                            death_year = int(death_time[1:5])
                            if 1901 <= death_year <= 2000:
                                features["died_20c"] = 1 # 20世紀に死亡
                        except Exception: pass
            
            print("OK")
        except Exception as e:
            print("失敗:", e)
        
        new_records.append(rec)
        processed += 1
        time.sleep(sleep) 

    merged = list(existing.values()) + new_records
    with open(dataset_path, "w", encoding="utf-8") as f:
        json.dump(merged, f, ensure_ascii=False, indent=2)

    print(f"データセットを保存しました: {dataset_path}（合計 {len(merged)} 件）")
    return merged

# -----------------------
# Step3: アキネーター本体
# -----------------------
def load_dataset(dataset_path=DATASET_FILE):
    if not os.path.exists(dataset_path):
        print("データセットが見つかりません。まず build_dataset を実行してください。")
        return None
    with open(dataset_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return data

# -----------------------
# ★ 質問マップの自動生成（アイデア反映・カテゴリ連動・改良版）
# -----------------------
def generate_question_map(dataset, selected_categories=None):
    qm = {"occupation": [], "activity": [], "feature": [], "common": []}
    added_keys = set() 

    # --- 1. 共通質問 (Wikidata由来 + 日付 + 名前) ---
    common_questions_def = [
        # (既存)
        ("gender_male", "男性ですか？", "common"),
        ("gender_female", "女性ですか？", "common"),
        ("alive_text", "現在もご存命ですか？", "common"),
        ("actor_wikidata", "本業は俳優ですか？", "occupation"),
        ("singer_wikidata", "本業は歌手ですか？", "occupation"),
        ("politician_wikidata", "本業は政治家ですか？", "occupation"),
        
        # ★ 追加 (日付)
        ("age_20s", "現在、20代ですか？", "common"),
        ("age_30s", "現在、30代ですか？", "common"),
        ("age_40s", "現在、40代ですか？", "common"),
        ("age_50s", "現在、50代ですか？", "common"),
        ("born_1980s", "1980年代生まれですか？", "common"),
        ("born_1990s", "1990年代生まれですか？", "common"),
        ("born_2000s", "2000年代生まれですか？", "common"),
        ("died_20c", "20世紀（1900年代）に亡くなりましたか？", "common"),
        
        # ★ 追加 (名前)
        ("has_katakana", "名前にカタカナが含まれていますか？", "common"),
        ("is_hiragana_only", "名前はひらがなだけですか？", "common"),
        
        # ★ 追加 (Wikidata由来)
        ("from_tokyo", "出身は東京ですか？", "feature"),
        ("from_kansai", "出身は関西（大阪・京都・兵庫）ですか？", "feature"),
        ("grad_todai", "東京大学を卒業していますか？", "feature"),
        ("grad_waseda", "早稲田大学を卒業していますか？", "feature"),
        ("grad_keio", "慶應義塾大学を卒業していますか？", "feature"),
        ("award_shiju", "紫綬褒章を受章していますか？", "feature"),
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
        # (既存)
        "comedian": ("お笑い芸人ですか？", "occupation"),
        "seiyuu": ("声優として活動していますか？", "occupation"),
        "athlete": ("スポーツ選手ですか？", "occupation"),
        "model": ("モデルとして活動していますか？", "occupation"),
        "idol": ("アイドル活動をしていましたか（していますか）？", "occupation"),
        "youtuber": ("YouTuberとして活動していますか？", "occupation"),
        "director": ("監督（映画やアニメなど）ですか？", "occupation"),
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
        
        # ★ 追加
        "mc": ("司会者（MC）として有名ですか？", "activity"),
        "radio": ("ラジオ番組を持っていますか？", "activity"),
        "cm": ("CMに多く出演していますか？", "activity"),
        "married": ("結婚していることを公表していますか？", "feature"),
        "author": ("本（エッセイなど）を出版したことがありますか？", "feature"),
    }

    # ★ カテゴリと、それに関連する質問キーの「対応表」 (拡張) ★
    CATEGORY_TO_FEATURE_MAP = {
        # 芸能
        "日本の俳優": ["taiga", "tokusatsu", "romance_drama", "movie", "action", "stage", "nhk", "award", "hollywood", "mc", "radio", "cm", "married", "author"],
        "日本の女優": ["taiga", "romance_drama", "movie", "stage", "nhk", "award", "model", "mc", "radio", "cm", "married", "author"],
        "お笑い芸人": ["comedian", "youtuber", "movie", "stage", "mc", "radio", "married", "author"],
        "日本の声優": ["seiyuu", "anime", "singer", "stage", "radio"],
        "日本のアイドル": ["idol", "singer", "model", "movie", "stage", "radio", "cm"],
        "日本のモデル": ["model", "romance_drama", "cm"],
        "日本の歌手": ["singer", "award", "nhk", "movie", "radio", "author"],
        "日本のYouTuber": ["youtuber", "comedian", "mc"],
        # スポーツ
        "日本のスポーツ選手": ["athlete"], "日本のサッカー選手": ["athlete"], "日本の野球選手": ["athlete"],
        "日本の柔道家": ["athlete"], "日本のレスリング選手": ["athlete"], "日本のオリンピック選手": ["athlete"],
        "日本の水泳選手": ["athlete"], "日本の陸上競技選手": ["athlete"], "日本のテニス選手": ["athlete"],
        "日本のバレーボール選手": ["athlete"], "日本のバスケットボール選手": ["athlete"],
        # 政治
        "日本の政治家": ["politician", "grad_todai", "grad_waseda", "grad_keio", "author"],
        "日本の外交官": ["politician", "grad_todai"], 
        "日本の官僚": ["politician", "grad_todai"],
        # 文化
        "日本の作家": ["author", "award", "movie", "anime", "grad_todai", "grad_waseda", "grad_keio"],
        "日本の漫画家": ["author", "award", "movie", "anime"],
        "日本の小説家": ["author", "award", "movie", "anime"],
    }
    
    allowed_feature_keys = set()
    if not selected_categories or len(selected_categories) == len(CATEGORIES):
        allowed_feature_keys = set(feature_questions_def.keys())
    else:
        for cat in selected_categories:
            allowed_feature_keys.update(CATEGORY_TO_FEATURE_MAP.get(cat, []))

    for key in allowed_feature_keys:
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
# ★ アキネーター対話部分（「賢いスキップ」削除版）
#-----------------------
def akinator_play(dataset, selected_categories=None, max_questions=30, check_every=10):
    candidates = dataset.copy()
    qm_dict = generate_question_map(dataset, selected_categories) 
    print("=== アキネーター開始 ===")
    print(f"候補人数: {len(candidates)} 件")

    asked_keys = set()
    asked_count = 0

    for q_category in ["occupation", "common", "activity", "feature"]:
        if len(candidates) <= 1 or asked_count >= max_questions: break 
        question_list = qm_dict[q_category]
        random.shuffle(question_list) 

        for question in question_list:
            if asked_count >= max_questions or len(candidates) <= 1: break
            
            key, q_text, test = question.get("key"), question.get("text"), question.get("check")

            if key in asked_keys: continue
            
            # --- 「賢いスキップ」機能は削除済み ---

            # --- 質問実行 ---
            ans = input(q_text + " （はい/いいえ/わからない） > ").strip()
            asked_keys.add(key) 

            if ans not in ["はい", "いいえ"]:
                print("スキップ"); continue

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
        print("候補が見つかりませんでした。"); return None

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
# エントリポイント用関数 (変更なし / 10/30 修正版)
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
        if not ds: return None
        selected_categories = kwargs.get("selected_categories")
        return akinator_play(ds, 
                             selected_categories=selected_categories, 
                             max_questions=kwargs.get("max_questions", 30))
    else:
        raise ValueError("step must be one of: collect, build, play")

# -----------------------
# 実行部分 (変更なし / 10/30 修正版)
# -----------------------
if __name__ == "__main__":
    # --- 実行パラメータ ---
    SLEEP = 0.5     # APIアクセス間隔 (秒)
    CMLIMIT = 50
    DEPTH = 1
    BUILD_LIMIT = 200  # ★ 1000人程度に増やすことを推奨します
    MAX_QUESTIONS = 25

    # --- 実行フロー ---
    try:
        selected_categories = choose_categories()
        
        run_step("collect", 
                 categories=selected_categories, 
                 cmlimit=CMLIMIT, 
                 depth=DEPTH, 
                 sleep=SLEEP)
        
        run_step("build", 
                 limit=BUILD_LIMIT, 
                 sleep=SLEEP)
        
        run_step("play", 
                 selected_categories=selected_categories, 
                 max_questions=MAX_QUESTIONS)
                 
    except KeyboardInterrupt:
        print("\n処理が中断されました。")
    except Exception as e:
        print(f"\nエラーが発生しました: {e}")