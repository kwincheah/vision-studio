"""Security and Secret Scanning Utility for Public GitHub Repository Preparation."""
import os
import re
import sys

SECRET_PATTERNS = [
    (r'(?i)(?:api_key|apikey|secret_key|private_key)\s*[:=]\s*["\'][A-Za-z0-9_\-\.]{8,}["\']', "Potential API/Secret Key"),
    (r'ghp_[A-Za-z0-9]{36}', "GitHub Personal Access Token"),
    (r'github_pat_[A-Za-z0-9_]{50,}', "GitHub Fine-Grained Token"),
    (r'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----', "Private Key Block"),
    (r'AIza[0-9A-Za-z\\-_]{35}', "Google API Key"),
    (r'sk-[a-zA-Z0-9]{32,}', "OpenAI/Anthropic Secret Key"),
    (r'(?i)password\s*[:=]\s*["\'][^"\']{6,}["\']', "Hardcoded Password"),
]

def scan():
    repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    ignored_dirs = {'.git', '.pytest_cache', '__pycache__', 'venv', '.gemini', '.vm_config', 'saved_images', 'dist', 'build', 'installer_output'}
    ignored_exts = {'.png', '.jpg', '.jpeg', '.pdf', '.pt', '.pyc', '.pyd', '.ico', '.svg'}

    findings = []
    scanned_files = 0

    for root, dirs, files in os.walk(repo_root):
        dirs[:] = [d for d in dirs if d not in ignored_dirs]
        for f in files:
            if any(f.endswith(ext) for ext in ignored_exts):
                continue
            filepath = os.path.join(root, f)
            scanned_files += 1
            try:
                with open(filepath, 'r', encoding='utf-8', errors='ignore') as fp:
                    content = fp.read()
                    for pattern, label in SECRET_PATTERNS:
                        matches = re.finditer(pattern, content)
                        for m in matches:
                            snippet = m.group(0)[:60]
                            rel_path = os.path.relpath(filepath, repo_root)
                            findings.append((rel_path, label, snippet))
            except Exception as e:
                pass

    print(f"Scanned {scanned_files} files across repository.")
    if findings:
        print(f"WARNING: Found {len(findings)} potential secret(s):")
        for path, label, snip in findings:
            print(f"  [{label}] {path} -> {snip}")
        return False
    else:
        print("PASS: Zero secrets, private keys, or credentials found.")
        return True

if __name__ == "__main__":
    success = scan()
    sys.exit(0 if success else 1)
