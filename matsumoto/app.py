import os
import glob
import time
from flask import Flask, jsonify, request, session, send_from_directory
from flask_cors import CORS
from flask_session import Session

# ---- inf_learnロジックをインポート ----
try:
    import inf_learn as logic
except ImportError:
    print("エラー: 'inf_learn.py' が見つかりません。app.py と同じフォルダに置いてください。")
    exit()

app = Flask(__name__)
CORS(app)

# セッション設定
app.secret_key = "my-super-secret-key-for-akinator" #
app.config["SESSION_PERMANENT"] = False
app.config["SESSION_TYPE"] = "filesystem"
app.config["SESSION_USE_SIGNER"] = True
app.config["SESSION_FILE_DIR"] = "./flask_session"
Session(app)

# =======================
# データセット管理
# =======================

DATASET_FILES = []   # 利用可能なファイルリスト
DATASET = []         # ロード中のデータセット（リスト）
QM_DICT = {}         # ロード中の質問マップ（辞書）
ACTIVE_DATASET_ID = None

#----------------------
# データセットスキャン＆ロード
#----------------------
def scan_dataset_files():
    """
    カレントディレクトリと ./datasets フォルダから
    people_dataset*.json を探す
    """
    base_dir = os.path.dirname(os.path.abspath(__file__))
    cwd = os.getcwd()
    parent_dir = os.path.dirname(base_dir)
    
    # 探索対象ディレクトリ
    search_dirs = [
        base_dir,
        os.path.join(base_dir, "datasets"),
        cwd,
        os.path.join(cwd, "datasets"),
        os.path.join(parent_dir, "datasets"),
    ]
    
    found_files = set()
    for d in search_dirs:
        if not os.path.isdir(d): continue
        pattern = os.path.join(d, "people_dataset*.json")
        for f in glob.glob(pattern):
            found_files.add(os.path.abspath(f))

    if not found_files:
        print("[WARN] people_dataset*.json が見つかりませんでした。")
        return []

    # ファイル情報作成
    file_infos = []
    for idx, path in enumerate(sorted(found_files)):
        mtime = os.path.getmtime(path)
        basename = os.path.basename(path)
        # ラベル作成 (ファイル名から _ をスペースに置換などで見やすく)
        label = os.path.splitext(basename)[0].replace("people_dataset_", "")
        
        file_infos.append({
            "id": f"ds{idx+1}",
            "path": path,
            "label": label,
            "mtime": mtime,
        })

    # 更新日時順にソート（新しいものがデフォルト）
    file_infos.sort(key=lambda x: x["mtime"], reverse=True)
    
    # 先頭をデフォルトに設定
    if file_infos:
        file_infos[0]["is_default"] = True

    return file_infos

# ----------------------
# データセットロード
# ----------------------
def load_dataset_by_id(dataset_id):
    """ 指定IDのデータセットをロードしてグローバル変数にセット """
    global DATASET, QM_DICT, ACTIVE_DATASET_ID

    info = next((f for f in DATASET_FILES if f["id"] == dataset_id), None)
    if not info:
        raise ValueError(f"dataset_id='{dataset_id}' not found.")

    path = info["path"]
    print(f"[LOAD] データセット読み込み中: {path}")

    # inf_learn の load_dataset を使用 (閾値は任意調整。ここでは10)
    ds = logic.load_dataset(dataset_path=path, min_feature_threshold=10)
    if not ds:
        raise RuntimeError("有効なデータがありません（閾値不足の可能性あり）。")

    # 質問マップ生成 (カテゴリ選択はNoneで全自動生成させる)
    qm = logic.generate_question_map(ds, selected_categories=None)

    DATASET = ds
    QM_DICT = qm
    ACTIVE_DATASET_ID = dataset_id
    
    print(f"[LOAD] 完了: {len(DATASET)}人, 質問タイプ数={sum(len(v) for v in QM_DICT.values())}")

# 起動時にスキャン実行
DATASET_FILES = scan_dataset_files()
DEFAULT_DATASET_ID = DATASET_FILES[0]["id"] if DATASET_FILES else None

# =======================
# ルーティング
# =======================

@app.route("/") # フロントエンド配信
# ----------------------
# インデックス配信
# ----------------------
def serve_index():
    return send_from_directory(".", "index.html")

@app.route("/datasets", methods=["GET"]) # データセット一覧取得
# ----------------------
# データセット一覧取得
# ----------------------
def list_datasets():
    """ フロントエンドへデータセット一覧を返す """
    return jsonify({"datasets": DATASET_FILES})

@app.route("/start", methods=["POST"]) # 新規セッション開始
# ----------------------
# セッション開始処理
# ----------------------
def start_session():
    """ 新規セッション開始 """
    if not DATASET_FILES:
        return jsonify({"error": "データセットファイルがありません。"}), 500

    req = request.get_json(silent=True) or {}
    dataset_id = req.get("dataset_id") or DEFAULT_DATASET_ID

    try:
        # 違うデータセットがリクエストされたらロードし直す
        if dataset_id != ACTIVE_DATASET_ID:
            load_dataset_by_id(dataset_id)
    except Exception as e:
        print(f"[ERROR] Load failed: {e}")
        return jsonify({"error": str(e)}), 500

    # セッション初期化
    session["candidates"] = DATASET[:]  # 全員候補
    session["asked_keys"] = []          # 質問済みキーリスト
    session["steps"] = 0                # ステップ数
    session["dataset_id"] = dataset_id  # 使用データセットID
    session["history_stack"] = []       # Undo用スタック
    session["user_answers_log"] = {}    # 回答履歴（学習用）
    session["recovery_count"] = 0       # リカバリー回数

    # 最初の質問を取得
    return jsonify(find_next_action())  # 初回質問を返す

@app.route("/answer", methods=["POST"]) # ユーザー回答処理
# ----------------------
# ユーザー回答処理
# ----------------------
def handle_answer():
    data = request.json or {}
    answer = data.get("answer")       # yes, no, dont_know, reject_candidates
    person_name = data.get("person_name")
    session.setdefault("saved_people", [])
    q_key = data.get("question_key")

    # セッション情報の取得
    candidates = session.get("candidates", [])
    asked_keys = session.get("asked_keys", [])
    steps = session.get("steps", 0)
    user_answers = session.get("user_answers_log", {}) # 回答履歴

    # リスト全拒否＆リカバリー要求の処理
    if answer == "reject_candidates":
        print("[RECOVERY] 候補リストが拒否されました。リカバリーを試みます。")
        
        # 1. 現在のリカバリー回数をチェック（無限ループ防止のため最大3回までとか）
        recovery_count = session.get("recovery_count", 0)
        
        if recovery_count >= 3:
            # 3回やってもダメなら、本当に諦める（降参画面へ）
            return jsonify({
                "type": "guess",
                "name": "該当する人物が見つかりませんでした", # これで降参画面が出る
                "confidence": 0,
                "stats": {"candidates_count": 0, "steps": steps}
            })

        # 2. 全データからニアミス（不一致3つ以内）を探す
        near_misses = []
        # YES/NOの形式を inf_learn 用に合わせる ("yes"->"y")
        formatted_answers = {k: ("y" if v=="yes" else "n") for k, v in user_answers.items()}

        for person in DATASET:
            # inf_learnの関数で不一致数を計算
            miss_count = logic.calculate_mismatches(person, formatted_answers)
            if miss_count <= 3:
                near_misses.append(person)
        
        # 直前に提示していた候補（candidates）は、今回のニアミスリストから除外する
        rejected_names = {p["name"] for p in candidates}
        near_misses = [p for p in near_misses if p["name"] not in rejected_names]

        # 3. 結果判定
        if near_misses:
            print(f"[RECOVERY] 成功: {len(near_misses)} 名が復活しました。")
            
            # セッション更新
            session["candidates"] = near_misses
            session["recovery_count"] = recovery_count + 1
            
            # 次の質問を探して返す
            next_action = find_next_action()
            next_action["recovery_message"] = f"条件を緩和して、{len(near_misses)}名を再候補にしました！\n質問を続けます。"
            return jsonify(next_action)
        
        else:
            print("[RECOVERY] 失敗: 復活できる候補がいません。")
            # 復活できなければ降参
            return jsonify({
                "type": "guess",
                "name": "該当する人物が見つかりませんでした",
                "confidence": 0,
                "stats": {"candidates_count": 0, "steps": steps}
            })


    # 回答履歴を保存する
    if q_key and answer in ("yes", "no"):
        user_log = session.get("user_answers_log", {})
        user_log[q_key] = answer  # "yes" or "no"
        session["user_answers_log"] = user_log

    # 特殊選択 (候補カードからの直接選択)
    if answer == "force_choose":
    # 対応する人を探す
        for p in candidates:
            if p["name"] == person_name:
            # 画像取得
                image_url = None
            try:
                image_url = logic.get_wikipedia_main_image(person_name)
            except: pass

            return jsonify({
                "type": "guess",
                "name": person_name,
                "image_url": image_url,
                "confidence": 100,
                "stats": {
                    "candidates_count": 1,
                    "steps": session.get("steps"),
                    "dataset_id": session.get("dataset_id")
                }
            })
        
    """ 回答を受け取り、候補を絞り込む（NO で候補一覧に戻る仕様込み） """
    # --- 1) すでに候補1人で、NOが押された場合 ---
    if answer == "no" and len(candidates) == 1:
        prev_list = session.get("prev_candidates_before_guess")
        if prev_list:
            return jsonify({
                "type": "candidates_list",
                "candidates": prev_list,
                "stats": {
                    "candidates_count": len(prev_list),
                    "steps": steps,               # ★Stepは増加させない
                    "dataset_id": session.get("dataset_id")
                }
            })

    # --- Undo用: 状態保存 ---
    save_state_for_undo(candidates[:], asked_keys[:], steps, current_q_key=q_key)

    # --- 2) 絞り込みロジック ---
    if answer == "no" and not q_key:
        candidates = []

    # yes / no による絞り込み
    if answer in ("yes", "no") and q_key:
        new_candidates = []
        for person in candidates:
            has_feature = (person.get("features", {}).get(q_key) == 1)
            if answer == "yes" and has_feature:
                new_candidates.append(person)
            elif answer == "no" and not has_feature:
                new_candidates.append(person)
        candidates = new_candidates
        session["prev_candidates_before_guess"] = session.get("candidates", [])[:]

    # dont_know → 絞り込まない

    # --- 質問キー追加 ---
    if q_key and q_key not in asked_keys:
        asked_keys.append(q_key)

    # --- セッション更新 (★候補1人になった瞬間用) ---
    prev_len = session.get("prev_candidates_len", len(candidates))
    if prev_len > 1 and len(candidates) == 1:
        session["prev_candidates_before_guess"] = session.get("candidates", [])[:]
    session["prev_candidates_len"] = len(candidates)

    session["candidates"] = candidates
    session["asked_keys"] = asked_keys

    # --- 3) 推測中（1人）になったらステップを増やさない ---
    if len(candidates) == 1:
        session["steps"] = steps  # ★ステップ固定
    else:
        session["steps"] = steps + 1

    return jsonify(find_next_action())

@app.route("/undo", methods=["POST"]) # ユーザーの「1つ前に戻る」要求
# ----------------------
# Undo処理
# ----------------------
def undo_last():
    """ 1つ前の状態に戻す """
    stack = session.get("history_stack", [])
    if not stack:
        return jsonify(find_next_action()) # 戻れない場合は現状維持

    prev_state = stack.pop() # 最新履歴を取り出す
    session["candidates"] = prev_state["candidates"]
    session["asked_keys"] = prev_state["asked_keys"]
    session["steps"] = prev_state["steps"]
    session["history_stack"] = stack # 更新したスタックを保存

    # ★修正: 復元する質問キーがあれば、それを強制的に使う
    restored_q_key = prev_state.get("question_key")
    
    # 統計情報作成
    stats = {
        "candidates_count": len(prev_state["candidates"]),
        "steps": prev_state["steps"],
        "dataset_id": session.get("dataset_id")
    }

    if restored_q_key:
        print(f"[UNDO] 質問を復元します: {restored_q_key}")
        # キーからテキストを探す
        q_text = find_text_by_key(restored_q_key)
        if q_text:
            return jsonify({
                "type": "question",
                "text": q_text,
                "key": restored_q_key,
                "stats": stats,
                "is_undo": True
            })

    # もしキー情報がない場合（初回など）は通常通り計算
    res = find_next_action()
    res["is_undo"] = True
    return jsonify(res)

# =======================
# ロジック補助
# =======================

def save_state_for_undo(candidates, asked_keys, steps, current_q_key):
    """ 現在のセッション状態を履歴スタックに積む """
    stack = session.get("history_stack", [])
    current = {
        "candidates": list(candidates), # 明示的にリストコピー
        "asked_keys": list(asked_keys),
        "steps": steps,
        "question_key": current_q_key  # ★保存項目に追加
    }
    stack.append(current)
    # メモリ節約のため履歴は最大20件まで
    if len(stack) > 20: stack.pop(0)
    session["history_stack"] = stack

def find_text_by_key(key):
    """ QM_DICTからキーに対応する質問文を探す """
    # QM_DICT = { "occupation": [q1, q2...], "activity": [...] }
    for cat_list in QM_DICT.values():
        for q in cat_list:
            if q["key"] == key:
                return q["text"]
    return None

def find_next_action():
    """ 次の質問 または 推測結果 を返す """
    candidates = session.get("candidates", [])
    asked_keys = session.get("asked_keys", [])
    
    dataset_id = session.get("dataset_id")

     # --- NEW: 候補が1人になる直前の状態を保存 ---
    prev_len = session.get("prev_candidates_len", len(candidates))
    if prev_len > 1 and len(candidates) == 1:
        # 1人になる直前の候補一覧を保存
        session["prev_candidates_before_guess"] = session["candidates"][:]  
    session["prev_candidates_len"] = len(candidates)
    
    # 統計情報
    stats = {
        "candidates_count": len(candidates),
        "steps": session.get("steps", 0),
        "dataset_id": dataset_id
    }

    # 1. 候補が1人 → 推測 (画像取得)
    if len(candidates) == 1:
        person = candidates[0]
        name = person["name"]
        
        print(f"[GUESS] 確定: {name} (画像取得中...)")
        
        # 画像取得ロジック
        image_url = None
        try:
            image_url = logic.get_wikipedia_main_image(name)
        except Exception as e:
            print(f"画像取得エラー: {e}")

        return {
            "type": "guess",
            "name": name,
            "image_url": image_url,
            "source_url": f"https://ja.wikipedia.org/wiki/{name}",
            "confidence": 100,
            "stats": stats
        }

    # 2. 候補が0人
    if len(candidates) == 0:
        return {
            "type": "guess",
            "name": "該当する人物が見つかりませんでした",
            "image_url": None,
            "confidence": 0,
            "stats": stats
        }

    # 3. 質問を探す
    asked_set = set(asked_keys)
    question = logic.find_best_question(candidates, QM_DICT, asked_set)

    if question:
        return {
            "type": "question",
            "text": question["text"],
            "key": question["key"],
            "stats": stats
        }
    
    # 4. 質問が尽きたが複数人いる場合 → 最も可能性が高い人（先頭）を推測
    top_person = candidates[0]
    print(f"[GUESS] 暫定: {top_person['name']}")
    
    image_url = None
    try:
        image_url = logic.get_wikipedia_main_image(top_person['name'])
    except: pass

    return {
        "type": "guess",
        "name": top_person["name"],
        "image_url": image_url,
        "source_url": f"https://ja.wikipedia.org/wiki/{name}", #追加
        "confidence": int(100 / len(candidates)),
        "stats": stats
    }

@app.route("/add_person", methods=["POST"]) # 新しい人物を学習させるAPI
# ----------------------
# 新規学習処理
# ----------------------
def add_new_person():
    """ 新しい人物を学習させるAPI """
    data = request.json or {}
    name = data.get("name")
    dataset_id = session.get("dataset_id")

    if not name:
        return jsonify({"error": "名前が空です"}), 400

    # 現在使っているデータセットのパスを特定
    info = next((f for f in DATASET_FILES if f["id"] == dataset_id), None)
    if not info:
        return jsonify({"error": "データセットが見つかりません"}), 500

    path = info["path"]

    # 直前のセッションでユーザーが答えた内容を取得する
    # 「そのゲーム中にYESと答えた特徴」を学習に反映させるロジック
    
    # history_stackの一番新しいものから「YES」と答えた質問キーを抽出
    stack = session.get("history_stack", [])
    user_feedback_features = {}
    
    # スタックや現在の状態から、YES/NOの情報を集める

    user_answers_log = session.get("user_answers_log", {})  # ★後述の修正でこれを作ります

    print(f"[LEARN] 新規学習開始: {name} （ユーザー補正あり）-> {path}")

    # inf_learn.py の機能を使って追加
    try:
        logic.fetch_and_add_new_person_data(name, dataset_path=path, user_feedback=user_answers_log)

        # メモリ上のデータセットもリロードして即反映させる
        load_dataset_by_id(dataset_id) 
        
        return jsonify({"success": True, "message": f"『{name}』をデータセットに追加しました！"})
    except Exception as e:
        print(f"[ERROR] 学習失敗: {e}")
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    if not os.path.exists("./flask_session"):
        os.makedirs("./flask_session")
    
    print("=== Server Started ===")
    app.run(debug=True, port=5000, use_reloader=False)