import base64
import datetime
import json
import os
import platform
import urllib.request
import matplotlib
import matplotlib.pyplot as plt

# --- 1. マルチOS対応のフォント設定 ---
current_os = platform.system()
if current_os == 'Windows':
  matplotlib.rcParams['font.sans-serif'] = ['Meiryo', 'MS Gothic', 'Yu Gothic']
elif current_os == 'Darwin':  # macOS
  matplotlib.rcParams['font.sans-serif'] = ['Hiragino Sans', 'Apple Gothic']
else:  # Linux / その他
  # Linux環境で一般的な日本語フォント（環境に合わせて調整可能）
  matplotlib.rcParams['font.sans-serif'] = [
      'TakaoPGothic',
      'IPAexGothic',
      'DejaVu Sans',
  ]

matplotlib.rcParams['axes.unicode_minus'] = False

# --- 2. 設定ファイル (config.json) の読み込み ---
CONFIG_FILE = 'config.net.json'  # または 'config.json'


def load_config():
  if not os.path.exists(CONFIG_FILE):
    # 設定ファイルがない場合は雛形を自動作成して終了する（親切設計）
    default_config = {
        "github_token": "your_github_token_here",
        "output_dir": "github_report_output",
    }
    with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
      json.dump(default_config, f, indent=2, ensure_ascii=False)
    print(f"⚠️ '{CONFIG_FILE}' が見つからなかったため、新規作成しました。")
    print(
        f"ファイルを開いて GitHub の Personal Access Token を設定してください。"
    )
    exit(1)

  try:
    with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
      return json.load(f)
  except Exception as e:
    print(f"❌ 設定ファイル '{CONFIG_FILE}' の読み込みに失敗しました: {e}")
    exit(1)


CONFIG = load_config()
TOKEN = CONFIG.get("github_token", "")
OUTPUT_DIR = CONFIG.get("output_dir", "github_report_output")
HISTORY_JSON = os.path.join(OUTPUT_DIR, "all_repositories_stats.json")


def github_api_request(url, token):
  req = urllib.request.Request(
      url,
      headers={
          "Authorization": f"token {token}",
          "User-Agent": "Python-Ultimate-GitHub-Dashboard",
          "Accept": "vnd.github+json",
      },
  )
  try:
    with urllib.request.urlopen(req) as response:
      if response.status == 200:
        return json.loads(response.read().decode("utf-8"))
  except Exception as e:
    return None
  return None


def get_repository_tree(owner, repo_name, default_branch, token):
  url = f"https://api.github.com/repos/{owner}/{repo_name}/git/trees/{default_branch}?recursive=1"
  return github_api_request(url, token)


def analyze_code_content(blob_url, token, filename):
  blob_data = github_api_request(blob_url, token)
  if not blob_data or "content" not in blob_data:
    return None

  try:
    content_bytes = base64.b64decode(blob_data["content"])
    text = content_bytes.decode("utf-8", errors="ignore")
  except Exception:
    return None

  lines = text.splitlines()
  total_lines = len(lines)
  blank_lines = 0
  comment_lines = 0

  ext = filename.split(".")[-1].lower() if "." in filename else ""

  for line in lines:
    stripped = line.strip()
    if not stripped:
      blank_lines += 1
      continue

    if ext in ["py", "sh", "ps1", "yml", "yaml", "rb", "pl"]:
      if stripped.startswith("#"):
        comment_lines += 1
    elif ext in ["js", "ts", "java", "c", "cpp", "cs", "go", "rs", "php", "json"]:
      if stripped.startswith("//") or stripped.startswith("/*"):
        comment_lines += 1
    elif ext in ["html", "xml"]:
      if stripped.startswith("<!--"):
        comment_lines += 1

  code_lines = total_lines - blank_lines - comment_lines

  return {
      "total": total_lines,
      "code": max(0, code_lines),
      "comment": comment_lines,
      "blank": blank_lines,
  }


def main():
  if not TOKEN or TOKEN == "your_github_token_here":
    print("❌ 有効な GitHub Token が設定されていません。")
    print(f"'{CONFIG_FILE}' を編集してトークンを入力してください。")
    return

  os.makedirs(OUTPUT_DIR, exist_ok=True)

  # 1. 過去のダウンロードデータを読み込み
  previous_releases = {}
  if os.path.exists(HISTORY_JSON):
    try:
      with open(HISTORY_JSON, "r", encoding="utf-8") as f:
        old_json = json.load(f)
        for repo_item in old_json.get("all_repositories", []):
          repo_name = repo_item["repository"]
          previous_releases[repo_name] = {}
          for rel in repo_item.get("releases", []):
            tag = rel["tag_name"]
            tag_total = sum(asset["downloads"] for asset in rel.get("assets", []))
            previous_releases[repo_name][tag] = tag_total
    except Exception:
      pass

  repos_url = "https://api.github.com/user/repos?per_page=100"
  print("リポジトリ一覧を取得しています...")
  repos = github_api_request(repos_url, TOKEN)

  if not repos:
    print(
        "リポジトリ情報を取得できませんでした。トークンを確認してください。"
    )
    return

  today_str = datetime.date.today().isoformat()
  grand_total_downloads = 0
  all_stats = {"scan_date": today_str, "all_repositories": []}
  global_languages = {}

  weekdays_count = [0] * 7
  weekday_names = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]

  print(f"\n合計 {len(repos)} 個のリポジトリを総合スキャンします...\n")
  target_extensions = ["py", "ps1", "js", "html", "css", "sh", "bat", "json", "md"]

  primary_owner = ""

  for repo in repos:
    owner = repo["owner"]["login"]
    if not primary_owner:
      primary_owner = owner

    repo_name = repo["name"]
    default_branch = repo.get("default_branch", "main")
    is_private = repo["private"]
    full_repo_name = f"{owner}/{repo_name}"

    print(f"🔍 分析中: {full_repo_name}")

    # A. 使用言語比率
    lang_url = f"https://api.github.com/repos/{owner}/{repo_name}/languages"
    languages = github_api_request(lang_url, TOKEN) or {}
    for lang, bytes_count in languages.items():
      global_languages[lang] = global_languages.get(lang, 0) + bytes_count

    # B. ファイル数 ＆ LOC解析
    tree_data = get_repository_tree(owner, repo_name, default_branch, TOKEN)
    file_count = 0
    dir_count = 0
    repo_loc_stats = {
        "total_lines": 0,
        "code_lines": 0,
        "comment_lines": 0,
        "blank_lines": 0,
    }

    if tree_data and "tree" in tree_data:
      for item in tree_data["tree"]:
        if item["type"] == "tree":
          dir_count += 1
        elif item["type"] == "blob":
          file_count += 1
          filename = item["path"]
          ext = filename.split(".")[-1].lower() if "." in filename else ""
          if ext in target_extensions and "url" in item:
            stats = analyze_code_content(item["url"], TOKEN, filename)
            if stats:
              repo_loc_stats["total_lines"] += stats["total"]
              repo_loc_stats["code_lines"] += stats["code"]
              repo_loc_stats["comment_lines"] += stats["comment"]
              repo_loc_stats["blank_lines"] += stats["blank"]

    # C. コミット履歴
    commits_url = f"https://api.github.com/repos/{owner}/{repo_name}/commits?per_page=100"
    commits = github_api_request(commits_url, TOKEN) or []
    for commit in commits:
      try:
        date_str = (
            commit.get("commit", {}).get("author", {}).get("date", "")
        )
        if date_str:
          dt = datetime.datetime.fromisoformat(date_str.replace("Z", "+00:00"))
          weekdays_count[dt.weekday()] += 1
      except Exception:
        pass

    # D. ダウンロード数 ＆ トレンド
    releases_url = f"https://api.github.com/repos/{owner}/{repo_name}/releases"
    releases = github_api_request(releases_url, TOKEN) or []

    repo_downloads = 0
    repo_releases_data = []
    release_tags = []
    release_downloads = []
    release_diffs = []
    old_repo_tags = previous_releases.get(full_repo_name, {})

    for release in releases:
      tag_name = release.get("tag_name")
      release_name = release.get("name")
      release_assets = []
      tag_dl_sum = 0

      for asset in release.get("assets", []):
        filename = asset.get("name")
        dl_count = asset.get("download_count")
        tag_dl_sum += dl_count
        repo_downloads += dl_count
        grand_total_downloads += dl_count
        release_assets.append({"filename": filename, "downloads": dl_count})

      repo_releases_data.append({
          "tag_name": tag_name,
          "name": release_name,
          "assets": release_assets,
      })

      old_tag_dl = old_repo_tags.get(tag_name, tag_dl_sum)
      diff = tag_dl_sum - old_tag_dl

      release_tags.append(tag_name)
      release_downloads.append(tag_dl_sum)
      release_diffs.append(diff)

    repo_info = {
        "repository": full_repo_name,
        "private": is_private,
        "default_branch": default_branch,
        "file_count": file_count,
        "dir_count": dir_count,
        "languages": languages,
        "loc_stats": repo_loc_stats,
        "releases": repo_releases_data,
    }
    all_stats["all_repositories"].append(repo_info)

    print(f"   └─ 📁 ファイル: {file_count} | 📂 フォルダ: {dir_count}")
    print(
        f"   └─ 📝 純コード行数: {repo_loc_stats['code_lines']} 行"
        f" (コメント: {repo_loc_stats['comment_lines']} 行)"
    )
    print(f"   └─ 📥 総合DL数: {repo_downloads} 回")

    # グラフ生成 1: ダウンロード・トレンドグラフ
    if release_tags:
      fig_width = max(10, len(release_tags) * 0.4)
      plt.figure(figsize=(fig_width, 4.5))
      bars = plt.bar(release_tags, release_downloads, color="#2ca02c")
      plt.xlabel("Release Tags", fontsize=10)
      plt.ylabel("Downloads", fontsize=10)
      plt.title(f"Downloads & Trend: {repo_name}", fontsize=12, fontweight="bold")
      plt.xticks(rotation=45, ha="right")
      for bar, diff in zip(bars, release_diffs):
        height = bar.get_height()
        if height > 0 or diff != 0:
          diff_text = f" +{diff}" if diff > 0 else f" {diff}" if diff < 0 else ""
          plt.text(
              bar.get_x() + bar.get_width() / 2.0,
              height + 0.1,
              f"{int(height)}{diff_text}",
              ha="center",
              va="bottom",
              fontsize=8,
              color="green" if diff > 0 else "black",
          )
      plt.tight_layout()
      plt.savefig(os.path.join(OUTPUT_DIR, f"{repo_name}_trend.png"), dpi=300)
      plt.close()

    # グラフ生成 2: LOC内訳グラフ
    if repo_loc_stats["total_lines"] > 0:
      plt.figure(figsize=(6, 4))
      categories = ["Code", "Comment", "Blank"]
      loc_values = [
          repo_loc_stats["code_lines"],
          repo_loc_stats["comment_lines"],
          repo_loc_stats["blank_lines"],
      ]
      bars = plt.bar(
          categories, loc_values, color=["#1f77b4", "#ff7f0e", "#7f7f7f"]
      )
      plt.ylabel("Lines", fontsize=10)
      plt.title(f"LOC Breakdown: {repo_name}", fontsize=12, fontweight="bold")
      for bar in bars:
        h = bar.get_height()
        plt.text(
            bar.get_x() + bar.get_width() / 2.0,
            h + 10,
            str(int(h)),
            ha="center",
            va="bottom",
            fontsize=9,
        )
      plt.tight_layout()
      plt.savefig(os.path.join(OUTPUT_DIR, f"{repo_name}_loc.png"), dpi=300)
      plt.close()

    # グラフ生成 3: 言語比率円グラフ
    if languages:
      plt.figure(figsize=(6, 6))
      plt.pie(
          list(languages.values()),
          labels=list(languages.keys()),
          autopct="%1.1f%%",
          startangle=140,
          colors=plt.cm.Set3.colors,
      )
      plt.title(f"Language Share: {repo_name}", fontsize=12, fontweight="bold")
      plt.tight_layout()
      plt.savefig(os.path.join(OUTPUT_DIR, f"{repo_name}_languages.png"), dpi=300)
      plt.close()

    print()

  # 全体の言語比率グラフ
  if global_languages:
    plt.figure(figsize=(7, 7))
    plt.pie(
        list(global_languages.values()),
        labels=list(global_languages.keys()),
        autopct="%1.1f%%",
        startangle=140,
        colors=plt.cm.Paired.colors,
    )
    plt.title(
        "Overall Language Share (All Repositories)",
        fontsize=13,
        fontweight="bold",
    )
    plt.tight_layout()
    plt.savefig(os.path.join(OUTPUT_DIR, "overall_languages.png"), dpi=300)
    plt.close()

  # 曜日別コミット活動パターン
  plt.figure(figsize=(7, 4))
  bars = plt.bar(weekday_names, weekdays_count, color="#1f77b4")
  plt.xlabel("Day of Week", fontsize=10)
  plt.ylabel("Commit Count", fontsize=10)
  plt.title(
      "Coding Activity Pattern by Day of Week", fontsize=12, fontweight="bold"
  )
  for bar in bars:
    h = bar.get_height()
    if h > 0:
      plt.text(
          bar.get_x() + bar.get_width() / 2.0,
          h + 0.1,
          str(int(h)),
          ha="center",
          va="bottom",
          fontsize=9,
      )
  plt.tight_layout()
  plt.savefig(os.path.join(OUTPUT_DIR, "coding_activity_weekly.png"), dpi=300)
  plt.close()

  # 総合JSON保存
  with open(HISTORY_JSON, "w", encoding="utf-8") as f:
    json.dump(all_stats, f, ensure_ascii=False, indent=2)

  # --- HTML生成 ---
  html_content = f"""<!DOCTYPE html>
<html lang="ja">
<head>
    <meta charset="UTF-8">
    <title>GitHub Dashboard - {primary_owner}</title>
    <style>
        body {{ font-family: 'Meiryo', 'Segoe UI', sans-serif; background: #f4f6f9; margin: 0; padding: 20px; color: #333; }}
        h1 {{ text-align: center; color: #2c3e50; }}
        h1 a {{ color: #2c3e50; text-decoration: none; }}
        h1 a:hover {{ color: #3498db; text-decoration: underline; }}
        .summary-box {{ text-align: center; margin-bottom: 20px; font-size: 1.1em; color: #555; }}
        .tabs {{ display: flex; justify-content: center; background: #2c3e50; border-radius: 8px 8px 0 0; overflow: hidden; }}
        .tab-btn {{ background: inherit; border: none; outline: none; cursor: pointer; padding: 14px 20px; font-size: 16px; color: #bdc3c7; transition: 0.3s; font-weight: bold; }}
        .tab-btn:hover {{ background: #34495e; color: #fff; }}
        .tab-btn.active {{ background: #fff; color: #2c3e50; border-top: 3px solid #3498db; }}
        .tab-content {{ display: none; background: #fff; padding: 25px; border-radius: 0 0 8px 8px; box-shadow: 0 4px 6px rgba(0,0,0,0.05); }}
        .tab-content.active {{ display: block; }}
        .grid-container {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(450px, 1fr)); gap: 20px; margin-top: 20px; }}
        .card {{ background: #fafafa; border: 1px solid #e1e4e8; border-radius: 6px; padding: 15px; text-align: center; box-shadow: 0 2px 4px rgba(0,0,0,0.02); }}
        .card h3 {{ margin-top: 0; font-size: 1.1em; }}
        .card h3 a {{ color: #0366d6; text-decoration: none; }}
        .card h3 a:hover {{ text-decoration: underline; }}
        img {{ max-width: 100%; height: auto; border-radius: 4px; }}
        .global-section {{ text-align: center; margin-bottom: 30px; }}
    </style>
    <script>
        function openTab(evt, tabName) {{
            let contents = document.getElementsByClassName("tab-content");
            for (let c of contents) c.classList.remove("active");
            let buttons = document.getElementsByClassName("tab-btn");
            for (let b of buttons) b.classList.remove("active");
            document.getElementById(tabName).classList.add("active");
            evt.currentTarget.classList.add("active");
        }}
    </script>
</head>
<body>

    <h1><a href="https://github.com/{primary_owner}" target="_blank" title="GitHubプロフィールを開く">🚀 {primary_owner} GitHub Dashboard</a></h1>
    <div class="summary-box">
        スキャン日時: {today_str} | 総合ダウンロード数: <b>{grand_total_downloads} 回</b>
    </div>

    <div class="tabs">
        <button class="tab-btn active" onclick="openTab(event, 'tab-downloads')">📊 ダウンロード・トレンド</button>
        <button class="tab-btn" onclick="openTab(event, 'tab-loc')">📝 コード規模 (LOC・コメント)</button>
        <button class="tab-btn" onclick="openTab(event, 'tab-languages')">💻 言語比率</button>
        <button class="tab-btn" onclick="openTab(event, 'tab-activity')">📅 活動パターン</button>
    </div>

    <div id="tab-downloads" class="tab-content active">
        <h2>リポジトリ別 ダウンロード数 ＆ 前回比トレンド</h2>
        <div class="grid-container">
"""

  for repo in all_stats["all_repositories"]:
    repo_full = repo["repository"]
    repo_name = repo_full.split("/")[1]
    repo_url = f"https://github.com/{repo_full}"
    if repo["releases"]:
      html_content += f"""
            <div class="card">
                <h3><a href="{repo_url}" target="_blank">{repo_full}</a></h3>
                <img src="{repo_name}_trend.png" alt="{repo_name} trend">
            </div>
"""

  html_content += """
        </div>
    </div>

    <div id="tab-loc" class="tab-content">
        <h2>コード行数（LOC）とコメント内訳</h2>
        <div class="grid-container">
"""

  for repo in all_stats["all_repositories"]:
    repo_full = repo["repository"]
    repo_name = repo_full.split("/")[1]
    repo_url = f"https://github.com/{repo_full}"
    if repo["loc_stats"]["total_lines"] > 0:
      html_content += f"""
            <div class="card">
                <h3><a href="{repo_url}" target="_blank">{repo_full}</a><br><small style="font-size:0.8em; color:#666;">(コード: {repo['loc_stats']['code_lines']}行 / コメント: {repo['loc_stats']['comment_lines']}行)</small></h3>
                <img src="{repo_name}_loc.png" alt="{repo_name} loc">
            </div>
"""

  html_content += """
        </div>
    </div>

    <div id="tab-languages" class="tab-content">
        <h2>使用言語比率（全体 ＆ リポジトリ別）</h2>
        <div class="global-section">
            <h3>🌍 全リポジトリ合算の言語比率</h3>
            <img src="overall_languages.png" alt="Overall Languages" style="max-width: 450px;">
        </div>
        <hr style="border:0; border-top:1px solid #eee; margin:20px 0;">
        <div class="grid-container">
"""

  for repo in all_stats["all_repositories"]:
    repo_full = repo["repository"]
    repo_name = repo_full.split("/")[1]
    repo_url = f"https://github.com/{repo_full}"
    if repo["languages"]:
      html_content += f"""
            <div class="card">
                <h3><a href="{repo_url}" target="_blank">{repo_full}</a></h3>
                <img src="{repo_name}_languages.png" alt="{repo_name} languages">
            </div>
"""

  html_content += """
        </div>
    </div>

    <div id="tab-activity" class="tab-content" style="text-align: center;">
        <h2>曜日別 コミット活動パターン</h2>
        <p>一週間のうち、どの曜日にコードを多く書いているかの傾向</p>
        <img src="coding_activity_weekly.png" alt="Coding Activity" style="max-width: 650px; margin-top: 15px;">
    </div>

</body>
</html>
"""

  html_path = os.path.join(OUTPUT_DIR, "index.html")
  with open(html_path, "w", encoding="utf-8") as f:
    f.write(html_content)

  print("========================================")
  print(f" 💾 全データとレポートが '{OUTPUT_DIR}/' フォルダに保存されました。")
  print(
      f" 🌐 ブラウザで '{OUTPUT_DIR}/index.html' を開くとダッシュボードが見られます！"
  )
  print("========================================")


if __name__ == "__main__":
  main()