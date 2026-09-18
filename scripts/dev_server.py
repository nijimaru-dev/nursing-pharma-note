# -*- coding: utf-8 -*-
"""
dev_server.py
ローカル確認用の簡易HTTPサーバー。

`python -m http.server` はレスポンスに Cache-Control を付与しないため、
ブラウザがJS/JSONを積極的にキャッシュしてしまい、通常のリロードでは
編集後の内容が反映されず、ハードリロード（Ctrl+Shift+R）が毎回必要に
なる問題があった。このスクリプトは全レスポンスへ
Cache-Control: no-cache, no-store, must-revalidate を付与することで、
通常のリロードでも常に最新のファイルが反映されるようにする。

使い方:
    python scripts/dev_server.py
    python scripts/dev_server.py --port 8000 --dir site
"""

import argparse
import functools
import http.server


class NoCacheHandler(http.server.SimpleHTTPRequestHandler):
    def end_headers(self):
        self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
        self.send_header("Pragma", "no-cache")
        self.send_header("Expires", "0")
        super().end_headers()


def main():
    ap = argparse.ArgumentParser(description="ローカル確認用: キャッシュ無効化つき静的サーバー")
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--dir", default="site", help="配信するディレクトリ（既定: site）")
    args = ap.parse_args()

    handler = functools.partial(NoCacheHandler, directory=args.dir)
    with http.server.ThreadingHTTPServer(("127.0.0.1", args.port), handler) as httpd:
        print(f"http://localhost:{args.port} で配信中（Cache-Control: no-cache）。Ctrl+Cで終了。")
        httpd.serve_forever()


if __name__ == "__main__":
    main()
