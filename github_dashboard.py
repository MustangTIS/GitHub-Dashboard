import base64
import datetime
import json
import os
import re
import urllib.request

# --- 1. 設定ファイル (config.net.json) の読み込み ---
CONFIG_FILE = "config.net.json"  # または "config.json"


def load_config():
  if not os.path.exists(CONFIG_FILE):
    default_config = {
        "github_token": "your_github_token_here",
        "output_dir": "github_report_output",
    }
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
      json.dump(default_config, f, indent=2, ensure_ascii=False)
    print(f"⚠️ '{CONFIG_FILE}' が見つからなかったため、新規作成しました。")
    print(
        "ファイルを開いて GitHub の Personal Access Token を設定してください。"
    )
    exit(1)

  try:
    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
      return json.load(f)
  except Exception as e:
    print(f"❌ 設定ファイル '{CONFIG_FILE}' の読み込みに失敗しました: {e}")
    exit(1)


CONFIG = load_config()
TOKEN = CONFIG.get("github_token", "")
OUTPUT_DIR = CONFIG.get("output_dir", "github_report_output")
HISTORY_JSON = os.path.join(OUTPUT_DIR, "all_repositories_stats.json")


def safe_id(name: str) -> str:
  return re.sub(r"[^a-zA-Z0-9_]", "_", name)


def escape_html(text: str) -> str:
  if not text:
    return ""
  return (
      str(text)
      .replace("&", "&amp;")
      .replace("<", "&lt;")
      .replace(">", "&gt;")
      .replace('"', "&quot;")
  )


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
  except Exception:
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
  local_tz = datetime.datetime.now().astimezone().tzinfo

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
  grand_total_code_lines = 0
  grand_total_comment_lines = 0
  grand_total_commits = 0

  all_stats = {"scan_date": today_str, "all_repositories": []}
  global_languages = {}

  weekdays_count = [0] * 7
  weekday_names = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
  hours_count = [0] * 24
  hour_labels = [f"{h:02d}h" for h in range(24)]

  print(f"\n合計 {len(repos)} 個のリポジトリを総合スキャンします...\n")
  target_extensions = ["py", "ps1", "js", "html", "css", "sh", "bat", "json", "md"]

  primary_owner = ""

  for repo in repos:
    owner = repo["owner"]["login"]
    if not primary_owner:
      primary_owner = owner

    repo_name = repo["name"]
    description = (repo.get("description") or "").strip()
    pushed_at = (repo.get("pushed_at") or "")[:10]
    dom_id = safe_id(f"{owner}_{repo_name}")
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

    grand_total_code_lines += repo_loc_stats["code_lines"]
    grand_total_comment_lines += repo_loc_stats["comment_lines"]

    # C. コミット履歴（曜日別・時間帯別）
    commits_url = f"https://api.github.com/repos/{owner}/{repo_name}/commits?per_page=100"
    commits = github_api_request(commits_url, TOKEN) or []
    grand_total_commits += len(commits)
    for commit in commits:
      try:
        date_str = (
            commit.get("commit", {}).get("author", {}).get("date", "")
        )
        if date_str:
          dt = datetime.datetime.fromisoformat(date_str.replace("Z", "+00:00"))
          if dt.tzinfo is not None:
            dt = dt.astimezone(local_tz)
          weekdays_count[dt.weekday()] += 1
          hours_count[dt.hour] += 1
      except Exception:
        pass

    # D. ダウンロード数 ＆ 累計計算
    releases_url = f"https://api.github.com/repos/{owner}/{repo_name}/releases"
    releases = github_api_request(releases_url, TOKEN) or []

    repo_downloads = 0
    repo_releases_data = []
    release_tags = []
    release_downloads = []
    release_diffs = []
    old_repo_tags = previous_releases.get(full_repo_name, {})

    for release in releases:
      tag_name = release.get("tag_name") or release.get("name") or "untagged"
      release_name = release.get("name")
      release_assets = []
      tag_dl_sum = 0

      for asset in release.get("assets", []):
        filename = asset.get("name")
        dl_count = asset.get("download_count") or 0
        tag_dl_sum += dl_count
        repo_downloads += dl_count
        grand_total_downloads += dl_count
        release_assets.append({"filename": filename, "downloads": dl_count})

      repo_releases_data.append({
          "tag_name": tag_name,
          "name": release_name,
          "tag_total": tag_dl_sum,
          "assets": release_assets,
      })

      old_tag_dl = old_repo_tags.get(tag_name, tag_dl_sum)
      diff = tag_dl_sum - old_tag_dl

      release_tags.append(tag_name)
      release_downloads.append(tag_dl_sum)
      release_diffs.append(diff)

    chrono_tags = list(reversed(release_tags))
    chrono_downloads = list(reversed(release_downloads))
    chrono_diffs = list(reversed(release_diffs))

    cumulative_downloads = []
    running_sum = 0
    for dl in chrono_downloads:
      running_sum += dl
      cumulative_downloads.append(running_sum)

    repo_info = {
        "repository": full_repo_name,
        "repo_name": repo_name,
        "description": description,
        "pushed_at": pushed_at,
        "dom_id": dom_id,
        "private": is_private,
        "default_branch": default_branch,
        "file_count": file_count,
        "dir_count": dir_count,
        "total_downloads": repo_downloads,
        "languages": languages,
        "loc_stats": repo_loc_stats,
        "releases": repo_releases_data,
        "dl_chart": {
            "tags": chrono_tags,
            "per_release": chrono_downloads,
            "cumulative": cumulative_downloads,
            "diffs": chrono_diffs,
        },
    }
    all_stats["all_repositories"].append(repo_info)

    print(f"   └─ 📁 ファイル: {file_count} | 📂 フォルダ: {dir_count}")
    print(
        f"   └─ 📝 純コード行数: {repo_loc_stats['code_lines']} 行"
        f" (コメント: {repo_loc_stats['comment_lines']} 行)"
    )
    print(f"   └─ 📥 総合DL数: {repo_downloads} 回\n")

  all_stats["activity_summary"] = {
      "weekday_names": weekday_names,
      "weekdays_count": weekdays_count,
      "hour_labels": hour_labels,
      "hours_count": hours_count,
  }

  with open(HISTORY_JSON, "w", encoding="utf-8") as f:
    json.dump(all_stats, f, ensure_ascii=False, indent=2)

  repo_count = len(all_stats["all_repositories"])
  dashboard_payload = {
      "primary_owner": primary_owner,
      "scan_date": today_str,
      "global_languages": global_languages,
      "weekday_names": weekday_names,
      "weekdays_count": weekdays_count,
      "hour_labels": hour_labels,
      "hours_count": hours_count,
      "repositories": all_stats["all_repositories"],
  }
  payload_json = json.dumps(dashboard_payload, ensure_ascii=False).replace(
      "</script>", "<\\/script>"
  )

  # --- HTML生成 ---
  html_content = f"""<!DOCTYPE html>
<html lang="ja">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>GitHub Dashboard - {primary_owner}</title>
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700&family=Noto+Sans+JP:wght@400;500;700&display=swap" rel="stylesheet">
    <script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.3/dist/chart.umd.min.js"></script>
    <style>
        :root {{
            --bg-main: #0f172a;
            --bg-card: #1e293b;
            --bg-card-sub: #162032;
            --bg-card-hover: #243247;
            --border: #334155;
            --text-main: #f1f5f9;
            --text-muted: #94a3b8;
            --accent: #38bdf8;
            --accent-green: #34d399;
            --accent-amber: #fbbf24;
            --accent-purple: #a78bfa;
        }}
        * {{ box-sizing: border-box; }}
        body {{
            font-family: 'Inter', 'Noto Sans JP', -apple-system, BlinkMacSystemFont, sans-serif;
            background: var(--bg-main);
            color: var(--text-main);
            margin: 0;
            padding: 28px 20px 60px;
            line-height: 1.55;
        }}
        .container {{
            max-width: 1280px;
            margin: 0 auto;
        }}
        header {{
            display: flex;
            flex-wrap: wrap;
            justify-content: space-between;
            align-items: center;
            gap: 12px;
            margin-bottom: 22px;
            padding-bottom: 16px;
            border-bottom: 1px solid var(--border);
        }}
        h1 {{
            margin: 0;
            font-size: 1.5rem;
            font-weight: 700;
            letter-spacing: -0.02em;
        }}
        h1 a {{
            color: var(--text-main);
            text-decoration: none;
            display: inline-flex;
            align-items: center;
            gap: 10px;
        }}
        h1 a:hover {{ color: var(--accent); }}
        .scan-badge {{
            background: var(--bg-card);
            border: 1px solid var(--border);
            color: var(--text-muted);
            padding: 5px 12px;
            border-radius: 999px;
            font-size: 0.82rem;
        }}
        .kpi-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 14px;
            margin-bottom: 22px;
        }}
        .kpi-card {{
            background: var(--bg-card);
            border: 1px solid var(--border);
            border-radius: 12px;
            padding: 16px 18px;
        }}
        .kpi-label {{
            font-size: 0.78rem;
            color: var(--text-muted);
            font-weight: 500;
            margin-bottom: 4px;
        }}
        .kpi-value {{
            font-size: 1.55rem;
            font-weight: 700;
            letter-spacing: -0.02em;
        }}
        .kpi-value.green {{ color: var(--accent-green); }}
        .kpi-value.blue {{ color: var(--accent); }}
        .kpi-value.amber {{ color: var(--accent-amber); }}
        .kpi-sub {{
            font-size: 0.75rem;
            color: var(--text-muted);
            margin-top: 2px;
        }}
        .toolbar {{
            display: flex;
            flex-wrap: wrap;
            justify-content: space-between;
            align-items: center;
            gap: 12px;
            margin-bottom: 20px;
        }}
        .tabs {{
            display: flex;
            flex-wrap: wrap;
            gap: 8px;
        }}
        .tab-btn {{
            background: var(--bg-card);
            border: 1px solid var(--border);
            color: var(--text-muted);
            cursor: pointer;
            padding: 9px 16px;
            border-radius: 10px;
            font-size: 0.88rem;
            font-weight: 600;
            transition: all 0.2s ease;
        }}
        .tab-btn:hover {{
            color: var(--text-main);
            background: var(--bg-card-hover);
        }}
        .tab-btn.active {{
            background: var(--accent);
            border-color: var(--accent);
            color: #0f172a;
        }}
        .filter-box {{
            display: flex;
            align-items: center;
            gap: 8px;
        }}
        .filter-input {{
            background: var(--bg-card);
            border: 1px solid var(--border);
            color: var(--text-main);
            border-radius: 9px;
            padding: 8px 12px;
            font-size: 0.86rem;
            min-width: 220px;
            outline: none;
        }}
        .filter-input:focus {{
            border-color: var(--accent);
        }}
        .tab-content {{
            display: none;
        }}
        .tab-content.active {{
            display: block;
            animation: fadeIn 0.2s ease;
        }}
        @keyframes fadeIn {{
            from {{ opacity: 0; transform: translateY(3px); }}
            to {{ opacity: 1; transform: translateY(0); }}
        }}
        .section-header {{
            margin-bottom: 16px;
        }}
        .section-header h2 {{
            margin: 0 0 2px;
            font-size: 1.15rem;
        }}
        .section-header p {{
            margin: 0;
            color: var(--text-muted);
            font-size: 0.86rem;
        }}
        .dl-repo-list {{
            display: flex;
            flex-direction: column;
            gap: 16px;
        }}
        .dl-repo-card, .card {{
            background: var(--bg-card);
            border: 1px solid var(--border);
            border-radius: 12px;
            padding: 16px 18px;
        }}
        .card-header {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            gap: 8px;
        }}
        .card-header h3 {{
            margin: 0;
            font-size: 1rem;
            font-weight: 600;
        }}
        .card-header h3 a {{
            color: var(--text-main);
            text-decoration: none;
        }}
        .card-header h3 a:hover {{
            color: var(--accent);
            text-decoration: underline;
        }}
        .repo-desc {{
            font-size: 0.83rem;
            color: var(--text-muted);
            margin-top: 4px;
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
        }}
        .meta-line {{
            font-size: 0.8rem;
            color: var(--text-muted);
            margin: 8px 0 12px;
        }}
        .dual-chart-grid {{
            display: grid;
            grid-template-columns: repeat(2, minmax(0, 1fr));
            gap: 14px;
        }}
        @media (max-width: 860px) {{
            .dual-chart-grid {{ grid-template-columns: 1fr; }}
        }}
        .chart-box {{
            background: var(--bg-card-sub);
            border: 1px solid rgba(51, 65, 85, 0.7);
            border-radius: 10px;
            padding: 12px;
        }}
        .chart-box-title {{
            font-size: 0.8rem;
            font-weight: 600;
            color: var(--text-muted);
            margin-bottom: 8px;
        }}
        .canvas-wrap {{
            position: relative;
            height: 210px;
            width: 100%;
        }}
        .activity-wrap {{
            position: relative;
            height: 250px;
            width: 100%;
        }}
        details.asset-details {{
            margin-top: 12px;
            border-top: 1px solid rgba(51, 65, 85, 0.6);
            padding-top: 8px;
            font-size: 0.8rem;
            color: var(--text-muted);
        }}
        details.asset-details summary {{
            cursor: pointer;
            user-select: none;
            font-weight: 600;
            color: var(--text-muted);
        }}
        details.asset-details summary:hover {{
            color: var(--accent);
        }}
        .asset-list {{
            margin: 8px 0 0;
            padding-left: 18px;
        }}
        .asset-list li {{
            margin-bottom: 3px;
        }}
        .grid-container {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(400px, 1fr));
            gap: 16px;
        }}
        @media (max-width: 520px) {{
            .grid-container {{ grid-template-columns: 1fr; }}
            .filter-input {{ min-width: 100%; }}
        }}
        .badge {{
            font-size: 0.72rem;
            padding: 2px 8px;
            border-radius: 999px;
            background: rgba(148, 163, 184, 0.15);
            color: var(--text-muted);
            white-space: nowrap;
        }}
        .badge.private {{
            background: rgba(251, 191, 36, 0.15);
            color: var(--accent-amber);
        }}
        .global-card {{
            background: var(--bg-card);
            border: 1px solid var(--border);
            border-radius: 12px;
            padding: 20px;
            margin-bottom: 20px;
        }}
        .global-card h3 {{
            margin: 0 0 12px;
            font-size: 1.05rem;
            text-align: center;
        }}
        .doughnut-wrap {{
            position: relative;
            height: 260px;
            max-width: 420px;
            margin: 0 auto;
        }}
        .empty-note {{
            background: var(--bg-card);
            border: 1px dashed var(--border);
            border-radius: 12px;
            padding: 28px;
            text-align: center;
            color: var(--text-muted);
        }}
    </style>
</head>
<body>
<div class="container">
    <header>
        <h1><a href="https://github.com/{primary_owner}" target="_blank" title="GitHubプロフィールを開く">🚀 {escape_html(primary_owner)} GitHub Dashboard</a></h1>
        <div class="scan-badge">📅 スキャン日: {today_str}</div>
    </header>

    <section class="kpi-grid">
        <div class="kpi-card">
            <div class="kpi-label">総合ダウンロード数</div>
            <div class="kpi-value green">{grand_total_downloads:,}</div>
            <div class="kpi-sub">全リリースアセット合計</div>
        </div>
        <div class="kpi-card">
            <div class="kpi-label">純コード行数 (LOC)</div>
            <div class="kpi-value blue">{grand_total_code_lines:,}</div>
            <div class="kpi-sub">コメント: {grand_total_comment_lines:,} 行</div>
        </div>
        <div class="kpi-card">
            <div class="kpi-label">直近コミット数</div>
            <div class="kpi-value amber">{grand_total_commits:,}</div>
            <div class="kpi-sub">各リポジトリ最新100件基準</div>
        </div>
        <div class="kpi-card">
            <div class="kpi-label">対象リポジトリ</div>
            <div class="kpi-value">{repo_count:,}</div>
            <div class="kpi-sub">スキャン完了リポジトリ</div>
        </div>
    </section>

    <div class="toolbar">
        <div class="tabs">
            <button class="tab-btn active" onclick="openTab(event, 'tab-downloads')">📊 ダウンロード・累計</button>
            <button class="tab-btn" onclick="openTab(event, 'tab-loc')">📝 コード規模 (LOC・コメント)</button>
            <button class="tab-btn" onclick="openTab(event, 'tab-languages')">💻 言語比率</button>
            <button class="tab-btn" onclick="openTab(event, 'tab-activity')">📅 活動パターン</button>
        </div>
        <div class="filter-box">
            <input type="text" id="repo-filter" class="filter-input" placeholder="リポジトリ名・説明で絞り込み..." oninput="filterRepos()">
        </div>
    </div>

    <div id="tab-downloads" class="tab-content active">
        <div class="section-header">
            <h2>リポジトリ別 リリースDL数 ＆ 累計ダウンロード数</h2>
            <p>各リリースの個別ダウンロード数と、時系列での累計ダウンロード数を並べて表示します</p>
        </div>
        <div class="dl-repo-list">
"""

  has_any_release = False
  for repo in all_stats["all_repositories"]:
    repo_full = repo["repository"]
    dom_id = repo["dom_id"]
    repo_url = f"https://github.com/{repo_full}"
    desc_text = escape_html(repo["description"])
    search_blob = escape_html(f"{repo_full} {repo['description']}".lower())
    priv_badge = '<span class="badge private">Private</span>' if repo["private"] else '<span class="badge">Public</span>'
    if repo["releases"]:
      has_any_release = True
      desc_html = f'<div class="repo-desc" title="{desc_text}">{desc_text}</div>' if desc_text else ""
      pushed_html = f" / 最終更新: {repo['pushed_at']}" if repo["pushed_at"] else ""

      asset_items_html = ""
      for rel in repo["releases"]:
        tag_esc = escape_html(rel["tag_name"])
        asset_summary = ", ".join(
            f"{escape_html(a['filename'])} ({a['downloads']:,})"
            for a in rel.get("assets", [])
        ) or "アセットなし"
        asset_items_html += f"<li><b>{tag_esc}</b>（計 {rel['tag_total']:,}）: {asset_summary}</li>"

      html_content += f"""
            <div class="dl-repo-card searchable-item" data-search="{search_blob}">
                <div class="card-header">
                    <h3><a href="{repo_url}" target="_blank">{escape_html(repo_full)}</a></h3>
                    {priv_badge}
                </div>
                {desc_html}
                <div class="meta-line">合計DL: <b>{repo['total_downloads']:,}</b> 回 / リリース数: {len(repo['releases'])}{pushed_html}</div>
                <div class="dual-chart-grid">
                    <div class="chart-box">
                        <div class="chart-box-title">リリース別 ダウンロード数（個別）</div>
                        <div class="canvas-wrap"><canvas id="dl-bar-{dom_id}"></canvas></div>
                    </div>
                    <div class="chart-box">
                        <div class="chart-box-title">累計 ダウンロード数（推移・棒グラフ）</div>
                        <div class="canvas-wrap"><canvas id="dl-cum-{dom_id}"></canvas></div>
                    </div>
                </div>
                <details class="asset-details">
                    <summary>リリース別アセット内訳を表示</summary>
                    <ul class="asset-list">{asset_items_html}</ul>
                </details>
            </div>
"""

  if not has_any_release:
    html_content += '<div class="empty-note">リリース情報があるリポジトリはまだありません。</div>'

  html_content += """
        </div>
    </div>

    <div id="tab-loc" class="tab-content">
        <div class="section-header">
            <h2>コード行数（LOC）とコメント内訳</h2>
            <p>対象拡張子ファイルの純コード・コメント・空行の内訳です</p>
        </div>
        <div class="grid-container">
"""

  has_any_loc = False
  for repo in all_stats["all_repositories"]:
    repo_full = repo["repository"]
    dom_id = repo["dom_id"]
    repo_url = f"https://github.com/{repo_full}"
    desc_text = escape_html(repo["description"])
    search_blob = escape_html(f"{repo_full} {repo['description']}".lower())
    loc = repo["loc_stats"]
    if loc["total_lines"] > 0:
      has_any_loc = True
      desc_html = f'<div class="repo-desc" title="{desc_text}">{desc_text}</div>' if desc_text else ""
      html_content += f"""
            <div class="card searchable-item" data-search="{search_blob}">
                <div class="card-header">
                    <h3><a href="{repo_url}" target="_blank">{escape_html(repo_full)}</a></h3>
                    <span class="badge">{repo['file_count']} files</span>
                </div>
                {desc_html}
                <div class="meta-line">コード: <b>{loc['code_lines']:,}</b>行 / コメント: <b>{loc['comment_lines']:,}</b>行 / 空行: {loc['blank_lines']:,}行</div>
                <div class="canvas-wrap"><canvas id="loc-{dom_id}"></canvas></div>
            </div>
"""

  if not has_any_loc:
    html_content += '<div class="empty-note">集計対象のコードファイルが見つかりませんでした。</div>'

  html_content += """
        </div>
    </div>

    <div id="tab-languages" class="tab-content">
        <div class="section-header">
            <h2>使用言語比率（全体 ＆ リポジトリ別）</h2>
            <p>GitHub APIから取得した言語バイト数の割合です</p>
        </div>
        <div class="global-card">
            <h3>🌍 全リポジトリ合算の言語比率</h3>
            <div class="doughnut-wrap"><canvas id="lang-overall"></canvas></div>
        </div>
        <div class="grid-container">
"""

  for repo in all_stats["all_repositories"]:
    repo_full = repo["repository"]
    dom_id = repo["dom_id"]
    repo_url = f"https://github.com/{repo_full}"
    desc_text = escape_html(repo["description"])
    search_blob = escape_html(f"{repo_full} {repo['description']}".lower())
    if repo["languages"]:
      desc_html = f'<div class="repo-desc" title="{desc_text}">{desc_text}</div>' if desc_text else ""
      html_content += f"""
            <div class="card searchable-item" data-search="{search_blob}">
                <div class="card-header">
                    <h3><a href="{repo_url}" target="_blank">{escape_html(repo_full)}</a></h3>
                </div>
                {desc_html}
                <div class="doughnut-wrap" style="margin-top:10px;"><canvas id="lang-{dom_id}"></canvas></div>
            </div>
"""

  html_content += f"""
        </div>
    </div>

    <div id="tab-activity" class="tab-content">
        <div class="section-header">
            <h2>コミット活動パターン（曜日別 ＆ 時間帯別）</h2>
            <p>ローカルタイムゾーン基準で、どの曜日・どの時間帯にコミットが集中しているかを表示します</p>
        </div>
        <div class="dual-chart-grid">
            <div class="card">
                <div class="chart-box-title">曜日別 コミット数</div>
                <div class="activity-wrap"><canvas id="activity-weekly"></canvas></div>
            </div>
            <div class="card">
                <div class="chart-box-title">時間帯別 コミット数（00h - 23h）</div>
                <div class="activity-wrap"><canvas id="activity-hourly"></canvas></div>
            </div>
        </div>
    </div>
</div>

<script>
const DASHBOARD_DATA = {payload_json};
const PALETTE = ['#38bdf8', '#34d399', '#a78bfa', '#fbbf24', '#f472b6', '#fb7185', '#2dd4bf', '#818cf8'];

Chart.defaults.color = '#94a3b8';
Chart.defaults.borderColor = 'rgba(51, 65, 85, 0.65)';
Chart.defaults.font.family = "'Inter', 'Noto Sans JP', sans-serif";

function openTab(evt, tabName) {{
    const contents = document.getElementsByClassName("tab-content");
    for (const c of contents) c.classList.remove("active");
    const buttons = document.getElementsByClassName("tab-btn");
    for (const b of buttons) b.classList.remove("active");
    document.getElementById(tabName).classList.add("active");
    evt.currentTarget.classList.add("active");
}}

function filterRepos() {{
    const q = (document.getElementById("repo-filter").value || "").trim().toLowerCase();
    const items = document.getElementsByClassName("searchable-item");
    for (const el of items) {{
        const hay = el.getAttribute("data-search") || "";
        el.style.display = (!q || hay.includes(q)) ? "" : "none";
    }}
}}

document.addEventListener("DOMContentLoaded", () => {{
    for (const repo of DASHBOARD_DATA.repositories) {{
        const dl = repo.dl_chart;
        if (dl && dl.tags && dl.tags.length > 0) {{
            const barEl = document.getElementById(`dl-bar-${{repo.dom_id}}`);
            if (barEl) {{
                new Chart(barEl, {{
                    type: 'bar',
                    data: {{
                        labels: dl.tags,
                        datasets: [{{
                            label: 'リリース別DL数',
                            data: dl.per_release,
                            backgroundColor: 'rgba(52, 211, 153, 0.8)',
                            borderColor: '#34d399',
                            borderWidth: 1,
                            borderRadius: 6
                        }}]
                    }},
                    options: {{
                        responsive: true,
                        maintainAspectRatio: false,
                        plugins: {{
                            legend: {{ display: false }},
                            tooltip: {{
                                callbacks: {{
                                    afterLabel: (ctx) => {{
                                        const diff = dl.diffs[ctx.dataIndex] ?? 0;
                                        if (diff > 0) return `前回比: +${{diff.toLocaleString()}}`;
                                        if (diff < 0) return `前回比: ${{diff.toLocaleString()}}`;
                                        return '前回比: ±0';
                                    }}
                                }}
                            }}
                        }},
                        scales: {{
                            y: {{ beginAtZero: true, ticks: {{ precision: 0 }} }}
                        }}
                    }}
                }});
            }}

            const cumEl = document.getElementById(`dl-cum-${{repo.dom_id}}`);
            if (cumEl) {{
                new Chart(cumEl, {{
                    type: 'bar',
                    data: {{
                        labels: dl.tags,
                        datasets: [{{
                            label: '累計DL数',
                            data: dl.cumulative,
                            backgroundColor: 'rgba(56, 189, 248, 0.8)',
                            borderColor: '#38bdf8',
                            borderWidth: 1,
                            borderRadius: 6
                        }}]
                    }},
                    options: {{
                        responsive: true,
                        maintainAspectRatio: false,
                        plugins: {{ legend: {{ display: false }} }},
                        scales: {{
                            y: {{ beginAtZero: true, ticks: {{ precision: 0 }} }}
                        }}
                    }}
                }});
            }}
        }}

        const locEl = document.getElementById(`loc-${{repo.dom_id}}`);
        if (locEl && repo.loc_stats && repo.loc_stats.total_lines > 0) {{
            new Chart(locEl, {{
                type: 'bar',
                data: {{
                    labels: ['Code', 'Comment', 'Blank'],
                    datasets: [{{
                        label: 'Lines',
                        data: [repo.loc_stats.code_lines, repo.loc_stats.comment_lines, repo.loc_stats.blank_lines],
                        backgroundColor: ['#38bdf8', '#fbbf24', '#64748b'],
                        borderRadius: 6
                    }}]
                }},
                options: {{
                    responsive: true,
                    maintainAspectRatio: false,
                    plugins: {{ legend: {{ display: false }} }},
                    scales: {{ y: {{ beginAtZero: true }} }}
                }}
            }});
        }}

        const langEl = document.getElementById(`lang-${{repo.dom_id}}`);
        const entries = Object.entries(repo.languages || {{}}).sort((a, b) => b[1] - a[1]);
        if (langEl && entries.length > 0) {{
            new Chart(langEl, {{
                type: 'doughnut',
                data: {{
                    labels: entries.map(e => e[0]),
                    datasets: [{{
                        data: entries.map(e => e[1]),
                        backgroundColor: entries.map((_, i) => PALETTE[i % PALETTE.length]),
                        borderColor: '#1e293b',
                        borderWidth: 2
                    }}]
                }},
                options: {{
                    responsive: true,
                    maintainAspectRatio: false,
                    plugins: {{ legend: {{ position: 'right' }} }}
                }}
            }});
        }}
    }}

    const overallEl = document.getElementById('lang-overall');
    const overallEntries = Object.entries(DASHBOARD_DATA.global_languages || {{}}).sort((a, b) => b[1] - a[1]);
    if (overallEl && overallEntries.length > 0) {{
        new Chart(overallEl, {{
            type: 'doughnut',
            data: {{
                labels: overallEntries.map(e => e[0]),
                datasets: [{{
                    data: overallEntries.map(e => e[1]),
                    backgroundColor: overallEntries.map((_, i) => PALETTE[i % PALETTE.length]),
                    borderColor: '#1e293b',
                    borderWidth: 2
                }}]
            }},
            options: {{
                responsive: true,
                maintainAspectRatio: false,
                plugins: {{ legend: {{ position: 'right' }} }}
            }}
        }});
    }}

    const actWeeklyEl = document.getElementById('activity-weekly');
    if (actWeeklyEl) {{
        new Chart(actWeeklyEl, {{
            type: 'bar',
            data: {{
                labels: DASHBOARD_DATA.weekday_names,
                datasets: [{{
                    label: 'Commits',
                    data: DASHBOARD_DATA.weekdays_count,
                    backgroundColor: 'rgba(56, 189, 248, 0.85)',
                    borderColor: '#38bdf8',
                    borderWidth: 1,
                    borderRadius: 6
                }}]
            }},
            options: {{
                responsive: true,
                maintainAspectRatio: false,
                plugins: {{ legend: {{ display: false }} }},
                scales: {{ y: {{ beginAtZero: true, ticks: {{ precision: 0 }} }} }}
            }}
        }});
    }}

    const actHourlyEl = document.getElementById('activity-hourly');
    if (actHourlyEl) {{
        new Chart(actHourlyEl, {{
            type: 'bar',
            data: {{
                labels: DASHBOARD_DATA.hour_labels,
                datasets: [{{
                    label: 'Commits',
                    data: DASHBOARD_DATA.hours_count,
                    backgroundColor: 'rgba(167, 139, 250, 0.85)',
                    borderColor: '#a78bfa',
                    borderWidth: 1,
                    borderRadius: 4
                }}]
            }},
            options: {{
                responsive: true,
                maintainAspectRatio: false,
                plugins: {{ legend: {{ display: false }} }},
                scales: {{
                    x: {{ ticks: {{ maxRotation: 0, autoSkip: true, maxTicksLimit: 12 }} }},
                    y: {{ beginAtZero: true, ticks: {{ precision: 0 }} }}
                }}
            }}
        }});
    }}
}});
</script>
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