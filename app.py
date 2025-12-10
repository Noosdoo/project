import os
import uuid
import logging
from flask import Flask, request, jsonify, session
from flask_cors import CORS
from flask_session import Session

# ★ 先ほどの長いコードを inf_learn.py として保存し、ここでインポートします
import inf_learn as logic

app = Flask(__name__)
CORS(app, supports_credentials=True)

# セッション設定
app.config["SECRET_KEY"] = "super-dynamic-akinator-key"
app.config["SESSION_TYPE"] = "filesystem"
app.config["SESSION_FILE_DIR"] = "./flask_session"
Session(app)

# ログ設定
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ==========================================
# グローバルキャッシュ (データセットの再読み込み負荷を下げるため)
# ==========================================
# 構造: { "dataset_path": { "data": [人物リスト], "qm": {質問マップ} } }
DATASET_CACHE = {}

def get_cached_dataset_and_qm(categories):
    """
    カテゴリに基づいてデータセットパスを特定し、
    キャッシュにあればそれを、なければロード/構築して返す
    """
    # 1. パスを特定
    # inf_learnの関数を使ってパスを取得
    list_path = logic.get_dynamic_cache_path(categories, prefix="people_list")
    dataset_path = logic.get_dynamic_cache_path(categories, prefix="people_dataset")

    # キャッシュヒット確認
    if dataset_path in DATASET_CACHE:
        return dataset_path, DATASET_CACHE[dataset_path]["data"], DATASET_CACHE[dataset_path]["qm"]

    # 2. データセットが存在しない場合 -> エラー (Webからはcollect/buildは重すぎるため)
    if not os.path.exists(dataset_path):
        # 簡易対応: 存在しない場合はデモ用などのフォールバックロジックを入れるか、エラーを返す
        # ここでは「データがありません」として返す
        return dataset_path, None, None

    # 3. ロード
    logger.info(f"データセットをロード中... {dataset_path}")
    # inf_learn の load_dataset を使用 (閾値は main の設定に合わせる)
    ds = logic.load_dataset(dataset_path, min_feature_threshold=15)
    
    if not ds:
        return dataset_path, None, None

    # 4. 質問マップ生成 (これが重いのでキャッシュする)
    logger.info("質問マップを生成中...")
    qm = logic.generate_question_map(ds, selected_categories=categories)

    # 5. キャッシュに保存
    DATASET_CACHE[dataset_path] = {
        "data": ds,
        "qm": qm
    }
    
    return dataset_path, ds, qm

# ==========================================
# API エンドポイント
# ==========================================

@app.route('/categories', methods=['GET'])
def get_categories():
    """利用可能なカテゴリ一覧を返す"""
    return jsonify({
        "categories": logic.CATEGORIES
    })

@app.route('/start', methods=['POST'])
def start_game():
    """ゲーム開始"""
    data = request.json or {}
    
    # フロントエンドから送られてきたカテゴリリスト (なければ全カテゴリ)
    selected_cats = data.get('categories', logic.CATEGORIES)
    if not selected_cats:
        selected_cats = logic.CATEGORIES

    # データセットの準備
    path, ds, qm = get_cached_dataset_and_qm(selected_cats)

    if ds is None:
        return jsonify({
            "type": "error",
            "message": "データセットが見つかりません。先にローカルで python inf_learn.py を実行してデータを収集してください。",
            "path": path
        }), 404

    # セッション初期化
    session['sid'] = str(uuid.uuid4())[:8]
    session['dataset_path'] = path
    session['categories'] = selected_cats
    # 候補者リスト (最初は全員)
    session['candidates'] = ds
    # 質問済みキー
    session['asked_keys'] = []
    session['steps'] = 0
    # 履歴 (Undo用)
    session['history'] = []

    # 最初の質問を決める
    # inf_learn の find_best_question を使用
    question = logic.find_best_question(ds, qm, [])
    
    if not question:
        return jsonify({"type": "error", "message": "有効な質問が見つかりませんでした。"}), 500

    return jsonify({
        "type": "question",
        "question_text": question["text"],
        "question_key": question["key"],
        "session_data": {"steps": 0, "candidates_count": len(ds)}
    })

@app.route('/answer', methods=['POST'])
def answer_question():
    """回答処理"""
    data = request.json or {}
    answer = data.get('answer')       # yes, no, dont_know
    question_key = data.get('question_key')

    # セッションから復元
    current_candidates = session.get('candidates', [])
    asked_keys = session.get('asked_keys', [])
    steps = session.get('steps', 0)
    dataset_path = session.get('dataset_path')
    
    # キャッシュから質問マップを取得 (lambda関数が含まれるためセッションには保存できない)
    if dataset_path in DATASET_CACHE:
        qm = DATASET_CACHE[dataset_path]["qm"]
    else:
        # キャッシュ切れの場合は再ロード
        _, _, qm = get_cached_dataset_and_qm(session.get('categories', []))

    # ---------------------------
    # 履歴保存 (Undo用)
    # ---------------------------
    session['history'].append({
        'candidates': current_candidates,
        'asked_keys': asked_keys,
        'steps': steps
    })

    # ---------------------------
    # 候補の絞り込み (inf_learnロジックの簡易再現)
    # ---------------------------
    # logic.py の find_best_question は "check" 関数を持っていますが、
    # ここでは単純に features 辞書を見て判定します
    
    new_candidates = []
    
    if answer == "dont_know":
        # 「わからない」場合は全員残す（inf_learnの仕様）
        new_candidates = current_candidates
    else:
        target_val = 1 if answer == "yes" else 0
        
        for person in current_candidates:
            # 特徴を持っているか (1 or None/0)
            has_feature = person.get("features", {}).get(question_key) == 1
            
            # YESと答えた -> 特徴を持っている人を残す
            if answer == "yes" and has_feature:
                new_candidates.append(person)
            # NOと答えた -> 特徴を持っていない人を残す
            elif answer == "no" and not has_feature:
                new_candidates.append(person)

    # 状態更新
    session['candidates'] = new_candidates
    if question_key:
        asked_keys.append(question_key)
    session['asked_keys'] = asked_keys
    session['steps'] = steps + 1
    
    # ---------------------------
    # 次のアクション判定
    # ---------------------------
    
    # 1. 候補が1人になった -> 推測
    if len(new_candidates) == 1:
        winner = new_candidates[0]
        # 画像取得 (inf_learnの関数利用)
        img_url = logic.get_wikipedia_main_image(winner['name'])
        
        return jsonify({
            "type": "guess",
            "name": winner['name'],
            "image": img_url,
            "confidence": 100,
            "session_data": {"steps": session['steps'], "candidates_count": 1}
        })

    # 2. 候補が0人になった -> ギブアップ
    elif len(new_candidates) == 0:
        return jsonify({
            "type": "guess",
            "name": "該当なし（わかりませんでした）",
            "image": None,
            "confidence": 0,
            "session_data": {"steps": session['steps'], "candidates_count": 0}
        })

    # 3. まだ候補がいる -> 次の質問
    else:
        # 次の質問を探す
        next_q = logic.find_best_question(new_candidates, qm, asked_keys)
        
        # 質問切れのケース
        if next_q is None:
            # 最も可能性が高い人（リストの先頭）を推測
            winner = new_candidates[0]
            img_url = logic.get_wikipedia_main_image(winner['name'])
            return jsonify({
                "type": "guess",
                "name": winner['name'] + " (質問切れ)",
                "image": img_url,
                "confidence": int(100/len(new_candidates)),
                "session_data": {"steps": session['steps'], "candidates_count": len(new_candidates)}
            })

        return jsonify({
            "type": "question",
            "question_text": next_q["text"],
            "question_key": next_q["key"],
            "session_data": {"steps": session['steps'], "candidates_count": len(new_candidates)}
        })

@app.route('/undo', methods=['POST'])
def undo_last():
    """1つ戻る"""
    history = session.get('history', [])
    if not history:
        return jsonify({"undo": False})
    
    # 履歴から復元
    last_state = history.pop()
    session['candidates'] = last_state['candidates']
    session['asked_keys'] = last_state['asked_keys']
    session['steps'] = last_state['steps']
    session['history'] = history
    
    # 次の質問を再計算（または直前の状態に戻す）
    # 再計算するためにQMが必要
    dataset_path = session.get('dataset_path')
    if dataset_path in DATASET_CACHE:
        qm = DATASET_CACHE[dataset_path]["qm"]
    else:
        _, _, qm = get_cached_dataset_and_qm(session.get('categories', []))
        
    next_q = logic.find_best_question(session['candidates'], qm, session['asked_keys'])
    
    return jsonify({
        "undo": True,
        "type": "question",
        "question_text": next_q["text"] if next_q else "エラー",
        "question_key": next_q["key"] if next_q else None,
        "session_data": {"steps": session['steps'], "candidates_count": len(session['candidates'])}
    })

@app.route('/submit_correct_answer', methods=['POST'])
def submit_correct_answer():
    """
    推測が外れた場合に、ユーザーから正解を受け取り、データセットに追加学習させる
    """
    data = request.json or {}
    correct_name = data.get('name')
    dataset_path = session.get('dataset_path')

    if not correct_name or not dataset_path:
        return jsonify({"success": False, "message": "名前またはデータセットが無効です"})

    logger.info(f"学習リクエスト: {correct_name} を {dataset_path} に追加します")

    # inf_learn の学習機能を使用
    # この関数はスクレイピングを行い、JSONに追記保存する
    try:
        logic.fetch_and_add_new_person_data(correct_name, dataset_path=dataset_path)
        
        # キャッシュをクリア（次回リロード時に新しいデータを読み込ませるため）
        if dataset_path in DATASET_CACHE:
            del DATASET_CACHE[dataset_path]
            
        return jsonify({"success": True, "message": f"『{correct_name}』を覚えました！次回から登場します。"})
        
    except Exception as e:
        logger.error(f"学習エラー: {e}")
        return jsonify({"success": False, "message": f"学習中にエラーが発生しました: {str(e)}"})

if __name__ == '__main__':
    if not os.path.exists("./flask_session"):
        os.makedirs("./flask_session")
    
    # 初回起動時に Janome などの準備ができるか確認
    if logic.JANOME_TOKENIZER is None:
        print("警告: Janomeがインストールされていないため、動的特徴抽出は動きません。")

    print("=== Server Starting ===")
    app.run(debug=True, port=5000)