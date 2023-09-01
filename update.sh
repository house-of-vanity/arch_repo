#!/bin/bash

dir_path="$1"

{
  echo "<!DOCTYPE html>"
  echo "<html>"
  echo "<head>"
  echo "  <title>Directory Index</title>"
  echo "  <style>"
  echo "    body { font-family: Arial, sans-serif; margin: 40px; }"
  echo "    h1 { color: #333366; }"
  echo "    table { width: 100%; border-collapse: collapse; }"
  echo "    th, td { border: 1px solid lightgray; padding: 8px; text-align: left; }"
  echo "    a { text-decoration: none; color: darkgray; }"
  echo "    a:visited { color: lightgray; }"
  echo "  </style>"
  echo "</head>"
  echo "<body>"
  echo "  <h1>Index</h1>"
  echo "  <h2>$dir_path</h2>"

  cd "$dir_path" || exit
  
  echo "  <h2>Base</h2>"
  echo "  <table>"
  echo "    <tr>"
  echo "      <th>Filename</th>"
  echo "      <th>Size</th>"
  echo "      <th>Created On</th>"
  echo "    </tr>"

  for file in *; do
    if [[ "$file" == *.zst ]]; then continue; fi
    size=$(stat -c%s "$file")
    sizeHR=$(numfmt --to=iec-i --suffix=B --format="%.2f" "$size")
    mtime=$(stat -c %y "$file" | cut -d' ' -f1)
    echo "    <tr>"
    echo "      <td><a href=\"$file\">$file</a></td>"
    echo "      <td>${sizeHR}</td>"
    echo "      <td>${mtime}</td>"
    echo "    </tr>"
  done

  echo "  </table>"

  echo "  <h2>Packages</h2>"
  echo "  <table>"
  echo "    <tr>"
  echo "      <th>Package Name</th>"
  echo "      <th>Version</th>"
  echo "      <th>Size</th>"
  echo "      <th>Created On</th>"
  echo "    </tr>"

  for file in *.zst; do
    package_name=$(echo "$file" | cut -d'-' -f1)
    version=$(echo "$file" | cut -d'-' -f2- | rev | cut -c 5- | rev)
    size=$(stat -c%s "$file")
    sizeHR=$(numfmt --to=iec-i --suffix=B --format="%.2f" "$size")
    mtime=$(stat -c %y "$file" | cut -d' ' -f1)
    echo "    <tr>"
    echo "      <td><a href=\"$file\">$package_name</a></td>"
    echo "      <td>${version}</td>"
    echo "      <td>${sizeHR}</td>"
    echo "      <td>${mtime}</td>"
    echo "    </tr>"
  done

  echo "  </table>"
  echo "</body>"
  echo "</html>"

} > "$dir_path/index.html"

