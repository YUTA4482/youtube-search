from flask import Flask, render_template, request, jsonify
from googleapiclient.errors import HttpError
from youtube_client import search_videos

app = Flask(__name__)


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/search", methods=["POST"])
def search():
    data = request.get_json(force=True)
    query = (data.get("query") or "").strip()
    max_results = int(data.get("max_results", 10))
    period = data.get("period", "all")

    if not query:
        return jsonify({"error": "検索ワードを入力してください。"}), 400

    try:
        results = search_videos(query, max_results, period)
    except ValueError as e:
        return jsonify({"error": str(e)}), 500
    except HttpError as e:
        reason = e.error_details[0].get("reason", "") if e.error_details else ""
        if "quotaExceeded" in reason or e.status_code == 403:
            return jsonify({"error": "APIクォータを超過しました。しばらく時間をおいてから再試行してください。"}), 429
        return jsonify({"error": f"YouTube API エラー: {e.reason}"}), 502
    except Exception as e:
        return jsonify({"error": f"予期しないエラーが発生しました: {str(e)}"}), 500

    if not results:
        return jsonify({"results": [], "message": "該当する動画が見つかりませんでした。"})

    return jsonify({"results": results})


if __name__ == "__main__":
    app.run(debug=True)
