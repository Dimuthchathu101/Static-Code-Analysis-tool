import os
import re
import sys
import json
import requests
from bs4 import BeautifulSoup
import cssutils
from cssutils.css import CSSRule
import pyjsparser
import argparse
from urllib.parse import urljoin, urlparse
import tempfile
import shutil
import git
import subprocess
import os
import re
import csv
import base64
import math
import mimetypes

try:
    import subprocess
except ImportError:
    subprocess = None

def is_absolute(url):
    return bool(urlparse(url).netloc)

def fetch_url(session, url):
    try:
        response = session.get(url, timeout=10)
        response.raise_for_status()
        return response.text
    except requests.RequestException as e:
        return None, str(e)
    return None, 'Unknown error'

# --- Helper for minified detection ---
def is_minified(text):
    lines = text.splitlines()
    if not lines:
        return False
    avg_len = sum(len(l) for l in lines) / len(lines)
    return avg_len > 200 or len(lines) < 5

# --- Helper for image size detection ---
def is_large_image(path, content):
    # Only check for base64 or local files
    try:
        if path.startswith('data:image'):
            header, b64data = path.split(',', 1)
            data = base64.b64decode(b64data)
            return len(data) > 200*1024
        elif os.path.exists(path):
            return os.path.getsize(path) > 200*1024
    except Exception:
        return False
    return False

# --- Advanced SEO and HTML Performance ---
def analyze_html_content(content, location, options):
    issues = []
    soup = BeautifulSoup(content, 'html.parser')
    # SEO: canonical
    if not soup.find('link', rel='canonical'):
        issues.append(('SEO_MISSING_CANONICAL', location, 'Missing canonical tag'))
    # SEO: Open Graph/Twitter
    if not soup.find('meta', property='og:title'):
        issues.append(('SEO_MISSING_OG', location, 'Missing Open Graph meta'))
    if not soup.find('meta', attrs={'name': 'twitter:card'}):
        issues.append(('SEO_MISSING_TWITTER', location, 'Missing Twitter meta'))
    # SEO: robots meta
    if not soup.find('meta', attrs={'name': 'robots'}):
        issues.append(('SEO_MISSING_ROBOTS', location, 'Missing robots meta'))
    # SEO: sitemap
    if not soup.find('link', rel='sitemap'):
        issues.append(('SEO_MISSING_SITEMAP', location, 'Missing sitemap link'))
    # SEO: structured data
    if not soup.find('script', type='application/ld+json'):
        issues.append(('SEO_MISSING_STRUCTURED', location, 'Missing JSON-LD structured data'))
    # SEO: microdata
    if not soup.find(attrs={'itemscope': True}):
        issues.append(('SEO_MISSING_MICRODATA', location, 'Missing microdata'))
    # Performance: large images, missing loading=lazy
    for img in soup.find_all('img'):
        src = img.get('src')
        if src and (src.startswith('http') or src.startswith('data:image')):
            if is_large_image(src, content):
                issues.append(('HTML_LARGE_IMAGE', location, f'Large image: {src}'))
        if not img.get('loading') == 'lazy':
            issues.append(('HTML_IMG_NO_LAZY', location, f'Image missing loading=lazy: {src}'))
    # Performance: unminified inline scripts/styles
    for script in soup.find_all('script', src=False):
        if script.string and not is_minified(script.string):
            issues.append(('HTML_UNMINIFIED_INLINE_SCRIPT', location, 'Unminified inline script'))
    for style in soup.find_all('style'):
        if style.string and not is_minified(style.string):
            issues.append(('HTML_UNMINIFIED_INLINE_STYLE', location, 'Unminified inline style'))
    # Deprecated tags
    deprecated_tags = ['center', 'font', 'marquee']
    for tag in deprecated_tags:
        for found in soup.find_all(tag):
            issues.append(('HTML_DEPRECATED_TAG', location, f"Deprecated HTML tag <{tag}> used"))
    # Accessibility: missing aria (skip)
    # Accessibility: label/input (skip)
    # Accessibility: heading order (skip)
    # SEO: title, meta description, h1 count
    if not soup.find('title'):
        issues.append(('SEO_MISSING_TITLE', location, "Missing <title> tag"))
    if not soup.find('meta', attrs={'name': 'description'}):
        issues.append(('SEO_MISSING_DESCRIPTION', location, "Missing meta description"))
    h1s = soup.find_all('h1')
    if len(h1s) == 0:
        issues.append(('SEO_MISSING_H1', location, "No <h1> tag found"))
    elif len(h1s) > 1:
        issues.append(('SEO_MULTIPLE_H1', location, "Multiple <h1> tags found"))
    # Broken links
    for a in soup.find_all('a', href=True):
        href = a['href']
        if not is_absolute(href):
            continue  # skip local links in repo mode
        try:
            r = requests.head(href, allow_redirects=True, timeout=5)
            if r.status_code >= 400:
                issues.append(('HTML_BROKEN_LINK', href, f"Broken link: {r.status_code}"))
        except Exception as e:
            issues.append(('HTML_BROKEN_LINK', href, f"Broken link: {str(e)}"))
    for img in soup.find_all('img', src=True):
        src = img['src']
        if not is_absolute(src):
            continue
        try:
            r = requests.head(src, allow_redirects=True, timeout=5)
            if r.status_code >= 400:
                issues.append(('HTML_BROKEN_IMG', src, f"Broken image: {r.status_code}"))
        except Exception as e:
            issues.append(('HTML_BROKEN_IMG', src, f"Broken image: {str(e)}"))
    return issues

# --- Advanced CSS Analysis ---
def css_specificity(selector):
    # Simple specificity calculation: (IDs, classes, elements)
    id_count = selector.count('#')
    class_count = selector.count('.') + selector.count('[')
    element_count = len(re.findall(r'\b[a-zA-Z]+\b', selector))
    return (id_count, class_count, element_count)

def analyze_css_content(content, location, options):
    issues = []
    try:
        sheet = cssutils.parseString(content)
        selectors_seen = set()
        specificity_map = {}
        for rule in sheet:
            if rule.type == CSSRule.STYLE_RULE:
                selector = rule.selectorText
                spec = css_specificity(selector)
                specificity_map[selector] = spec
                # Specificity wars
                if spec[0] > 2 or spec[1] > 5:
                    issues.append(('CSS_SPECIFICITY_WAR', location, f'Selector {selector} has high specificity {spec}'))
                # Deep selectors
                if selector.count(' ') > 4:
                    issues.append(('CSS_DEEP_SELECTOR', location, f'Deep selector: {selector}'))
                # Use of IDs
                if '#' in selector:
                    issues.append(('CSS_ID_SELECTOR', location, f'ID selector: {selector}'))
                # Non-standard properties
                for prop in rule.style:
                    if prop.name.startswith('-') and not prop.name.startswith('--'):
                        issues.append(('CSS_NONSTANDARD_PROPERTY', location, f'Non-standard property: {prop.name}'))
                # !important
                for prop in rule.style:
                    if '!important' in prop.value:
                        issues.append(('CSS_IMPORTANT_OVERUSE', location, "Use of !important in CSS"))
                # Selector depth
                if options.max_selector_depth is not None:
                    depth = max(selector.count(' '), selector.count('>'))
                    if depth > options.max_selector_depth:
                        issues.append(('CSS_COMPLEX_SELECTOR', location, f"Overly complex selector: {selector}"))
                # Duplicate selectors
                if selector in selectors_seen:
                    issues.append(('CSS_DUPLICATE_SELECTOR', location, f"Duplicate selector: {selector}"))
                selectors_seen.add(selector)
        # Large file
        if len(content) > 100*1024:
            issues.append(('CSS_LARGE_FILE', location, f'CSS file > 100KB'))
        # Excessive @import
        if content.count('@import') > 3:
            issues.append(('CSS_EXCESSIVE_IMPORT', location, 'Excessive @import usage'))
        # Non-minified CSS
        if not is_minified(content):
            issues.append(('CSS_UNMINIFIED', location, 'Non-minified CSS'))
        # Specificity graph (optional: print or save as CSV/JSON)
        # ...
    except Exception as e:
        issues.append(('CSS_PARSING_ERROR', location, f"CSS parsing error: {str(e)}"))
    return issues

# --- Advanced JS Analysis ---
def analyze_js_content(content, location, options):
    issues = []
    try:
        pyjsparser.parse(content)
    except Exception as e:
        issues.append(('JS_SYNTAX_ERROR', location, f"Syntax error: {str(e)}"))
    # Deprecated APIs
    deprecated_apis = ['escape(', 'unescape(', 'document.all', 'document.layers']
    for api in deprecated_apis:
        if api in content:
            issues.append(('JS_DEPRECATED_API', location, f"Deprecated API used: {api}"))
    # Performance: large bundles
    if len(content) > 200*1024:
        issues.append(('JS_LARGE_BUNDLE', location, 'JS file > 200KB'))
    # Synchronous XHR
    if re.search(r'open\s*\(\s*["\"][A-Z]+["\"]\s*,\s*[^,]+,\s*false', content):
        issues.append(('JS_SYNC_XHR', location, 'Synchronous XHR detected'))
    # Blocking scripts
    if 'document.write' in content:
        issues.append(('JS_BLOCKING_SCRIPT', location, 'document.write used'))
    # Unused code: (not trivial, skip for now)
    # Modern syntax: (warn if ES6+ features detected)
    if re.search(r'=>|const |let |\bclass\b|\bimport\b|\bexport\b', content):
        issues.append(('JS_MODERN_SYNTAX', location, 'Modern JS syntax detected'))
    # ESLint integration (optional)
    if options.eslint and subprocess:
        try:
            with open('temp_eslint.js', 'w', encoding='utf-8') as f:
                f.write(content)
            result = subprocess.run(['eslint', 'temp_eslint.js', '-f', 'json'], capture_output=True, text=True)
            if result.returncode != 0 and result.stdout:
                eslint_issues = json.loads(result.stdout)
                for file_issues in eslint_issues:
                    for msg in file_issues.get('messages', []):
                        issues.append(('JS_ESLINT', location, f"{msg.get('message')} (rule: {msg.get('ruleId')})"))
            os.remove('temp_eslint.js')
        except Exception as e:
            issues.append(('JS_ESLINT_ERROR', location, f"ESLint error: {str(e)}"))
    return issues

# --- Dependency & Config Analysis ---
def analyze_package_json(path):
    issues = []
    try:
        with open(path, encoding='utf-8') as f:
            pkg = json.load(f)
        # Outdated/vulnerable/deprecated dependencies (basic: just warn if any dependency is pinned to old version)
        for dep_type in ['dependencies', 'devDependencies']:
            for dep, ver in pkg.get(dep_type, {}).items():
                if re.match(r'^[<>=~]?\d+\.\d+\.\d+$', ver) and ver.startswith(('0.', '1.0.', '2.0.')):
                    issues.append(('PKG_OLD_DEP', path, f'{dep} version {ver} may be outdated'))
                if 'deprecated' in dep.lower():
                    issues.append(('PKG_DEPRECATED_DEP', path, f'{dep} is deprecated'))
        # TODO: Integrate with npm audit or Snyk for real vulnerability scan
    except Exception as e:
        issues.append(('PKG_PARSE_ERROR', path, f'package.json parse error: {str(e)}'))
    return issues

def analyze_env_file(path):
    issues = []
    try:
        with open(path, encoding='utf-8') as f:
            for line in f:
                if re.search(r'(key|token|secret|password|api)[^=]*=', line, re.I):
                    issues.append(('ENV_POTENTIAL_SECRET', path, f'Potential secret: {line.strip()}'))
    except Exception as e:
        issues.append(('ENV_PARSE_ERROR', path, f'.env parse error: {str(e)}'))
    return issues

# --- Advanced Reporting ---
# --- Solutions for Issues ---
ISSUE_SOLUTIONS = {
    'PY_FLAKE8': 'Follow PEP8 guidelines. Use autopep8 or black to auto-format your code.',
    'FLASK_DEBUG_MODE': 'Disable debug mode in production by setting debug=False.',
    'SEO_MISSING_CANONICAL': 'Add a <link rel="canonical" href="..."> tag to your HTML <head>.',
    'SEO_MISSING_OG': 'Add Open Graph meta tags (e.g., <meta property="og:title" ...>) to your HTML <head>.',
    'SEO_MISSING_TWITTER': 'Add Twitter meta tags (e.g., <meta name="twitter:card" ...>) to your HTML <head>.',
    'SEO_MISSING_ROBOTS': 'Add <meta name="robots" content="index,follow"> to your HTML <head>.',
    'SEO_MISSING_SITEMAP': 'Add a <link rel="sitemap" href="/sitemap.xml"> to your HTML <head>.',
    'SEO_MISSING_STRUCTURED': 'Add JSON-LD structured data using <script type="application/ld+json">.',
    'SEO_MISSING_MICRODATA': 'Add microdata attributes (itemscope, itemtype) to your HTML.',
    'SEO_MISSING_TITLE': 'Add a <title> tag to your HTML <head>.',
    'SEO_MISSING_DESCRIPTION': 'Add a <meta name="description" content="..."> to your HTML <head>.',
    'SEO_MISSING_H1': 'Add a single <h1> tag to each page.',
    'HTML_UNMINIFIED_INLINE_SCRIPT': 'Minify your inline JavaScript using a tool like UglifyJS.',
    'HTML_UNMINIFIED_INLINE_STYLE': 'Minify your inline CSS using a tool like cssnano.',
    'HTML_IMG_NO_LAZY': 'Add loading="lazy" to <img> tags for better performance.',
    'HTML_BROKEN_IMG': 'Fix or remove broken image links.',
    'HTML_BROKEN_LINK': 'Fix or remove broken hyperlinks.',
    'JS_MODERN_SYNTAX': 'Ensure your build process transpiles modern JS to ES5 for compatibility.',
    'JS_SYNTAX_ERROR': 'Fix JavaScript syntax errors. Use ESLint or a modern IDE for help.',
    'JS_DEPRECATED_API': 'Replace deprecated JS APIs with modern alternatives.',
    'JS_LARGE_BUNDLE': 'Split large JS files into smaller chunks and use code splitting.',
    'JS_BLOCKING_SCRIPT': 'Avoid using document.write and blocking scripts.',
    'JS_DEPRECATED_LIFECYCLE': 'Update deprecated React lifecycle methods to modern hooks or methods.',
    'REACT_MISSING_KEY': 'Add a unique key prop to each element in a list.',
    'CSS_UNMINIFIED': 'Minify your CSS using a tool like cssnano.',
    'CSS_LARGE_FILE': 'Split large CSS files and remove unused styles.',
    'CSS_COMPLEX_SELECTOR': 'Simplify overly complex CSS selectors.',
    'CSS_DEEP_SELECTOR': 'Avoid deep CSS selectors for better performance.',
    'CSS_SPECIFICITY_WAR': 'Reduce selector specificity and avoid !important.',
    'CSS_ID_SELECTOR': 'Avoid using IDs in CSS selectors; prefer classes.',
    'CSS_NONSTANDARD_PROPERTY': 'Use standard CSS properties for better browser compatibility.',
    'CSS_DUPLICATE_SELECTOR': 'Remove duplicate CSS selectors.',
    'CSS_EXCESSIVE_IMPORT': 'Limit the use of @import in CSS; use build tools to combine files.',
    'PKG_OLD_DEP': 'Update outdated dependencies in package.json using npm or yarn.',
    'PKG_DEPRECATED_DEP': 'Replace deprecated dependencies with maintained alternatives.',
    'PHP_LINT_ERROR': 'Fix PHP syntax errors. Use php -l for linting.',
    'PHP_EVAL': 'Avoid using eval() in PHP for security and maintainability.',
    'PHP_MYSQL_DEPRECATED': 'Replace deprecated mysql_* functions with mysqli or PDO.',
    'PHP_UNVALIDATED_INPUT': 'Validate and sanitize all user input in PHP.',
    # ... add more as needed ...
}

# --- Enhanced HTML Reporting ---
def generate_report(issues, output_format='plain'):
    if not issues:
        print("No issues found!")
        return
    severity_map = {
        'SEO_MISSING_TITLE': 'error',
        'SEO_MISSING_DESCRIPTION': 'warning',
        'SEO_MISSING_CANONICAL': 'warning',
        'SEO_MISSING_OG': 'warning',
        'SEO_MISSING_TWITTER': 'info',
        'SEO_MISSING_ROBOTS': 'info',
        'SEO_MISSING_SITEMAP': 'info',
        'SEO_MISSING_STRUCTURED': 'info',
        'SEO_MISSING_MICRODATA': 'info',
        'HTML_LARGE_IMAGE': 'warning',
        'HTML_IMG_NO_LAZY': 'info',
        'HTML_UNMINIFIED_INLINE_SCRIPT': 'info',
        'HTML_UNMINIFIED_INLINE_STYLE': 'info',
        'CSS_SPECIFICITY_WAR': 'warning',
        'CSS_DEEP_SELECTOR': 'info',
        'CSS_ID_SELECTOR': 'info',
        'CSS_NONSTANDARD_PROPERTY': 'info',
        'CSS_IMPORTANT_OVERUSE': 'warning',
        'CSS_COMPLEX_SELECTOR': 'warning',
        'CSS_DUPLICATE_SELECTOR': 'info',
        'CSS_LARGE_FILE': 'warning',
        'CSS_EXCESSIVE_IMPORT': 'info',
        'CSS_UNMINIFIED': 'info',
        'JS_DEPRECATED_API': 'warning',
        'JS_LARGE_BUNDLE': 'warning',
        'JS_SYNC_XHR': 'warning',
        'JS_BLOCKING_SCRIPT': 'warning',
        'JS_MODERN_SYNTAX': 'info',
        'PKG_OLD_DEP': 'warning',
        'PKG_DEPRECATED_DEP': 'warning',
        'PKG_PARSE_ERROR': 'error',
        'ENV_POTENTIAL_SECRET': 'warning',
        'ENV_PARSE_ERROR': 'error',
        'PY_FLAKE8': 'info',
        'FLASK_DEBUG_MODE': 'info',
        'PHP_LINT_ERROR': 'error',
        'PHP_EVAL': 'warning',
        'PHP_MYSQL_DEPRECATED': 'warning',
        'PHP_UNVALIDATED_INPUT': 'warning',
        'REACT_MISSING_KEY': 'info',
        'REACT_DEPRECATED_LIFECYCLE': 'warning',
        # ... add more as needed ...
    }
    if output_format == 'html':
        print("""
<!DOCTYPE html>
<html lang='en'>
<head>
<meta charset='UTF-8'>
<title>Static Analysis Report</title>
<style>
body { font-family: 'Segoe UI', Arial, sans-serif; background: #f8f9fa; margin: 0; padding: 0; }
.container { max-width: 1100px; margin: 40px auto; background: #fff; border-radius: 12px; box-shadow: 0 2px 16px rgba(0,0,0,0.08); padding: 32px; }
h1 { color: #2c3e50; }
table { width: 100%; border-collapse: collapse; margin-top: 24px; }
th, td { padding: 12px 10px; border-bottom: 1px solid #eaeaea; }
th { background: #f1f3f6; color: #34495e; }
tr:hover { background: #f9fafb; }
.severity-error { color: #e74c3c; font-weight: bold; }
.severity-warning { color: #f39c12; font-weight: bold; }
.severity-info { color: #2980b9; }
.severity-critical { color: #c0392b; font-weight: bold; }
.solution { color: #16a085; font-size: 0.98em; margin-top: 4px; }
.summary { margin-top: 32px; background: #f1f3f6; border-radius: 8px; padding: 18px; }
</style>
</head>
<body>
<div class='container'>
<h1>Static Code Analysis Report</h1>
<p><b>Found {}</b> issues:</p>
<table>
<tr><th>#</th><th>Type</th><th>Location</th><th>Severity</th><th>Message</th><th>Solution</th></tr>
""".format(len(issues)))
        for i, (issue_type, location, message) in enumerate(issues, 1):
            sev = severity_map.get(issue_type, 'info')
            solution = ISSUE_SOLUTIONS.get(issue_type, 'Refer to documentation or best practices for this issue.')
            print("<tr>" +
                  f"<td>{i}</td>" +
                  f"<td>{issue_type}</td>" +
                  f"<td><code>{location}</code></td>" +
                  f"<td class='severity-{sev}'>{sev.capitalize()}</td>" +
                  f"<td>{message}</td>" +
                  f"<td class='solution'>{solution}</td>" +
                  "</tr>")
        print("""
</table>
<div class='summary'>
<h2>Summary</h2>
<ul>
""")
        stats = {}
        for t, _, _ in issues:
            stats[t] = stats.get(t, 0) + 1
        for t, count in stats.items():
            print(f"<li><b>{t}</b>: {count}</li>")
        print("""
</ul>
</div>
</div>
</body>
</html>
""")
        return
    elif output_format == 'json':
        print(json.dumps([
            {'type': t, 'location': l, 'message': m, 'severity': severity_map.get(t, 'info')} for t, l, m in issues
        ], indent=2))
    elif output_format == 'csv':
        writer = csv.writer(sys.stdout)
        writer.writerow(['Type', 'Location', 'Message', 'Severity'])
        for t, l, m in issues:
            writer.writerow([t, l, m, severity_map.get(t, 'info')])
    elif output_format == 'markdown':
        print('| Type | Location | Message | Severity |')
        print('|------|----------|---------|----------|')
        for t, l, m in issues:
            print(f'| {t} | {l} | {m} | {severity_map.get(t, "info")} |')
    else:
        print(f"Found {len(issues)} issues:")
        print("=" * 60)
        for i, (issue_type, location, message) in enumerate(issues, 1):
            sev = severity_map.get(issue_type, 'info')
            print(f"{i}. [{issue_type}] ({sev})")
            print(f"   Location: {location}")
            print(f"   Issue: {message}")
            print("-" * 60)
    # Summary statistics
    stats = {}
    for t, _, _ in issues:
        stats[t] = stats.get(t, 0) + 1
    print("\nSummary:")
    for t, count in stats.items():
        print(f"  {t}: {count}")

# --- React/JSX/TSX/Angular/TS Analysis ---
def analyze_jsx_tsx_content(content, location, options):
    issues = []
    # Use ESLint with React/TS plugins if available
    if options.eslint and subprocess:
        try:
            ext = os.path.splitext(location)[1].lower()
            temp_file = f'temp_eslint{ext}'
            with open(temp_file, 'w', encoding='utf-8') as f:
                f.write(content)
            result = subprocess.run(['eslint', temp_file, '-f', 'json'], capture_output=True, text=True)
            if result.stdout:
                eslint_issues = json.loads(result.stdout)
                for file_issues in eslint_issues:
                    for msg in file_issues.get('messages', []):
                        issues.append(('REACT_ESLINT' if ext in ['.jsx', '.tsx'] else 'TS_ESLINT', location, f"{msg.get('message')} (rule: {msg.get('ruleId')})"))
            os.remove(temp_file)
        except Exception as e:
            issues.append(('ESLINT_ERROR', location, f"ESLint error: {str(e)}"))
    # Heuristic checks for React
    if 'React.Component' in content or 'useState' in content or 'useEffect' in content:
        if re.search(r'<\w+\s+key=[^\s>]+', content) is None and re.search(r'\.map\(', content):
            issues.append(('REACT_MISSING_KEY', location, 'Missing key prop in list rendering'))
        if re.search(r'componentWillMount|componentWillReceiveProps|componentWillUpdate', content):
            issues.append(('REACT_DEPRECATED_LIFECYCLE', location, 'Deprecated lifecycle method used'))
        if re.search(r'document\.getElementById|document\.querySelector', content):
            issues.append(('REACT_DIRECT_DOM', location, 'Direct DOM manipulation in React'))
    # Heuristic checks for Angular
    if '@Component' in content or 'NgModule' in content:
        if re.search(r'\*ngFor(?!.*trackBy)', content):
            issues.append(('ANGULAR_MISSING_TRACKBY', location, 'Missing trackBy in *ngFor'))
    return issues

# --- Python/Flask Analysis ---
def analyze_python_content(content, location, options):
    issues = []
    # Use flake8 for linting
    try:
        temp_file = 'temp_flake8.py'
        with open(temp_file, 'w', encoding='utf-8') as f:
            f.write(content)
        result = subprocess.run(['flake8', temp_file, '--format=%(row)d:%(col)d: %(code)s %(text)s'], capture_output=True, text=True)
        if result.stdout:
            for line in result.stdout.splitlines():
                issues.append(('PY_FLAKE8', location, line))
        os.remove(temp_file)
    except Exception as e:
        issues.append(('PY_FLAKE8_ERROR', location, f'flake8 error: {str(e)}'))
    # Flask-specific
    if 'Flask(' in content:
        if 'debug=True' in content:
            issues.append(('FLASK_DEBUG_MODE', location, 'Flask debug mode enabled'))
        if 'SECRET_KEY' in content and re.search(r'SECRET_KEY\s*=\s*["\"][^"\"]+["\"]', content):
            issues.append(('FLASK_HARDCODED_SECRET', location, 'Hardcoded Flask SECRET_KEY'))
    return issues

# --- PHP Analysis ---
def analyze_php_content(content, location, options):
    issues = []
    # Use PHP lint if available
    try:
        temp_file = 'temp_php.php'
        with open(temp_file, 'w', encoding='utf-8') as f:
            f.write(content)
        result = subprocess.run(['php', '-l', temp_file], capture_output=True, text=True)
        if 'Parse error' in result.stdout or 'Parse error' in result.stderr:
            issues.append(('PHP_PARSE_ERROR', location, result.stdout + result.stderr))
        os.remove(temp_file)
    except Exception as e:
        issues.append(('PHP_LINT_ERROR', location, f'php -l error: {str(e)}'))
    # Heuristic checks
    if 'eval(' in content:
        issues.append(('PHP_EVAL', location, 'Use of eval()'))
    if re.search(r'mysql_\w+\(', content):
        issues.append(('PHP_MYSQL_DEPRECATED', location, 'Use of deprecated mysql_* functions'))
    if re.search(r'\$_(GET|POST|REQUEST|COOKIE)\[', content) and not re.search(r'htmlspecialchars|filter_var', content):
        issues.append(('PHP_UNVALIDATED_INPUT', location, 'Potential unvalidated input'))
    return issues

# --- Angular JSON Analysis ---
def analyze_angular_json_content(content, location, options):
    issues = []
    try:
        data = json.loads(content)
        if 'projects' in data:
            for proj, conf in data['projects'].items():
                if 'architect' in conf and 'build' in conf['architect']:
                    if conf['architect']['build'].get('optimization') is False:
                        issues.append(('ANGULAR_NO_OPTIMIZATION', location, f'Angular project {proj} has optimization disabled'))
    except Exception as e:
        issues.append(('ANGULAR_JSON_ERROR', location, f'angular.json parse error: {str(e)}'))
    return issues

# --- Repo Analysis ---
def analyze_github_repo(repo_url, options):
    temp_dir = tempfile.mkdtemp()
    try:
        print(f"Cloning {repo_url} ...")
        git.Repo.clone_from(repo_url, temp_dir)
        issues = []
        for root, dirs, files in os.walk(temp_dir):
            for file in files:
                path = os.path.join(root, file)
                ext = os.path.splitext(file)[1].lower()
                try:
                    with open(path, encoding='utf-8', errors='ignore') as f:
                        content = f.read()
                except Exception:
                    continue
                if ext in ['.html', '.jinja', '.j2'] and options.html:
                    issues += analyze_html_content(content, path, options)
                elif ext in ['.css'] and options.css:
                    issues += analyze_css_content(content, path, options)
                elif ext in ['.js'] and options.js:
                    issues += analyze_js_content(content, path, options)
                elif ext in ['.jsx', '.tsx', '.ts'] and options.js:
                    issues += analyze_jsx_tsx_content(content, path, options)
                elif ext == '.py':
                    issues += analyze_python_content(content, path, options)
                elif ext == '.php':
                    issues += analyze_php_content(content, path, options)
                elif file == 'package.json':
                    issues += analyze_package_json(path)
                elif file == '.env':
                    issues += analyze_env_file(path)
                elif file == 'angular.json':
                    issues += analyze_angular_json_content(content, path, options)
        return issues
    finally:
        shutil.rmtree(temp_dir)

class WebsiteAnalyzer:
    def __init__(self, url, options):
        self.url = url
        self.base_url = self._get_base_url(url)
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (compatible; StaticAnalyzer/2.0)'
        })
        self.issues = []
        self.options = options
        self.html_content = None
        self.soup = None
        self.external_css = []
        self.external_js = []
        self.used_selectors = set()
        self.all_links = []
        self.all_imgs = []

    def _get_base_url(self, url):
        return '/'.join(url.split('/')[:3])

    def _fetch_url(self, url):
        try:
            response = self.session.get(url, timeout=10)
            response.raise_for_status()
            return response.text
        except requests.RequestException as e:
            self.issues.append(('NETWORK_ERROR', url, str(e)))
            return None

    def _check_robots_txt(self):
        if self.options.ignore_robots:
            return
        robots_url = f"{self.base_url}/robots.txt"
        robots = self._fetch_url(robots_url)
        if robots and "User-agent: *" in robots and "Disallow: /" in robots:
            self.issues.append(('ROBOTS_DISALLOW', robots_url, "Blocked by robots.txt"))

    def analyze(self):
        self._check_robots_txt()
        self.html_content = self._fetch_url(self.url)
        if not self.html_content:
            return self.issues
        self.soup = BeautifulSoup(self.html_content, 'html.parser')
        if self.options.html:
            self._analyze_html()
        if self.options.css:
            self._analyze_styles()
        if self.options.js:
            self._analyze_scripts()
        if self.options.perfsec:
            self._analyze_perfsec()
        return self.issues

    # --- HTML Analysis ---
    def _analyze_html(self):
        soup = self.soup
        # Accessibility: missing alt
        for img in soup.find_all('img'):
            self.all_imgs.append(img)
            if not img.get('alt'):
                self.issues.append(('HTML_MISSING_ALT', str(img), "Image missing alt text"))
        # Deprecated tags
        deprecated_tags = ['center', 'font', 'marquee']
        for tag in deprecated_tags:
            for found in soup.find_all(tag):
                self.issues.append(('HTML_DEPRECATED_TAG', str(found), f"Deprecated HTML tag <{tag}> used"))
        # Accessibility: missing aria
        for el in soup.find_all(True):
            if el.name in ['button', 'input', 'a'] and not any(attr.startswith('aria-') for attr in el.attrs):
                self.issues.append(('HTML_MISSING_ARIA', str(el), f"<{el.name}> missing aria-* attribute"))
        # Accessibility: label/input
        for inp in soup.find_all('input'):
            if not inp.get('id') or not soup.find('label', attrs={'for': inp.get('id')}):
                self.issues.append(('HTML_INPUT_NO_LABEL', str(inp), "Input missing associated <label>"))
        # Accessibility: heading order
        headings = [int(h.name[1]) for h in soup.find_all(re.compile('^h[1-6]$'))]
        if headings:
            prev = 0
            for h in headings:
                if prev and h > prev + 1:
                    self.issues.append(('HTML_HEADING_ORDER', f"h{h}", "Skipped heading level"))
                prev = h
        # SEO: title, meta description, h1 count
        if not soup.find('title'):
            self.issues.append(('SEO_MISSING_TITLE', self.url, "Missing <title> tag"))
        if not soup.find('meta', attrs={'name': 'description'}):
            self.issues.append(('SEO_MISSING_DESCRIPTION', self.url, "Missing meta description"))
        h1s = soup.find_all('h1')
        if len(h1s) == 0:
            self.issues.append(('SEO_MISSING_H1', self.url, "No <h1> tag found"))
        elif len(h1s) > 1:
            self.issues.append(('SEO_MULTIPLE_H1', self.url, "Multiple <h1> tags found"))
        # Broken links
        for a in soup.find_all('a', href=True):
            href = a['href']
            if not is_absolute(href):
                href = urljoin(self.base_url + '/', href)
            self.all_links.append(href)
            try:
                r = self.session.head(href, allow_redirects=True, timeout=5)
                if r.status_code >= 400:
                    self.issues.append(('HTML_BROKEN_LINK', href, f"Broken link: {r.status_code}"))
            except Exception as e:
                self.issues.append(('HTML_BROKEN_LINK', href, f"Broken link: {str(e)}"))
        for img in soup.find_all('img', src=True):
            src = img['src']
            if not is_absolute(src):
                src = urljoin(self.base_url + '/', src)
            try:
                r = self.session.head(src, allow_redirects=True, timeout=5)
                if r.status_code >= 400:
                    self.issues.append(('HTML_BROKEN_IMG', src, f"Broken image: {r.status_code}"))
            except Exception as e:
                self.issues.append(('HTML_BROKEN_IMG', src, f"Broken image: {str(e)}"))

    # --- CSS Analysis ---
    def _analyze_styles(self):
        soup = self.soup
        # External CSS
        for link in soup.find_all('link', rel='stylesheet'):
            href = link['href']
            css_url = href if is_absolute(href) else urljoin(self.base_url + '/', href)
            css_content = self._fetch_url(css_url)
            if css_content:
                self.external_css.append((css_url, css_content))
                self._analyze_css(css_content, css_url)
        # Inline CSS
        for style in soup.find_all('style'):
            if style.string:
                self._analyze_css(style.string, self.url)
        # Inline styles in HTML
        inline_style_pattern = re.compile(r'style="([^"]*)"')
        for match in inline_style_pattern.findall(self.html_content):
            self._analyze_css(match, self.url)
        # Unused selectors
        self._check_unused_selectors()

    def _analyze_css(self, css_content, source):
        try:
            sheet = cssutils.parseString(css_content)
            selectors_seen = set()
            for rule in sheet:
                if rule.type == CSSRule.STYLE_RULE:
                    # !important
                    for prop in rule.style:
                        if '!important' in prop.value:
                            self.issues.append(('CSS_IMPORTANT_OVERUSE', source, "Use of !important in CSS"))
                    # Selector depth
                    selector = rule.selectorText
                    if self.options.max_selector_depth is not None:
                        depth = max(selector.count(' '), selector.count('>'))
                        if depth > self.options.max_selector_depth:
                            self.issues.append(('CSS_COMPLEX_SELECTOR', source, f"Overly complex selector: {selector}"))
                    # Vendor prefix
                    for prop in rule.style:
                        if prop.name.startswith('-webkit-') or prop.name.startswith('-moz-') or prop.name.startswith('-ms-'):
                            if not prop.name.startswith('--'):
                                self.issues.append(('CSS_VENDOR_PREFIX', source, f"Vendor prefix used: {prop.name}"))
                    # Duplicate selectors
                    if selector in selectors_seen:
                        self.issues.append(('CSS_DUPLICATE_SELECTOR', source, f"Duplicate selector: {selector}"))
                    selectors_seen.add(selector)
                    # Track selectors for unused check
                    self.used_selectors.add(selector)
        except Exception as e:
            self.issues.append(('CSS_PARSING_ERROR', source, f"CSS parsing error: {str(e)}"))

    def _check_unused_selectors(self):
        # Only works for external CSS
        html = self.html_content
        for css_url, css_content in self.external_css:
            try:
                sheet = cssutils.parseString(css_content)
                for rule in sheet:
                    if rule.type == CSSRule.STYLE_RULE:
                        selector = rule.selectorText
                        # Only check simple selectors
                        if selector and not re.search(r'[\[\]:>~+]', selector):
                            if selector not in html:
                                self.issues.append(('CSS_UNUSED_SELECTOR', css_url, f"Unused selector: {selector}"))
            except Exception:
                pass

    # --- JS Analysis ---
    def _analyze_scripts(self):
        soup = self.soup
        # External scripts
        for script in soup.find_all('script', src=True):
            src = script['src']
            js_url = src if is_absolute(src) else urljoin(self.base_url + '/', src)
            js_content = self._fetch_url(js_url)
            if js_content:
                self.external_js.append((js_url, js_content))
                self._analyze_javascript(js_content, js_url)
        # Inline scripts
        for script in soup.find_all('script', src=False):
            if script.string:
                self._analyze_javascript(script.string, self.url)
        # Inline event handlers
        for el in soup.find_all(True):
            for attr in el.attrs:
                if attr.startswith('on'):
                    self.issues.append(('JS_INLINE_EVENT_HANDLER', str(el), f"Inline event handler: {attr}"))
        # ESLint integration (optional)
        if self.options.eslint and subprocess:
            for js_url, js_content in self.external_js:
                self._eslint_check(js_content, js_url)

    def _analyze_javascript(self, js_content, source):
        try:
            pyjsparser.parse(js_content)
        except Exception as e:
            self.issues.append(('JS_SYNTAX_ERROR', source, f"Syntax error: {str(e)}"))
        # Dangerous patterns
        dangerous_patterns = {
            'eval': r'\beval\s*\(',
            'innerHTML': r'\.innerHTML\s*=',
            'document.write': r'document\.write\s*\('
        }
        for pattern_name, pattern in dangerous_patterns.items():
            if re.search(pattern, js_content):
                self.issues.append(('JS_DANGEROUS_FUNCTION', source, f"Use of {pattern_name} detected"))
        # Deprecated APIs
        deprecated_apis = ['escape(', 'unescape(', 'document.all', 'document.layers']
        for api in deprecated_apis:
            if api in js_content:
                self.issues.append(('JS_DEPRECATED_API', source, f"Deprecated API used: {api}"))

    def _eslint_check(self, js_content, source):
        try:
            with open('temp_eslint.js', 'w', encoding='utf-8') as f:
                f.write(js_content)
            result = subprocess.run(['eslint', 'temp_eslint.js', '-f', 'json'], capture_output=True, text=True)
            if result.returncode != 0 and result.stdout:
                eslint_issues = json.loads(result.stdout)
                for file_issues in eslint_issues:
                    for msg in file_issues.get('messages', []):
                        self.issues.append(('JS_ESLINT', source, f"{msg.get('message')} (rule: {msg.get('ruleId')})"))
            os.remove('temp_eslint.js')
        except Exception as e:
            self.issues.append(('JS_ESLINT_ERROR', source, f"ESLint error: {str(e)}"))

    # --- Performance & Security ---
    def _analyze_perfsec(self):
        # Large files
        for url, content in self.external_css + self.external_js:
            if len(content) > 100*1024:
                self.issues.append(('PERF_LARGE_FILE', url, f"File size > 100KB ({len(content)} bytes)"))
        # Insecure requests
        for url, _ in self.external_css + self.external_js:
            if url.startswith('http://'):
                self.issues.append(('SEC_INSECURE_REQUEST', url, "Insecure HTTP resource"))
        # Inline scripts/styles
        for script in self.soup.find_all('script', src=False):
            if script.string and len(script.string) > 100:
                self.issues.append(('SEC_INLINE_SCRIPT', self.url, "Large inline script detected"))
        for style in self.soup.find_all('style'):
            if style.string and len(style.string) > 100:
                self.issues.append(('SEC_INLINE_STYLE', self.url, "Large inline style detected"))

# --- CLI ---
def main():
    parser = argparse.ArgumentParser(description='Static Website Code Analyzer')
    parser.add_argument('url', nargs='?', help='URL of the website to analyze')
    parser.add_argument('--repo', help='GitHub repository URL to analyze')
    parser.add_argument('--output', choices=['plain', 'json', 'html', 'csv', 'markdown'], default='plain', help='Output format')
    parser.add_argument('--ignore-robots', action='store_true', help='Ignore robots.txt restrictions')
    parser.add_argument('--max-selector-depth', type=int, default=3, help='Max CSS selector depth before warning')
    parser.add_argument('--no-html', action='store_true', help='Disable HTML checks')
    parser.add_argument('--no-css', action='store_true', help='Disable CSS checks')
    parser.add_argument('--no-js', action='store_true', help='Disable JS checks')
    parser.add_argument('--no-perfsec', action='store_true', help='Disable performance/security checks')
    parser.add_argument('--eslint', action='store_true', help='Enable ESLint integration (requires Node.js)')
    args = parser.parse_args()
    class Opt:
        html = not args.no_html
        css = not args.no_css
        js = not args.no_js
        perfsec = not args.no_perfsec
        ignore_robots = args.ignore_robots
        max_selector_depth = args.max_selector_depth
        eslint = args.eslint
    if args.repo:
        issues = analyze_github_repo(args.repo, Opt)
        generate_report(issues, output_format=args.output)
    elif args.url:
        analyzer = WebsiteAnalyzer(args.url, Opt)
        issues = analyzer.analyze()
        generate_report(issues, output_format=args.output)
    else:
        parser.print_help()

if __name__ == "__main__":
    main() 