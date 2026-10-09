#!/bin/sh
# 用系统自带的外部浏览器打开导读站。
# 原因：WorkBuddy 内置预览窗口的行内 WebContents 被沙箱策略禁用了下载，
# 页面里的「导出 Excel」在内置窗口里必然落不了盘；外部 Chrome / Edge 完全正常。
# 用法：sh open_external.sh            # 完整版
#       sh open_external.sh simple     # 简化版（不含作者分析 / 导出面板）
set -e
BASE="$(cd "$(dirname "$0")" && pwd)"
case "$1" in
  simple) FILE="$BASE/interspeech2026_simple.html" ;;
  *)      FILE="$BASE/interspeech2026_authors.html" ;;
esac

for B in "/Applications/Google Chrome.app" \
         "/Applications/Microsoft Edge.app" \
         "/Applications/Chromium.app" \
         "/Applications/Brave Browser.app"; do
  if [ -d "$B" ]; then
    echo "打开：$B"
    open -a "$B" "$FILE"
    exit 0
  fi
done

echo "没找到 Chrome / Edge，用系统默认浏览器打开"
open "$FILE"
