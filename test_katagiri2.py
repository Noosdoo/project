import requests
import time
import json
import os
import re
import random
import wikipediaapi
import unicodedata 
from datetime import datetime 
from concurrent.futures import ThreadPoolExecutor, as_completed 

# Wikipediaにアクセスする際のユーザーエージェント
USER_AGENT = "CelebrityAkinatorBot/1.0 (https://github.com/yourproject; contact@example.com)"
# WikipediaおよびWikidataのAPIエンドポイント
WIKI_API = "https://ja.wikipedia.org/w/api.php"
WIKIDATA_ENTITY_URL = "https://www.wikidata.org/wiki/Special:EntityData/{}.json"

# 保存先ファイル名
PEOPLE_LIST_FILE = "people_list.json"  # 取得した人物タイトルのリスト
DATASET_FILE = "people_dataset.json"   # 各人物の属性データ

# 取得対象カテゴリ (元のまま)
CATEGORIES = [
    "日本の俳優", "日本の女優", "お笑い芸人", "日本の声優", "日本のアイドル", "日本のモデル", "日本の歌手",
    "日本の作曲家", "日本の映画監督", "日本の舞台俳優", "日本のアナウンサー", "日本のYouTuber",
    "日本の作家", "日本の漫画家", "日本の小説家", "日本の詩人", "日本の科学者", "日本の数学者", "日本の物理学者",
    "日本の化学者", "日本の医師", "日本の哲学者", "日本の歴史学者", "日本の教育者", "日本の研究者", "日本の発明家",
    "日本の政治家", "日本の外交官", "日本の官僚", "日本の経営者", "日本の起業家", "日本の弁護士", "日本の裁判官",
    "日本のスポーツ選手", "日本のサッカー選手", "日本の野球選手", "日本の柔道家", "日本のレスリング選手", "日本のオリンピック選手",
    "日本の水泳選手", "日本の陸上競技選手", "日本のテニス選手", "日本のバレーボール選手", "日本のバスケットボール選手",
    "日本の画家", "日本の彫刻家", "日本の写真家", "日本の建築家", "日本のデザイナー", "日本の陶芸家", "日本の演出家",
    "日本の音楽家", "日本の指揮者", "日本の舞踏家",
]

# Wikipedia APIに送る際のヘッダー
HEADERS = {"User-Agent": USER_AGENT}


# -----------------------
# 除外ルール: 人物ページかどうか判定
# -----------------------
def is_person_page(title):
    exclude_keywords = ["一覧", "号", "歴史", "編"]
    return not any(k in title for k in exclude_keywords)

# -----------------------
# ユーティリティ: Wikipediaカテゴリからタイトル取得
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
# カテゴリ選択
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
# Step1: 全カテゴリから人物を収集して保存 
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
# Wikidata取得補助
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
# Wikidataから構造化属性を取得 
# -----------------------
def fetch_wikidata_entity(wikibase_id):
    """
    WikidataのエンティティURLから、指定された属性(Claim)を取得する。
    元の関数とほぼ同じだが、エラーハンドリングを少し強化。
    """
    if not wikibase_id:
        return None
    try:
        url = WIKIDATA_ENTITY_URL.format(wikibase_id)
        res = requests.get(url, headers=HEADERS, timeout=15)
        res.raise_for_status() # 4xx, 5xxエラーで例外を発生
        data = res.json()
        entity = data.get("entities", {}).get(wikibase_id, {})
        claims = entity.get("claims", {})
        result = {}
        
        # P106 (職業)
        if "P106" in claims:
            occ = [c["mainsnak"]["datavalue"]["value"]["id"] for c in claims["P106"] 
                   if c.get("mainsnak", {}).get("datavalue", {}).get("value", {}).get("id")]
            if occ: result["occupation_qids"] = list(set(occ)) # 重複排除
            
        # P21 (性別)
        if "P21" in claims:
            try:
                result["gender_qid"] = claims["P21"][0]["mainsnak"]["datavalue"]["value"]["id"]
            except (KeyError, IndexError, TypeError): pass
            
        # P569 (生年月日)
        if "P569" in claims:
            try:
                # +YYYY-MM-DDTHH:MM:SSZ 形式
                t = claims["P569"][0]["mainsnak"]["datavalue"]["value"]["time"]
                result["birth_time"] = t
            except (KeyError, IndexError, TypeError): pass
            
        # P570 (没年月日)
        if "P570" in claims:
            try:
                t = claims["P570"][0]["mainsnak"]["datavalue"]["value"]["time"]
                result["death_time"] = t
            except (KeyError, IndexError, TypeError): pass
            
        # P19 (出身地)
        if "P19" in claims:
            try:
                result["birth_place_qid"] = claims["P19"][0]["mainsnak"]["datavalue"]["value"]["id"]
            except (KeyError, IndexError, TypeError): pass
            
        # P69 (学歴)
        if "P69" in claims:
            edu = [c["mainsnak"]["datavalue"]["value"]["id"] for c in claims["P69"]
                   if c.get("mainsnak", {}).get("datavalue", {}).get("value", {}).get("id")]
            if edu: result["education_qids"] = list(set(edu))

        # P166 (受賞歴)
        if "P166" in claims:
            award = [c["mainsnak"]["datavalue"]["value"]["id"] for c in claims["P166"]
                     if c.get("mainsnak", {}).get("datavalue", {}).get("value", {}).get("id")]
            if award: result["award_qids"] = list(set(award))
        
        return result
    except requests.exceptions.RequestException as e:
        print(f"  ! Wikidata取得エラー (ID: {wikibase_id}): {e}")
        return None
    except Exception as e:
        print(f"  ! Wikidata解析エラー (ID: {wikibase_id}): {e}")
        return None

# -----------------------
# 【廃止】summaryからキーワードベースで特徴を抽出 
# def extract_features_from_summary(summary): ...
# → 不正確さの原因となるため、この関数は使用しない
# -----------------------

# -----------------------
# Step2: people list -> build dataset 
# -----------------------
def load_people_list(people_list_path=PEOPLE_LIST_FILE):
    if not os.path.exists(people_list_path): return None
    try:
        with open(people_list_path, "r", encoding="utf-8") as f: data = json.load(f)
        if isinstance(data, dict): return data.get("people")
        elif isinstance(data, list): return data
        return None
    except Exception: return None


# -----------------------
# Step2: build dataset 並行処理版 (改良)
# -----------------------
def build_dataset_parallel(people_list_path=PEOPLE_LIST_FILE, dataset_path=DATASET_FILE,
                            limit=None, max_workers=10, sleep=0.5):
    """
    並列処理でデータセットを構築する。
    曖昧な「summaryキーワード検索」を排除し、Wikidataの属性のみをfeaturesに格納する。
    """
    people = load_people_list(people_list_path)
    if people is None:
        print("人物リストが存在しません。まず collect_people を実行してください。")
        return None

    # 既存データの読み込み
    existing = {}
    if os.path.exists(dataset_path):
        try:
            with open(dataset_path, "r", encoding="utf-8") as f:
                existing = {p["name"]: p for p in json.load(f)}
                print(f"{len(existing)} 件の既存データを読み込みました。未処理のみ並列処理します。")
        except Exception as e:
            print("既存データ読み込み失敗:", e)
            existing = {}

    # 処理対象を絞る
    targets = [n for n in people if n not in existing]
    if limit:
        targets = targets[:limit]
    print(f"処理対象: {len(targets)} 件")

    # スレッドで個別処理
    def process_person(name):
        try:
            # wikipedia-apiライブラリはWikidata IDの取得にのみ使用
            wiki = wikipediaapi.Wikipedia(user_agent=USER_AGENT, language="ja")
            page = wiki.page(name)
            
            if not page.exists():
                return {"name": name, "error": "ページなし"}

            # 返却するレコードの雛形
            rec = {"name": name, "features": {}, "wikidata": None}
            features = {}

            # --- 名前構造 ---
            if re.search(r'[ァ-ヶ]', name):
                features["has_katakana"] = 1
            if re.fullmatch(r'[ぁ-ん]+', name):
                features["is_hiragana_only"] = 1

            # --- Wikidata取得 ---
            # wikibase_id = get_wikibase_item_from_wikipedia(name) # 古い方法
            wikibase_id = page.wikibase # wikipediaapiライブラリの機能
            
            if wikibase_id:
                wd = fetch_wikidata_entity(wikibase_id)
                rec["wikidata"] = wd # 生のWikidata情報も保存
                if wd:
                    # 【重要】WikidataのQIDを、アキネーターの質問キー(features)に変換する
                    
                    # 性別 (Q6581097=男性, Q6581072=女性)
                    g = wd.get("gender_qid")
                    if g == "Q6581097":
                        features["gender_male"] = 1
                    elif g == "Q6581072":
                        features["gender_female"] = 1

                    # 職業 (QIDベースで判定)
                    occ_qs = wd.get("occupation_qids", [])
                    if any(q in occ_qs for q in ["Q33999", "Q10800557", "Q947873"]): # 俳優, 女優など
                        features["occupation_actor"] = 1
                    if any(q in occ_qs for q in ["Q177220", "Q639669"]): # 歌手, ミュージシャン
                        features["occupation_singer"] = 1
                    if "Q28389" in occ_qs: # 政治家
                        features["occupation_politician"] = 1
                    if "Q1028181" in occ_qs: # 声優
                        features["occupation_seiyuu"] = 1
                    if "Q482980" in occ_qs: # サッカー選手
                        features["occupation_soccer"] = 1
                    if "Q11774891" in occ_qs: # 野球選手
                        features["occupation_baseball"] = 1
                    if "Q11774891" in occ_qs: # お笑い芸人
                         features["occupation_comedian"] = 1
                    if "Q131524" in occ_qs: # YouTuber
                         features["occupation_youtuber"] = 1

                    # 出身地
                    place_qid = wd.get("birth_place_qid")
                    # (QIDのハードコーディングは元のコードの仕様を踏襲)
                    if place_qid in {"Q1490", "Q1228"}: # 東京都, 江戸
                        features["from_tokyo"] = 1
                    elif place_qid in {"Q172582", "Q16997", "Q486245"}: # 大阪府, 京都府, 兵庫県
                        features["from_kansai"] = 1
                    elif place_qid == "Q170036": # 北海道
                        features["from_hokkaido"] = 1
                    elif place_qid == "Q160498": # 福岡県
                        features["from_fukuoka"] = 1
                        
                    # 学歴
                    edu_qids = wd.get("education_qids", [])
                    if "Q7981" in edu_qids: # 東京大学
                        features["grad_todai"] = 1
                    elif "Q174019" in edu_qids: # 早稲田大学
                        features["grad_waseda"] = 1
                    elif "Q302302" in edu_qids: # 慶應義塾大学
                        features["grad_keio"] = 1

                    # 受賞歴
                    award_qids = wd.get("award_qids", [])
                    if "Q1138032" in award_qids: # 紫綬褒章
                        features["award_shiju"] = 1
                    if "Q101086" in award_qids: # アカデミー賞
                        features["award_oscar"] = 1
                    if "Q186490" in award_qids: # 日本アカデミー賞
                        features["award_japan_academy"] = 1

                    # 生年月日・没年月日
                    birth_time = wd.get("birth_time")
                    death_time = wd.get("death_time")
                    
                    if death_time:
                        features["alive_now"] = 0 # 亡くなっている
                        try:
                            if datetime.fromisoformat(death_time.lstrip('+').rstrip('Z')).year < 2000:
                                features["died_20c"] = 1
                        except: pass
                    else:
                        features["alive_now"] = 1 # 存命

                    if birth_time:
                        try:
                            birth_year = datetime.fromisoformat(birth_time.lstrip('+').rstrip('Z')).year
                            features["birth_year"] = birth_year # 年を直接保存
                            
                            if 1980 <= birth_year <= 1989:
                                features["born_1980s"] = 1
                            elif 1990 <= birth_year <= 1999:
                                features["born_1990s"] = 1
                            elif 2000 <= birth_year <= 2009:
                                features["born_2000s"] = 1

                            if features["alive_now"] == 1:
                                age = datetime.now().year - birth_year
                                if 20 <= age <= 29:
                                    features["age_20s"] = 1
                                elif 30 <= age <= 39:
                                    features["age_30s"] = 1
                                elif 40 <= age <= 49:
                                    features["age_40s"] = 1
                                elif 50 <= age <= 59:
                                    features["age_50s"] = 1
                        except: pass

            rec["features"] = features
            return rec

        except Exception as e:
            return {"name": name, "error": str(e)}


    # 並列実行
    new_records = []
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_name = {executor.submit(process_person, name): name for name in targets}
        
        count = 0
        for future in as_completed(future_to_name):
            count += 1
            name = future_to_name[future]
            try:
                rec = future.result()
                if rec:
                    new_records.append(rec)
                
                if "error" in rec:
                    print(f"({count}/{len(targets)}) × {name}: {rec['error']}")
                else:
                    print(f"({count}/{len(targets)}) ✓ {name}")
            except Exception as e:
                print(f"({count}/{len(targets)}) ⚠ {name}: {e}")
            
            # APIへの負荷軽減のため、指定したsleepを挟む
            time.sleep(sleep) 

    # 結合と保存
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
        print("データセットが見つかりません。まず build_dataset_parallel を実行してください。")
        return None
    with open(dataset_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    # エラーのあったデータを除外して返す
    return [d for d in data if "error" not in d and d.get("features")]

# -----------------------
# 質問マップの自動生成 (改良)
# -----------------------
def generate_question_map(dataset, selected_categories=None):
    """
    データセットに存在する「属性(feature)」のみに基づいて、質問マップを動的に生成する。
    """
    qm = {"occupation": [], "activity": [], "feature": [], "common": []}
    added_keys = set() 

    # --- 1. 質問の定義 (Wikidataのfeatureキーと日本語の質問文を対応させる) ---
    # この定義表を充実させるほど、アキネーターは賢くなる
    question_definitions = {
        # 共通
        "gender_male": ("男性ですか？", "common"),
        "gender_female": ("女性ですか？", "common"),
        "alive_now": ("現在もご存命ですか？", "common"),
        "has_katakana": ("名前にカタカナが含まれていますか？", "common"),
        "is_hiragana_only": ("名前はひらがなだけですか？", "common"),
        # 年代
        "age_20s": ("現在、20代ですか？", "common"),
        "age_30s": ("現在、30代ですか？", "common"),
        "age_40s": ("現在、40代ですか？", "common"),
        "age_50s": ("現在、50代ですか？", "common"),
        "born_1980s": ("1980年代生まれですか？", "common"),
        "born_1990s": ("1990年代生まれですか？", "common"),
        "born_2000s": ("2000年代生まれですか？", "common"),
        "died_20c": ("20世紀（1900年代）に亡くなりましたか？", "common"),
        # 職業
        "occupation_actor": ("本業は俳優（女優）ですか？", "occupation"),
        "occupation_singer": ("本業は歌手・ミュージシャンですか？", "occupation"),
        "occupation_politician": ("本業は政治家ですか？", "occupation"),
        "occupation_seiyuu": ("本業は声優ですか？", "occupation"),
        "occupation_soccer": ("本業はサッカー選手ですか？", "occupation"),
        "occupation_baseball": ("本業は野球選手ですか？", "occupation"),
        "occupation_comedian": ("本業はお笑い芸人ですか？", "occupation"),
        "occupation_youtuber": ("本業はYouTuberですか？", "occupation"),
        # 特徴 (出身地・学歴・受賞)
        "from_tokyo": ("出身は東京ですか？", "feature"),
        "from_kansai": ("出身は関西（大阪・京都・兵庫）ですか？", "feature"),
        "from_hokkaido": ("出身は北海道ですか？", "feature"),
        "from_fukuoka": ("出身は福岡ですか？", "feature"),
        "grad_todai": ("東京大学を卒業していますか？", "feature"),
        "grad_waseda": ("早稲田大学を卒業していますか？", "feature"),
        "grad_keio": ("慶應義塾大学を卒業していますか？", "feature"),
        "award_shiju": ("紫綬褒章を受章していますか？", "feature"),
        "award_oscar": ("アカデミー賞を受章していますか？", "feature"),
        "award_japan_academy": ("日本アカデミー賞を受章していますか？", "feature"),
    }
    
    # --- 2. データセットに存在するキーだけを質問マップに追加 ---
    
    # まず、データセットに存在する全featureキーを集計
    all_feature_keys = set()
    for rec in dataset:
        all_feature_keys.update(rec.get("features", {}).keys())

    # 存在するキー かつ 定義表にあるキー だけを質問リストに追加
    for key in all_feature_keys:
        if key in question_definitions:
            text, category = question_definitions[key]
            qm[category].append({
                "key": key, 
                "text": text,
                # check関数: rec["features"] にそのキーが存在し、値が1かどうかを判定
                "check": lambda rec, k=key: rec.get("features", {}).get(k) == 1
            })
            added_keys.add(key)
        
    print(f"質問を生成しました (職業: {len(qm['occupation'])}, 活動: {len(qm['activity'])}, 特徴: {len(qm['feature'])}, 共通: {len(qm['common'])})")
    return qm

# -----------------------
# 最適な質問を見つけるアルゴリズム (変更なし)
# -----------------------
def find_best_question(candidates, qm_dict, asked_keys):
    """
    決定木の「情報利得」の考え方に基づき、
    現在の候補者リスト(candidates)を最も効率よく
    半分(50/50)に分割できる質問を見つけ出します。
    """
    best_question = None
    best_score = -1 

    # 全カテゴリの質問をループ
    for q_category in qm_dict.values():
        for question in q_category:
            key, test = question.get("key"), question.get("check")

            if key in asked_keys:
                continue

            # --- シミュレーション ---
            yes_count = 0
            no_count = 0
            for c in candidates:
                if test(c):
                    yes_count += 1
                else:
                    no_count += 1
            
            # 1. 全員がYesまたは全員がNoの質問は、情報利得ゼロ (スキップ)
            if yes_count == 0 or no_count == 0:
                continue
                
            # 2. 分割の良さをスコア化 (50/50に近いほど高得点)
            score = yes_count * no_count
            
            if score > best_score:
                best_score = score
                best_question = question
                
    return best_question


# -----------------------
# アキネーター本体ループ (変更なし)
# -----------------------
def akinator_play(dataset, selected_categories=None, max_questions=30):
    candidates = dataset.copy()
    qm_dict = generate_question_map(dataset, selected_categories)
    
    print("=== アキネーター開始 ===")
    asked_keys = set()
    asked_count = 0

    while len(candidates) > 1 and asked_count < max_questions:
        question = find_best_question(candidates, qm_dict, asked_keys)
        if question is None:
            print("\n質問が尽きました。残りの候補から推測します...")
            break

        key, q_text, test = question["key"], question["text"], question["check"]
        ans = input(q_text + " （はい/いいえ/わからない） > ").strip().lower()
        asked_keys.add(key)

        # 回答が「はい」「いいえ」以外ならスキップ
        if ans not in ["はい", "いいえ", "y", "n"]:
            print("（スキップします）")
            continue

        is_yes = (ans == "はい" or ans == "y")

        # 候補者をフィルタリング
        if is_yes:
            candidates = [c for c in candidates if test(c)]
        else:
            candidates = [c for c in candidates if not test(c)]

        asked_count += 1
        print(f"(現在の候補数: {len(candidates)}人)")

    # -----------------------------
    # 結果発表
    # -----------------------------
    print("\n=== 最終候補 ===")
    if not candidates:
        print("該当する人物がデータにいませんでした。")
        return None

    for i, c in enumerate(candidates[:3], 1): # 上位3名をリストアップ
        print(f"{i}. {c['name']}")

    choice = input("上の中にあなたの思い浮かべた人物はいますか？ (番号 または なし) > ").strip()
    if choice.isdigit():
        idx = int(choice) - 1
        if 0 <= idx < len(candidates[:3]):
            print(f"それでは、あなたが思い浮かべた人物は『{candidates[idx]['name']}』ですね！")
            return candidates[idx]

    print("候補にいませんでした。残念！")
    return None

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
        return build_dataset_parallel(limit=kwargs.get("limit", None),
                             max_workers=kwargs.get("max_workers", 10),
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
# 実行部分
# -----------------------
if __name__ == "__main__":
    # --- 実行パラメータ (安全な値に変更) ---
    SLEEP = 0.5      # APIアクセス間隔 (秒) ★ 0.5秒以上に設定
    CMLIMIT = 50     # カテゴリから取得する最大人数
    DEPTH = 1        # カテゴリのサブカテゴリをどこまで深く追うか
    BUILD_LIMIT = 200 # データセット構築の上限人数 (Noneで無制限)
    MAX_WORKERS = 5  # 並列処理の最大スレッド数 (5〜10が推奨)
    MAX_QUESTIONS = 25 # アキネーターの最大質問数

    # --- 実行フロー ---
    try:
        # Step 0: どのカテゴリで遊ぶか選択
        selected_categories = choose_categories()
        
        # Step 1: Wikipediaカテゴリから人物名リスト収集 (or キャッシュ読込)
        run_step("collect", 
                 categories=selected_categories, 
                 cmlimit=CMLIMIT, 
                 depth=DEPTH, 
                 sleep=SLEEP)
        
        # Step 2: Wikidataから属性データを並列収集 (or キャッシュ読込)
        run_step("build", 
                 limit=BUILD_LIMIT, 
                 max_workers=MAX_WORKERS,
                 sleep=SLEEP)
        
        # Step 3: アキネーター本体の実行
        run_step("play", 
                 selected_categories=selected_categories, 
                 max_questions=MAX_QUESTIONS)
                 
    except KeyboardInterrupt:
        print("\n処理が中断されました。")
    except Exception as e:
        print(f"\nエラーが発生しました: {e}")
        import traceback
        traceback.print_exc() # 詳細なエラー内容を表示