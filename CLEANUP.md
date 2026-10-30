# Cleanup commands (run once, on your computer, inside the project folder)

# 1) Remove files that must never be in Git
git rm -r --cached node_modules media db.sqlite3 db.backup.sqlite3 helpdesk_backup.json
# 2) Remove empty / leftover files
git rm bytes py python str fix_indent.py "templates/New Text Document.txt"
# 3) Commit
git add .gitignore
git commit -m "Secure settings, remove data files from repo"
git push

# 4) Deploying: the app needs WeasyPrint (PDF vouchers), which needs system libraries.
#    Use the included Dockerfile (choose "Docker" as the runtime on your host), not the plain Python runtime.
