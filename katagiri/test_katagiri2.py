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

# --- (1. 定義部分は変更なし) ---
USER_AGENT = "CelebrityAkinatorBot/1.0 (https://github.com/yourproject; contact@example.com)"
WIKI_API = "https://ja.wikipedia.org/w/api.php"
WIKIDATA_API = "https://www.wikidata.org/w/api.php" # ★ EntityData.jsonではなく、api.phpを使う

PEOPLE_LIST_FILE = "people_list.json"
DATASET_FILE = "people_dataset.json"

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
HEADERS = {"User-Agent": USER_AGENT}

def is_person_page(title):
    exclude_keywords = ["一覧", "号", "歴史", "編"]
    return not any(k in title for k in exclude_keywords)

def get_category_members(category, cmlimit=50, depth=1, collected=None, sleep=0.8):
    if collected is None: collected = set()
    cmtitle = f"Category:{category}"
    params = {"action": "query", "list": "categorymembers", "cmtitle": cmtitle, "cmlimit": str(cmlimit), "format": "json"}
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

def collect_people(categories=CATEGORIES, cmlimit=50, depth=0, sleep=0.8, save_path=PEOPLE_LIST_FILE):
    # (Step1: collect_people 関数は変更なし)
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


def load_people_list(people_list_path=PEOPLE_LIST_FILE):
    if not os.path.exists(people_list_path): return None
    try:
        with open(people_list_path, "r", encoding="utf-8") as f: data = json.load(f)
        if isinstance(data, dict): return data.get("people")
        elif isinstance(data, list): return data
        return None
    except Exception: return None

# -----------------------
# ★★★ Step2: build dataset (バッチ処理に全面改修) ★★★
# -----------------------

def fetch_wikidata_batch(wikibase_ids):
    """
    WikidataのIDリスト（最大50件）を受け取り、
    全員分の属性（Claim）を一括で取得する
    """
    if not wikibase_ids:
        return {}
        
    # IDを "|" で連結 (例: "Q1|Q2|Q50")
    ids_pipe = "|".join(wikibase_ids)
    
    params = {
        "action": "wbgetentities",
        "ids": ids_pipe,
        "props": "claims", # 属性(Claim)だけ取得
        "format": "json"
    }
    try:
        res = requests.get(WIKIDATA_API, params=params, headers=HEADERS, timeout=20)
        res.raise_for_status()
        data = res.json()
        return data.get("entities", {})
    except requests.exceptions.RequestException as e:
        print(f"  ! Wikidataバッチ取得エラー: {e}")
        return {}
    except Exception as e:
        print(f"  ! Wikidataバッチ解析エラー: {e}")
        return {}

def parse_claims_to_features(claims):
    """
    Wikidataのclaims(属性)を解析し、
    アキネーターの質問キー(features)に変換する
    """
    features = {}
    if not claims:
        return features
        
    # 性別 (P21)
    if "P21" in claims:
        try:
            g = claims["P21"][0]["mainsnak"]["datavalue"]["value"]["id"]
            if g == "Q6581097": features["gender_male"] = 1
            elif g == "Q6581072": features["gender_female"] = 1
        except (KeyError, IndexError, TypeError): pass
    
    # 職業 (P106)
    if "P106" in claims:
        occ_qs = [c["mainsnak"]["datavalue"]["value"]["id"] for c in claims["P106"] 
                if c.get("mainsnak", {}).get("datavalue", {}).get("value", {}).get("id")]
        
        if any(q in occ_qs for q in ["Q33999", "Q10800557", "Q947873"]): features["occupation_actor"] = 1
        if any(q in occ_qs for q in ["Q177220", "Q639669"]): features["occupation_singer"] = 1
        if "Q28389" in occ_qs: features["occupation_politician"] = 1
        if "Q1028181" in occ_qs: features["occupation_seiyuu"] = 1
        if "Q482980" in occ_qs: features["occupation_soccer"] = 1
        if "Q11774891" in occ_qs: features["occupation_baseball"] = 1
        if "Q11774891" in occ_qs: features["occupation_comedian"] = 1
        if "Q131524" in occ_qs: features["occupation_youtuber"] = 1
    
    # 出身地 (P19)
    if "P19" in claims:
        try:
            place_qid = claims["P19"][0]["mainsnak"]["datavalue"]["value"]["id"]
            if place_qid in {"Q1490", "Q1228"}: features["from_tokyo"] = 1
            elif place_qid in {"Q172582", "Q16997", "Q486245"}: features["from_kansai"] = 1
            elif place_qid == "Q170036": features["from_hokkaido"] = 1
            elif place_qid == "Q160498": features["from_fukuoka"] = 1
        except (KeyError, IndexError, TypeError): pass
            
    # 学歴 (P69)
    if "P69" in claims:
        edu_qids = [c["mainsnak"]["datavalue"]["value"]["id"] for c in claims["P69"]
                    if c.get("mainsnak", {}).get("datavalue", {}).get("value", {}).get("id")]
        if "Q7981" in edu_qids: features["grad_todai"] = 1
        if "Q174019" in edu_qids: features["grad_waseda"] = 1
        if "Q302302" in edu_qids: features["grad_keio"] = 1

    # 受賞歴 (P166)
    if "P166" in claims:
        award_qids = [c["mainsnak"]["datavalue"]["value"]["id"] for c in claims["P166"]
                      if c.get("mainsnak", {}).get("datavalue", {}).get("value", {}).get("id")]
        if "Q1138032" in award_qids: features["award_shiju"] = 1
        if "Q101086" in award_qids: features["award_oscar"] = 1
        if "Q186490" in award_qids: features["award_japan_academy"] = 1

    # 生年月日 (P569) / 没年月日 (P570)
    death_time = claims.get("P570", [{}])[0].get("mainsnak", {}).get("datavalue", {}).get("value", {}).get("time")
    birth_time = claims.get("P569", [{}])[0].get("mainsnak", {}).get("datavalue", {}).get("value", {}).get("time")
    
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
            features["birth_year"] = birth_year
            
            if 1980 <= birth_year <= 1989: features["born_1980s"] = 1
            elif 1990 <= birth_year <= 1999: features["born_1990s"] = 1
            elif 2000 <= birth_year <= 2009: features["born_2000s"] = 1

            if features.get("alive_now") == 1:
                age = datetime.now().year - birth_year
                if 20 <= age <= 29: features["age_20s"] = 1
                elif 30 <= age <= 39: features["age_30s"] = 1
                elif 40 <= age <= 49: features["age_40s"] = 1
                elif 50 <= age <= 59: features["age_50s"] = 1
        except: pass

    return features

def build_dataset_parallel(people_list_path=PEOPLE_LIST_FILE, dataset_path=DATASET_FILE,
                            limit=None, max_workers=10, sleep=0.5):
    """
    並列処理でデータセットを構築する (バッチ処理対応版)
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
    if not targets:
        return list(existing.values())

    # --- メインの処理 ---
    # 50件ずつのバッチに分割 (Wikidata APIのID上限が50のため)
    BATCH_SIZE = 50
    batches = [targets[i:i + BATCH_SIZE] for i in range(0, len(targets), BATCH_SIZE)]
    
    # wikipedia-apiライブラリを一度だけ初期化
    wiki = wikipediaapi.Wikipedia(user_agent=USER_AGENT, language="ja")
    
    new_records = []
    
    for i, batch_names in enumerate(batches):
        print(f"\n--- バッチ {i+1}/{len(batches)} (最大 {BATCH_SIZE} 件) を処理 ---")
        
        # 1. (並列) バッチ内の全人物のWikidata ID (QID) を先に取得
        name_to_qid_map = {} # {"大谷翔平": "Q11634676", ...}
        
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_to_name = {executor.submit(wiki.page, name): name for name in batch_names}
            for future in as_completed(future_to_name):
                name = future_to_name[future]
                try:
                    page = future.result()
                    if page.exists() and page.wikibase:
                        name_to_qid_map[name] = page.wikibase
                    else:
                        print(f"  × {name}: ページまたはQIDなし")
                except Exception as e:
                    print(f"  ⚠ {name}: {e}")

        # 2. (一括) QIDリストをWikidata APIに投げて、全属性を取得
        qid_list = list(name_to_qid_map.values())
        print(f"  -> {len(qid_list)} 件のQIDをWikidataに一括問い合わせ...")
        wikidata_entities = fetch_wikidata_batch(qid_list)
        print(f"  <- {len(wikidata_entities)} 件のデータを取得")

        # 3. (逐次) 取得したデータを解析して、レコードを作成
        for name, qid in name_to_qid_map.items():
            entity_data = wikidata_entities.get(qid)
            if not entity_data:
                print(f"  × {name}: Wikidataデータ取得失敗")
                new_records.append({"name": name, "error": "Wikidataデータなし"})
                continue
            
            claims = entity_data.get("claims", {})
            features = parse_claims_to_features(claims)
            
            # 名前に関する特徴を追加
            if re.search(r'[ァ-ヶ]', name): features["has_katakana"] = 1
            if re.fullmatch(r'[ぁ-ん]+', name): features["is_hiragana_only"] = 1
            
            rec = {"name": name, "features": features}
            new_records.append(rec)
            print(f"  ✓ {name}")

        # APIへの負荷軽減のため、バッチごとに待機
        time.sleep(sleep)

    # 結合と保存
    merged = list(existing.values()) + new_records
    with open(dataset_path, "w", encoding="utf-8") as f:
        json.dump(merged, f, ensure_ascii=False, indent=2)

    print(f"データセットを保存しました: {dataset_path}（合計 {len(merged)} 件）")
    return merged

# -----------------------
# Step3: アキネーター本体 (変更なし)
# -----------------------

def load_dataset(dataset_path=DATASET_FILE):
    if not os.path.exists(dataset_path):
        print("データセットが見つかりません。まず build_dataset_parallel を実行してください。")
        return None
    with open(dataset_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return [d for d in data if "error" not in d and d.get("features")]

def generate_question_map(dataset, selected_categories=None):
    qm = {"occupation": [], "activity": [], "feature": [], "common": []}
    added_keys = set() 
    question_definitions = {
        # 共通
        "gender_male": ("男性ですか？", "common"), "gender_female": ("女性ですか？", "common"),
        "alive_now": ("現在もご存命ですか？", "common"),
        "has_katakana": ("名前にカタカナが含まれていますか？", "common"),
        "is_hiragana_only": ("名前はひらがなだけですか？", "common"),
        # 年代
        "age_20s": ("現在、20代ですか？", "common"), "age_30s": ("現在、30代ですか？", "common"),
        "age_40s": ("現在、40代ですか？", "common"), "age_50s": ("現在、50代ですか？", "common"),
        "born_1980s": ("1980年代生まれですか？", "common"), "born_1990s": ("1990年代生まれですか？", "common"),
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
    
    all_feature_keys = set()
    for rec in dataset:
        all_feature_keys.update(rec.get("features", {}).keys())

    for key in all_feature_keys:
        if key in question_definitions:
            text, category = question_definitions[key]
            qm[category].append({
                "key": key, 
                "text": text,
                "check": lambda rec, k=key: rec.get("features", {}).get(k) == 1
            })
            added_keys.add(key)
        
    print(f"質問を生成しました (職業: {len(qm['occupation'])}, 活動: {len(qm['activity'])}, 特徴: {len(qm['feature'])}, 共通: {len(qm['common'])})")
    return qm

def find_best_question(candidates, qm_dict, asked_keys):
    best_question = None
    best_score = -1 
    for q_category in qm_dict.values():
        for question in q_category:
            key, test = question.get("key"), question.get("check")
            if key in asked_keys:
                continue
            yes_count = 0
            no_count = 0
            for c in candidates:
                if test(c): yes_count += 1
                else: no_count += 1
            if yes_count == 0 or no_count == 0:
                continue
            score = yes_count * no_count
            if score > best_score:
                best_score = score
                best_question = question
    return best_question

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

        if ans not in ["はい", "いいえ", "y", "n"]:
            print("（スキップします）")
            continue

        is_yes = (ans == "はい" or ans == "y")
        if is_yes:
            candidates = [c for c in candidates if test(c)]
        else:
            candidates = [c for c in candidates if not test(c)]

        asked_count += 1
        print(f"(現在の候補数: {len(candidates)}人)")

    print("\n=== 最終候補 ===")
    if not candidates:
        print("該当する人物がデータにいませんでした。")
        return None

    for i, c in enumerate(candidates[:3], 1):
        print(f"{i}. {c['name']}")

    choice = input("上の中にあなたの思い浮かべた人物はいますか？ (番号 または なし) > ").strip()
    if choice.isdigit():
        idx = int(choice) - 1
        if 0 <= idx < len(candidates[:3]):
            print(f"それでは、あなたが思い浮かべた人物は『{candidates[idx]['name']}』ですね！")
            return candidates[idx]

    print("候補にいませんでした。残念！")
    return None

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
    # --- 実行パラメータ (★ 制限解除) ---
    SLEEP = 0.5      # バッチごとの待機間隔 (秒)
    CMLIMIT = 50     
    DEPTH = 1        
    BUILD_LIMIT = None # ★ None (制限なし) に変更！
    MAX_WORKERS = 10 # バッチ内の並列処理スレッド数
    MAX_QUESTIONS = 25

    try:
        selected_categories = choose_categories()
        run_step("collect", 
                 categories=selected_categories, 
                 cmlimit=CMLIMIT, 
                 depth=DEPTH, 
                 sleep=SLEEP)
        
        run_step("build", 
                 limit=BUILD_LIMIT, 
                 max_workers=MAX_WORKERS,
                 sleep=SLEEP)
        
        run_step("play", 
                 selected_categories=selected_categories, 
                 max_questions=MAX_QUESTIONS)
                 
    except KeyboardInterrupt:
        print("\n処理が中断されました。")
    except Exception as e:
        print(f"\nエラーが発生しました: {e}")
        import traceback
        traceback.print_exc()