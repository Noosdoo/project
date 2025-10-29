import requests
import time
import json
import os
import re
import random
import wikipediaapi
from concurrent.futures import ThreadPoolExecutor, as_completed

# Wikipediaにアクセスする際のユーザーエージェント
USER_AGENT = "CelebrityAkinatorBot/1.0 (https://github.com/yourproject; contact@example.com)"
WIKI_API = "https://ja.wikipedia.org/w/api.php"
WIKIDATA_ENTITY_URL = "https://www.wikidata.org/wiki/Special:EntityData/{}.json"

# 保存先ファイル名
PEOPLE_LIST_FILE = "people_list.json"  # 取得した人物タイトルのリスト
DATASET_FILE = "people_dataset.json"   # 各人物の属性データ

# 取得対象カテゴリ（必要に応じて増やす）
CATEGORIES = [
    "日本の俳優",
    "日本の女優",
    "日本の歌手",
    "日本のお笑いタレント",
    "日本の声優",
    "日本の政治家",
    "日本のスポーツ選手",
    "日本の作家",
    "日本のアイドル",
]

# Wikipedia APIに送る際のヘッダー
HEADERS = {"User-Agent": USER_AGENT}

# ユーティリティ: Wikipediaカテゴリからタイトル取得（cmcontinue対応）
# depth: サブカテゴリをたどる深さ（0=直下のみ、1=1階層下まで）








# -----------------------
# ユーティリティ: Wikipediaカテゴリからタイトル取得（cmcontinue対応）
# -----------------------

# カテゴリから人物を収集する関数（カテゴリ名、１回のAPIリクエストで取得する件数、サブカテゴリをたどる深さ、再帰用、アクセス間隔）
def get_category_members(category, cmlimit=50, depth=1, collected=None, sleep=0.8):
    """
    category: "日本の俳優" のようなカテゴリ名（"Category:" は不要）
    cmlimit: 1リクエスト当たりの取得数（Colab利用なら50程度推奨）
    depth: サブカテゴリをたどる階層深さ
    collected: 内部用（再帰時に渡す）
    """

    # 再帰呼び出しでなければ、新しいセットを作成
    if collected is None:
        collected = set()

    # Wikipedia API用に "Category:" プレフィックスをつける
    cmtitle = f"Category:{category}"

    # APIパラメータ設定
    params = {
        "action": "query",           # クエリ実行モード
        "list": "categorymembers",   # カテゴリ内のメンバーを取得
        "cmtitle": cmtitle,          # 対象カテゴリ
        "cmlimit": str(cmlimit),     # 取得件数上限
        "format": "json"             # 結果形式（jsonとは人間が読み書きしやすいシンプルなテキスト形式）
    }

    cont = None  # 取得が複数ページに分かれる場合の継続トークンを格納
    while True:

        # 続きがあればパラメータに追加
        if cont:
            params.update(cont)
        try:
            # Wikipedia APIにリクエストを送信
            res = requests.get(WIKI_API, params=params, headers=HEADERS, timeout=15)
        except Exception as e:
            # 通信エラー時は報告して終了
            print("HTTPエラー:", e)
            return collected

        # アクセス拒否された場合
        if res.status_code == 403:
            print("403 Forbidden: Wikipediaがアクセスを拒否しました。時間を置いて再試行してください。")
            return collected

        # JSONのパースを試みる
        try:
            data = res.json()
        except Exception as e:
            print("JSONデコード失敗:", e)
            return collected

        # 結果から「カテゴリ内のページ一覧」を取り出す
        for m in data.get("query", {}).get("categorymembers", []):
            title = m.get("title")
            if not title:
                continue
            # サブカテゴリを見つけたら、深さが残っていれば再帰
            if title.startswith("Category:"):
                if depth > 0:
                    subcat = title[len("Category:"):]
                    time.sleep(sleep)  # アクセス間隔を空ける
                    get_category_members(subcat, cmlimit=cmlimit, depth=depth-1, collected=collected, sleep=sleep)
                continue
            # 除外ルール（団体類などを排除）
            if any(x in title for x in ["協会", "連合", "論争", "番組", "映画", "会社", "局", "団体", "目録"]):
                continue

            # 個人名をセットに追加
            collected.add(title)

        # 結果に「続き」がある場合は、次のページを取得する
        if "continue" in data:
            cont = data["continue"]
            time.sleep(sleep)
        else:
            # 全て取得し終えたら終了
            break

    # すべてのタイトルを返す（set型）
    return collected



def choose_categories():
    print("=== カテゴリを選択してください ===")
    for i, cat in enumerate(CATEGORIES, 1):
        print(f"{i}. {cat}")
    print("複数選ぶ場合はカンマ区切りで番号を入力してください (例: 1,3,5)")

    choice = input("> ").strip()
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
    return selected








# -----------------------
# Step1: 全カテゴリから人物を収集して保存
# -----------------------

# 指定したWikipediaカテゴリから、そのカテゴリに含まれる人物のタイトルを取得する関数（ 、APIで一回に取得する件数、下位カテゴリをどの階層まで探索するか、API呼び出し間の待機時間）
def collect_people(categories=CATEGORIES, cmlimit=50, depth=0, sleep=0.8, save_path=PEOPLE_LIST_FILE):
    # --- 開始メッセージ ---
    print("=== カテゴリから人物リストを収集します ===")

    # 全カテゴリの人物をまとめて保持するためのセット（重複を自動的に排除）
    all_people = set()

    # --- 各カテゴリを順番に処理 ---
    for cat in categories:
        print(f"取得中: {cat}")  # 現在処理中のカテゴリ名を表示
        people = get_category_members(cat, cmlimit=cmlimit, depth=depth, sleep=sleep)

        # 取得した件数を表示
        print(f"  → {len(people)} 人取得")

        # 取得結果を全体のセットに追加（重複は自動的に無視される）
        all_people.update(people)

        # Wikipedia APIサーバーに負荷をかけないよう、少し待機
        time.sleep(sleep)

    # set → list に変換し、アルファベット順（または五十音順）に並び替え
    people_list = sorted(list(all_people))

    # --- JSONファイルとして保存 ---
    # save_path : 保存先のファイルパス（例: "people_list.json"）
    # ensure_ascii=False → 日本語をそのまま保存
    # indent=2 → 見やすい整形出力
    with open(save_path, "w", encoding="utf-8") as f:
        json.dump(people_list, f, ensure_ascii=False, indent=2)

    # 保存完了メッセージ
    print(f"保存しました: {save_path} （合計 {len(people_list)} 人）")
    
    # 最後に人物リストを返す（後の処理で使うため）
    return people_list






# -----------------------
# Wikidata取得補助: Wikipediaページからwikibase_itemを得る
# -----------------------
def get_wikibase_item_from_wikipedia(title):
    params = {
        "action": "query",      # データを取得するアクション
        "titles": title,        # 対象ページのタイトル
        "prop": "pageprops",    # ページのプロパティ情報を取得（Wikibase item ID を含む）
        "format": "json"        # 返り値の形式をJSONに指定
    }
    try:
        # Wikipedia APIにリクエストを送信
        # ここでは、あらかじめ定義してあるグローバル変数 WIKI_API と HEADERS を使用
        # timeout=15 は15秒以内に応答がなければ中断する設定
        
        res = requests.get(WIKI_API, params=params, headers=HEADERS, timeout=15)
        # 返ってきたデータをJSON形式に変換
        data = res.json()
        # JSONから目的のデータ構造（"query" → "pages"）を取得
        pages = data.get("query", {}).get("pages", {})
        # ページ情報がなければ None を返す（エラー回避）
        if not pages:
            return None
        # ページ情報は通常1件なので、最初の要素を取得
        page = next(iter(pages.values()))
        # pageprops というキーに Wikidata ID が格納されている
        pp = page.get("pageprops", {})
        # WikidataのQID（例："Q706142"）を取得して返す
        return pp.get("wikibase_item")
    except Exception:
        # 何らかの通信エラー・構文エラー・タイムアウトが発生した場合は安全に None を返す
        return None






# -----------------------
# Wikidataから構造化属性を取得（P106: 職業, P21: 性別, P569: 生年月日, P570: 死亡日）
# ※ 返り値は辞書。失敗時はNone
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
            except Exception:
                pass
        # birth (P569)
        if "P569" in claims:
            try:
                t = claims["P569"][0]["mainsnak"]["datavalue"]["value"]["time"]
                result["birth_time"] = t  # +YYYY-MM-DD...
            except Exception:
                pass
        # death (P570)
        if "P570" in claims:
            try:
                t = claims["P570"][0]["mainsnak"]["datavalue"]["value"]["time"]
                result["death_time"] = t
            except Exception:
                pass
        return result
    except Exception:
        return None

# -----------------------
# summaryからキーワードベースで特徴を抽出する（拡張版）
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
    # 年代判定（summaryに年が書かれている場合）
    # try to find birth year pattern: YYYY年
    m = re.search(r'(\d{4})年', s)
    birth_year = None
    if m:
        try:
            birth_year = int(m.group(1))
        except:
            birth_year = None
    features["birth_year"] = birth_year
    # alive (naive: "没" or "死去" presence)
    features["alive_text"] = 0 if ("没" in s or "死去" in s or "亡くな" in s) else 1
    return features

# -----------------------
# Step2: people list -> build dataset (attributes per person)
# - resume: 既存のDATASET_FILEがあれば読み込み、まだ無い人だけ処理
# - limit: デバッグ用に処理件数を制限可能
# -----------------------
def build_dataset(people_list_path=PEOPLE_LIST_FILE, dataset_path=DATASET_FILE, limit=None, sleep=0.8):
    # load people list
    if not os.path.exists(people_list_path):
        print("人物リストが存在しません。まず collect_people を実行してください。")
        return None

    with open(people_list_path, "r", encoding="utf-8") as f:
        people = json.load(f)

    # load existing dataset to resume
    existing = {}
    if os.path.exists(dataset_path):
        with open(dataset_path, "r", encoding="utf-8") as f:
            try:
                existing = {p["name"]: p for p in json.load(f)}
            except:
                existing = {}

    wiki = wikipediaapi.Wikipedia(user_agent=USER_AGENT, language="ja")

    new_records = []
    processed = 0
    for name in people:
        if limit and processed >= limit:
            break
        if name in existing:
            continue  # already processed

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
            # try wikidata
            wikibase_id = get_wikibase_item_from_wikipedia(name)
            if wikibase_id:
                wd = fetch_wikidata_entity(wikibase_id)
                rec["wikidata"] = wd
                # if wikidata contains gender_qid or occupation_qids, we add simple derived flags
                if wd:
                    # gender qid mapping (Q6581097 male, Q6581072 female)
                    g = wd.get("gender_qid")
                    if g:
                        if g == "Q6581097":
                            rec["features"]["gender"] = "male"
                        elif g == "Q6581072":
                            rec["features"]["gender"] = "female"
                    # occupation qids: we can mark actor/singer/politician based on common Qs
                    occ_qs = wd.get("occupation_qids", [])
                    # known qids
                    if "Q33999" in occ_qs:  # actor (wikidata actor Q33999)
                        rec["features"]["actor_wikidata"] = 1
                    if "Q177220" in occ_qs or "Q639669" in occ_qs:  # singer / vocalist (Q177220 is singer)
                        rec["features"]["singer_wikidata"] = 1
                    if "Q82955" in occ_qs or "Q82955" in occ_qs:
                        rec["features"]["politician_wikidata"] = 1
                    # birth/death from wikidata
                    if wd.get("birth_time"):
                        rec["features"]["birth_time"] = wd.get("birth_time")
                    if wd.get("death_time"):
                        rec["features"]["death_time"] = wd.get("death_time")
            print("OK")
        except Exception as e:
            print("失敗:", e)
        new_records.append(rec)
        processed += 1
        time.sleep(sleep)

    # merge existing + new
    merged = list(existing.values()) + new_records
    with open(dataset_path, "w", encoding="utf-8") as f:
        json.dump(merged, f, ensure_ascii=False, indent=2)
    print(f"データセットを保存しました: {dataset_path}（合計 {len(merged)} 件）")
    return merged

# -----------------------
# Step3: アキネーター本体（datasetを読み込んで対話で絞り込み）
# - 質問は dataset の features keys と FEATURE_KEYWORDS に基づくものを提示する
# -----------------------
def load_dataset(dataset_path=DATASET_FILE):
    if not os.path.exists(dataset_path):
        print("データセットが見つかりません。まず build_dataset を実行してください。")
        return None
    with open(dataset_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return data

def generate_question_map():
    # 質問キー -> (説明文, lambda to test record)
    qm = []
    # add keyword-based features
    for key, kws in FEATURE_KEYWORDS.items():
        text = {
            "taiga": "大河ドラマに出演しましたか？",
            "tokusatsu": "特撮作品に出演しましたか？",
            "romance_drama": "恋愛ドラマに出演しましたか？",
            "movie": "映画にも出演していますか？",
            "action": "アクション作品に出演していますか？",
            "seiyuu": "声優としての仕事がありますか？",
            "singer": "歌手活動もしていますか？",
            "stage": "舞台（演劇・ミュージカル）にも出演していますか？",
            "model": "モデルとして活動したことがありますか？",
            "comedian": "お笑い芸人ですか？",
            "anime": "アニメ作品に関わったことがありますか？",
            "hollywood": "海外（ハリウッド等）にも進出していますか？",
            "idol": "アイドル経験がありますか？",
            "award": "演技賞などを受賞したことがありますか？",
            "nhk": "NHKの番組に出演したことがありますか？",
            "youtuber": "YouTubeチャンネルを持っていますか？",
            "athlete": "スポーツ選手ですか？",
            "politician": "政治家ですか？"
        }.get(key, f"{key} に該当しますか？")
        # test lambda: record->True/False or None
        def make_test(k):
            return lambda rec: bool(rec.get("features", {}).get(k, 0))
        qm.append((key, text, make_test(key)))
    # add Wikidata-derived tests
    qm.append(("alive_text", "現在もご存命ですか？", lambda rec: rec.get("features", {}).get("alive_text") == 1))
    qm.append(("gender_male", "男性ですか？", lambda rec: rec.get("features", {}).get("gender") == "male"))
    qm.append(("gender_female", "女性ですか？", lambda rec: rec.get("features", {}).get("gender") == "female"))

    return qm

def akinator_play(dataset, max_questions=30):
    # candidates is list of records (dicts)
    candidates = dataset.copy()
    qm = generate_question_map()
    random.shuffle(qm)

    print("=== アキネーター開始 ===")
    print(f"候補人数: {len(candidates)} 件")
    asked = 0
    for key, q_text, test in qm:
        if asked >= max_questions:
            break
        # skip if too narrow
        if len(candidates) <= 3:
            break
        ans = input(q_text + " （はい/いいえ/わからない） > ").strip()
        if ans not in ["はい", "いいえ"]:
            print("スキップ")
            continue
        # filter candidates
        if ans == "はい":
            candidates = [c for c in candidates if test(c)]
        else:
            candidates = [c for c in candidates if not test(c)]
        asked += 1
        print(f"現在の候補数: {len(candidates)}")
        # show top 5 names as examples
        print("（例）上位候補:", [c["name"] for c in candidates[:5]])
        # quick stop if 1 left
        if len(candidates) <= 1:
            break

    # final guess
    if not candidates:
        print("候補が見つかりませんでした。")
        return None
    # choose best: if features match many yes answers, prefer those with more matching features
    # simple heuristic: count matched tests
    # We'll ask user to confirm top 3
    print("\n候補上位（3件）:")
    for i, c in enumerate(candidates[:3], 1):
        print(f"{i}. {c['name']}")
    choice = input("上の中にあなたの思い浮かべた人物はいますか？ (番号 または n) > ").strip()
    if choice.isdigit():
        idx = int(choice)-1
        if 0 <= idx < len(candidates[:3]):
            print(f"それでは、あなたが思い浮かべた人物は『{candidates[idx]['name']}』ですね！")
            return candidates[idx]
    print(f"私の推測：『{candidates[0]['name']}』かもしれません。")
    return candidates[0]

# -----------------------
# 改良版: 並列処理でデータセット構築
# -----------------------
def build_dataset_parallel(limit=200, workers=10):
    if not os.path.exists(PEOPLE_LIST_FILE):
        print("まず collect_people を実行してください")
        return

    with open(PEOPLE_LIST_FILE, "r", encoding="utf-8") as f:
        people = json.load(f)[:limit]

    results = []
    wiki = wikipediaapi.Wikipedia(user_agent=USER_AGENT, language="ja")

    def fetch_data(person):
        page = wiki.page(person)
        summary = page.summary if page.exists() else None
        wikibase_id = get_wikibase_item_from_wikipedia(person)
        wikidata = fetch_wikidata_entity(wikibase_id) if wikibase_id else None
        features = extract_features_from_summary(summary)
        if wikidata:
            # gender
            g = wikidata.get("gender_qid")
            if g:
                if g == "Q6581097":
                    features["gender"] = "male"
                elif g == "Q6581072":
                    features["gender"] = "female"
            # occupation
            occ_qs = wikidata.get("occupation_qids", [])
            if "Q33999" in occ_qs:  # actor
                features["actor_wikidata"] = 1
            if "Q177220" in occ_qs:  # singer
                features["singer_wikidata"] = 1
            if "Q82955" in occ_qs:  # politician
                features["politician_wikidata"] = 1
            # birth/death
            if wikidata.get("birth_time"):
                features["birth_time"] = wikidata.get("birth_time")
            if wikidata.get("death_time"):
                features["death_time"] = wikidata.get("death_time")
        return {"name": person, "summary": summary, "features": features, "wikidata": wikidata}

    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = [executor.submit(fetch_data, p) for p in people]
        for i, future in enumerate(as_completed(futures), 1):
            results.append(future.result())
            print(f"\r処理中: {i}/{len(people)}", end="", flush=True)

    with open(DATASET_FILE, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    print(f"\nデータセット作成完了: {len(results)} 件")
    return results


def fetch_data(person):
    wiki = wikipediaapi.Wikipedia(user_agent=USER_AGENT, language="ja")
    page = wiki.page(person)
    summary = page.summary if page.exists() else None
    wikibase_id = get_wikibase_item_from_wikipedia(person)
    wikidata = fetch_wikidata_entity(wikibase_id) if wikibase_id else None
    return {"title": person, "summary": summary, "wikidata": wikidata}

    with ThreadPoolExecutor(max_workers=10) as executor:
        futures = [executor.submit(fetch_data, p) for p in people]
        for future in as_completed(futures):
            results.append(future.result())

    with open(PEOPLE_DATASET_FILE, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)




# -----------------------
# エントリポイント用関数
# -----------------------
def run_step(step="collect", **kwargs):
    """
    step: "collect" / "build" / "play"
    collect: categories -> people_list.json
        kwargs: cmlimit, depth, sleep
    build: people_list.json -> people_dataset.json
        kwargs: limit (int, optional), sleep
    play: load people_dataset.json -> interactive game
        kwargs: max_questions
    """
    step = step.lower()
    if step == "collect":
        cmlimit = kwargs.get("cmlimit", 50)
        depth = kwargs.get("depth", 1)
        sleep = kwargs.get("sleep", 0.8)
        return collect_people(categories=CATEGORIES, cmlimit=cmlimit, depth=depth, sleep=sleep)
    elif step == "build":
        limit = kwargs.get("limit", None)
        sleep = kwargs.get("sleep", 0.8)
        return build_dataset(limit=limit, sleep=sleep)
    elif step == "play":
        ds = load_dataset()
        if not ds:
            return None
        return akinator_play(ds, max_questions=kwargs.get("max_questions", 30))
    else:
        raise ValueError("step must be one of: collect, build, play")

if __name__ == "__main__":
    selected_categories = choose_categories()
    if not os.path.exists(PEOPLE_LIST_FILE):
        run_step("collect", categories=selected_categories, cmlimit=20, depth=0, sleep=0.0001)
    else:
        print("人物リストが既に存在するため、再取得をスキップします。")

    run_step("build", limit=200, sleep=0.0001)
    run_step("play", max_questions=25)