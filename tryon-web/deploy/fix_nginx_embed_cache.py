from pathlib import Path

p = Path("/etc/nginx/sites-enabled/soco-tryon")
t = p.read_text()
if "location = /static/embed_tryon_link.js" in t:
    print("already present")
else:
    needle = "    location /static/ {\n        proxy_pass http://soco_tryon;\n"
    insert = (
        "    location = /static/embed_tryon_link.js {\n"
        "        proxy_pass http://soco_tryon;\n"
        "        proxy_http_version 1.1;\n"
        "        proxy_set_header Host $host;\n"
        "        proxy_set_header X-Real-IP $remote_addr;\n"
        "        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;\n"
        "        proxy_set_header X-Forwarded-Proto $scheme;\n"
        "        expires -1;\n"
        '        add_header Cache-Control "no-store, no-cache, must-revalidate, max-age=0";\n'
        "    }\n\n"
    )
    if needle not in t:
        raise SystemExit("needle not found")
    p.write_text(t.replace(needle, insert + needle, 1))
    print("nginx updated")
