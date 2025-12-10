import os
import glob
import random
import time

from flask import Flask, jsonify, request, session, send_from_directory
from flask_cors import CORS
from flask_session import Session

# ---- 本体ロジックをインポート ----
try:
    import test_matsumoto_namae as logic
except ImportError:
    print("エラー: 'test_matsumoto_namae.py' が見つかりません。")
    exit()

app = Flask(__name__)
CORS(app)

# セッション設定
app.secret_key = "my-super-secret-key-for-akinator"
app.config["SESSION_PERMANENT"] = False
app.config["SESSION_TYPE"] = "filesystem"
app.config["SESSION_USE_SIGNER"] = True
app.config["SESSION_FILE_DIR"] = "./flask_session"
Session(app)

# =======================
# データセット管理
# =======================

DATASET_FILES = []   # [{id, path, label, mtime, is_default}, ...]
DEFAULT_DATASET_ID = None

# 実際に使うデータセット（/startで選択したもの）
DATASET = []
QM_DICT = {}
ACTIVE_DATASET_ID = None
ACTIVE_DATASET_PATH = None


def scan_dataset_files():
    """
    people_dataset*.json をいろんな候補ディレクトリから探す。
    探す場所:
      1. app.py があるフォルダ
      2. app.py があるフォルダの matsumoto サブフォルダ
      3. カレントディレクトリ
      4. その matsumoto サブフォルダ
    """
    base_dir = os.path.dirname(os.path.abspath(__file__))
    cwd = os.getcwd()

    search_dirs = [
        base_dir,
        os.path.join(base_dir, "matsumoto"),
        cwd,
        os.path.join(cwd, "matsumoto"),
    ]

    print("=== データセット探索ログ ===")
    print("  app.py の場所  :", base_dir)
    print("  カレントディレクトリ:", cwd)

    found_files = set()

    for d in search_dirs:
        d = os.path.abspath(d)
        if not os.path.isdir(d):
            print(f"  [SKIP] ディレクトリなし: {d}")
            continue

        pattern = os.path.join(d, "people_dataset*.json")
        files = glob.glob(pattern)
        if files:
            print(f"  検索パターン: {pattern}")
            for f in files:
                print("    →", f)
                found_files.add(os.path.abspath(f))

    if not found_files:
        print("  → people_dataset*.json が見つかりませんでした。")
        return []

    # ファイルごとの情報を作成
    file_infos = []
    for idx, path in enumerate(sorted(found_files)):
        mtime = os.path.getmtime(path)
        basename = os.path.basename(path)
        label = os.path.splitext(basename)[0]  # people_dataset_お笑い芸人
        file_infos.append({
            "id": f"ds{idx+1}",
            "path": path,
            "label": label,
            "mtime": mtime,
        })

    # 一番新しいファイルをデフォルトに
    file_infos.sort(key=lambda x: x["mtime"], reverse=True)
    default_id = file_infos[0]["id"]

    for f in file_infos:
        f["is_default"] = (f["id"] == default_id)
        print(f"候補: id={f['id']} label={f['label']} path={f['path']} default={f['is_default']}")

    return file_infos


def load_dataset_by_id(dataset_id):
    """
    指定された dataset_id の JSON を読み込み、DATASET & QM_DICT を更新。
    """
    global DATASET, QM_DICT, ACTIVE_DATASET_ID, ACTIVE_DATASET_PATH

    info = next((f for f in DATASET_FILES if f["id"] == dataset_id), None)
    if not info:
        raise ValueError(f"dataset_id='{dataset_id}' に対応するファイルがありません。")

    path = info["path"]
    print(f"[DATASET] '{info['label']}' ({path}) をロードします。")

    ds = logic.load_dataset(dataset_path=path, min_feature_threshold=10)
    if not ds:
        raise RuntimeError(f"データセットのロードに失敗しました: {path}")

    qm = logic.generate_question_map(ds, selected_categories=None)

    DATASET = ds
    QM_DICT = qm
    ACTIVE_DATASET_ID = dataset_id
    ACTIVE_DATASET_PATH = path

    print(f"[DATASET] ロード完了: {len(DATASET)}件, 質問数 合計={sum(len(v) for v in QM_DICT.values())}")


# 起動時に候補をスキャンだけしておく
DATASET_FILES = scan_dataset_files()
if DATASET_FILES:
    DEFAULT_DATASET_ID = next(f["id"] for f in DATASET_FILES if f.get("is_default"))
    print(f"[INFO] デフォルトの dataset_id: {DEFAULT_DATASET_ID}")
else:
    print("[WARN] 利用可能なデータセットが見つかりません。/start 時にエラーになります。")

# =======================
# HTML配信
# =======================

@app.route("/")
def serve_index():
    return send_from_directory(".", "index.html")


# =======================
# 状態スナップショット（1つ戻る用）
# =======================

def snapshot_state():
    """1つ戻る用に状態を保存するためのスナップショット"""
    return {
        "candidates": session.get("candidates", []),
        "asked_keys": session.get("asked_keys", []),
        "steps": session.get("steps", 0),
        "yes_count": session.get("yes_count", 0),
        "no_count": session.get("no_count", 0),
    }


def restore_state(state):
    """スナップショットからセッション状態を復元"""
    session["candidates"] = state.get("candidates", [])
    session["asked_keys"] = state.get("asked_keys", [])
    session["steps"] = state.get("steps", 0)
    session["yes_count"] = state.get("yes_count", 0)
    session["no_count"] = state.get("no_count", 0)


# =======================
# API エンドポイント
# =======================

@app.route("/datasets", methods=["GET"])
def list_datasets():
    """
    利用可能なデータセット候補一覧を返す。
    """
    if not DATASET_FILES:
        return jsonify({"datasets": []})

    items = []
    for info in DATASET_FILES:
        items.append({
            "id": info["id"],
            "label": info["label"],              # people_dataset_お笑い芸人
            "filename": os.path.basename(info["path"]),
            "mtime": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(info["mtime"])),
            "is_default": info.get("is_default", False),
        })
    return jsonify({"datasets": items})


@app.route("/start", methods=["POST"])
def start_session():
    """
    新しいセッションを開始し、最初の質問を返す。
    リクエストボディに {dataset_id: "..."} を渡すと、そのデータセットを使う。
    省略時はデフォルトのデータセット。
    """
    if not DATASET_FILES:
        return jsonify({"error": "利用可能なデータセットが見つかりません。"}), 500

    req = request.get_json(silent=True) or {}
    dataset_id = req.get("dataset_id") or DEFAULT_DATASET_ID

    try:
        # 必要ならロードし直す
        if dataset_id != ACTIVE_DATASET_ID:
            load_dataset_by_id(dataset_id)
    except Exception as e:
        print(f"[ERROR] /start でデータセットロード失敗: {e}")
        return jsonify({"error": f"データセットのロードに失敗しました: {e}"}), 500

    # セッション状態初期化
    session["candidates"] = DATASET[:]  # データセット全体をコピー
    session["asked_keys"] = []
    session["steps"] = 0
    session["yes_count"] = 0
    session["no_count"] = 0
    session["prev_state"] = None  # 戻る用
    session["dataset_id"] = dataset_id

    print(f"[START] 新規セッション開始。dataset_id={dataset_id}, 候補: {len(session['candidates'])}人")

    question_data = find_next_question()
    # どのデータセットかも返しておくとわかりやすい
    question_data["dataset_id"] = dataset_id
    return jsonify(question_data)


@app.route("/answer", methods=["POST"])
def handle_answer():
    """
    ユーザーの回答を処理し、次の質問または推測を返す。
    """
    if "candidates" not in session:
        print("[ERROR] /answer が呼び出されましたが、セッションに 'candidates' がありません。")
        return jsonify({"error": "セッションが開始されていません。"}), 400

    data = request.json or {}
    answer = data.get("answer")          # 'yes', 'no', 'dont_know'
    current_q_key = data.get("question_key")

    candidates = session.get("candidates", [])
    asked_keys = session.get("asked_keys", [])

    # 回答前の状態を保存（undo 用）
    session["prev_state"] = snapshot_state()

    # 質問キーを既問リストに追加
    if current_q_key and current_q_key not in asked_keys:
        asked_keys.append(current_q_key)

    # 回答に基づき候補を絞り込み
    if answer in ("yes", "no") and current_q_key is not None:
        # 対応する質問オブジェクトを探す
        q_obj = None
        for q_list in QM_DICT.values():
            q_obj = next((q for q in q_list if q["key"] == current_q_key), None)
            if q_obj:
                break

        if q_obj:
            test_func = q_obj["check"]
            if answer == "yes":
                candidates = [c for c in candidates if test_func(c)]
                session["yes_count"] = session.get("yes_count", 0) + 1
            else:
                candidates = [c for c in candidates if not test_func(c)]
                session["no_count"] = session.get("no_count", 0) + 1

            session["candidates"] = candidates

    # 'dont_know' の場合は絞り込まない

    session["steps"] = session.get("steps", 0) + 1
    session["asked_keys"] = asked_keys

    print(f"[ANSWER:{answer}] 候補: {len(candidates)}人")

    response_data = find_next_question()
    response_data["dataset_id"] = session.get("dataset_id")
    return jsonify(response_data)


@app.route("/undo", methods=["POST"])
def undo_last():
    """
    1つ前の状態に戻す。
    """
    prev = session.get("prev_state")
    if not prev:
        print("[UNDO] 戻る状態がありません。現状態をそのまま返します。")
        data = find_next_question()
        data["undo"] = False
        data["dataset_id"] = session.get("dataset_id")
        return jsonify(data)

    print("[UNDO] 1つ前の状態に戻します。")
    restore_state(prev)
    session["prev_state"] = None  # 連続 Undo は不可

    data = find_next_question()
    data["undo"] = True
    data["dataset_id"] = session.get("dataset_id")
    return jsonify(data)


# =======================
# 質問 / 推測ロジック
# =======================

def find_next_question():
    """
    現在のセッション情報に基づき、次の質問または推測結果を構築する。
    """
    candidates = session.get("candidates", [])
    asked_keys = session.get("asked_keys", [])

    # 1. 候補が1人
    if len(candidates) == 1:
        guess = candidates[0]["name"]
        print(f"[GUESS] 確定: {guess}")
        return {
            "type": "guess",
            "name": guess,
            "confidence": 100,
            "candidates_count": 1,
            "session_data": get_session_stats(),
        }

    # 2. 質問を探す
    if candidates and QM_DICT:
        question = logic.find_best_question(candidates, QM_DICT, asked_keys)
    else:
        question = None

    if question:
        return {
            "type": "question",
            "question_text": question["text"],
            "question_key": question["key"],
            "candidates_count": len(candidates),
            "session_data": get_session_stats(),
        }

    # 3. 質問が尽きたが複数候補
    if len(candidates) > 1:
        guess = candidates[0]["name"]
        confidence = (1 / len(candidates)) * 100
        print(f"[GUESS] 暫定: {guess} (候補 {len(candidates)}人)")
        return {
            "type": "guess",
            "name": guess,
            "confidence": confidence,
            "candidates_count": len(candidates),
            "session_data": get_session_stats(),
        }

    # 4. 候補0人
    print("[GUESS] 候補0人")
    return {
        "type": "guess",
        "name": "候補が見つかりませんでした",
        "confidence": 0,
        "candidates_count": 0,
        "session_data": get_session_stats(),
    }


def get_session_stats():
    """フロント用の統計"""
    return {
        "steps": session.get("steps", 0),
        "yes": session.get("yes_count", 0),
        "no": session.get("no_count", 0),
        "sid": request.cookies.get(app.config["SESSION_COOKIE_NAME"], "-")[:8],
    }


if __name__ == "__main__":
    if not os.path.exists(app.config["SESSION_FILE_DIR"]):
        os.makedirs(app.config["SESSION_FILE_DIR"], exist_ok=True)
        print(f"セッション保存フォルダ '{app.config['SESSION_FILE_DIR']}' を作成しました。")

    if not DATASET_FILES:
        print("\n[警告] データセット候補が1つもありません。")
        print("matsumoto/people_dataset_お笑い芸人.json などが存在するか確認してください。")

    app.run(debug=True, use_reloader=False, port=5000)
