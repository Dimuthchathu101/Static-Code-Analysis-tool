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
import html

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

# --- Helper to create a standardized issue dict ---
def make_issue(issue_type, location, message, severity=None, line=None, context=None, column=None):
    if line is None or line == '' or line == '-':
        line = 'N/A'
    if not severity:
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
            'HTML_DEPRECATED_TAG': 'warning',
            'HTML_MISSING_ALT': 'info',
            'HTML_MISSING_ARIA': 'info',
            'HTML_INPUT_NO_LABEL': 'info',
            'HTML_HEADING_ORDER': 'info',
            'SEO_MISSING_H1': 'warning',
            'SEO_MULTIPLE_H1': 'warning',
            'HTML_BROKEN_LINK': 'error',
            'HTML_BROKEN_IMG': 'error',
            'CSS_SPECIFICITY_WAR': 'warning',
            'CSS_DEEP_SELECTOR': 'info',
            'CSS_ID_SELECTOR': 'info',
            'CSS_NONSTANDARD_PROPERTY': 'info',
            'CSS_IMPORTANT_OVERUSE': 'info',
            'CSS_COMPLEX_SELECTOR': 'warning',
            'CSS_DUPLICATE_SELECTOR': 'info',
            'CSS_LARGE_FILE': 'warning',
            'CSS_EXCESSIVE_IMPORT': 'info',
            'CSS_UNMINIFIED': 'info',
            'CSS_PARSING_ERROR': 'error',
            'JS_SYNTAX_ERROR': 'error',
            'JS_DEPRECATED_API': 'warning',
            'JS_LARGE_BUNDLE': 'warning',
            'JS_SYNC_XHR': 'warning',
            'JS_BLOCKING_SCRIPT': 'warning',
            'JS_MODERN_SYNTAX': 'info',
            'JS_ESLINT': 'warning',
            'JS_ESLINT_ERROR': 'error',
            'REACT_MISSING_KEY': 'warning',
            'REACT_DEPRECATED_LIFECYCLE': 'warning',
            'REACT_DIRECT_DOM': 'warning',
            'ANGULAR_MISSING_TRACKBY': 'info',
            'PY_FLAKE8': 'warning',
            'PY_FLAKE8_ERROR': 'error',
            'FLASK_DEBUG_MODE': 'warning',
            'FLASK_HARDCODED_SECRET': 'error',
            'PHP_PARSE_ERROR': 'error',
            'PHP_LINT_ERROR': 'error',
            'PHP_EVAL': 'warning',
            'PHP_MYSQL_DEPRECATED': 'warning',
            'PHP_UNVALIDATED_INPUT': 'warning',
            'PKG_OLD_DEP': 'info',
            'PKG_DEPRECATED_DEP': 'warning',
            'PKG_PARSE_ERROR': 'error',
            'ENV_POTENTIAL_SECRET': 'warning',
            'ENV_PARSE_ERROR': 'error',
            'ANGULAR_NO_OPTIMIZATION': 'info',
            'ANGULAR_JSON_ERROR': 'error',
            'TEXT_TODO_FIXME': 'info',
            'TEXT_POTENTIAL_SECRET': 'warning',
            'TEXT_DEBUG_FLAG': 'info',
            'NETWORK_ERROR': 'info',
            'ROBOTS_DISALLOW': 'info',
            'SEC_INSECURE_REQUEST': 'warning',
            'SEC_INLINE_SCRIPT': 'warning',
            'SEC_INLINE_STYLE': 'warning',
            'PERF_LARGE_FILE': 'warning',
            'CSS_UNUSED_SELECTOR': 'info',
            'JS_DANGEROUS_FUNCTION': 'warning',
        }
        severity = severity_map.get(issue_type, 'Info')
    return {
        'type': issue_type,
        'location': location,
        'message': message,
        'severity': severity,
        'line': line,
        'context': context,
        'column': column
    }

# --- Helper to find line number in HTML ---
def find_line_number_in_html(raw_html, tag_str):
    idx = raw_html.find(tag_str)
    if idx == -1:
        return '-'
    return raw_html[:idx].count('\n') + 1

# --- Helper to find line number in JS/JSX/TSX ---
def find_line_number_in_js(js_content, pattern):
    for i, line in enumerate(js_content.splitlines(), 1):
        if re.search(pattern, line):
            return i
    return '-'

# --- Helper to find line number in any text file ---
def find_line_number_in_text(content, pattern_or_snippet):
    """Return the first line number (1-based) where pattern_or_snippet appears, or '-' if not found."""
    for i, line in enumerate(content.splitlines(), 1):
        if pattern_or_snippet in line or (hasattr(pattern_or_snippet, 'search') and pattern_or_snippet.search(line)):
            return i
    return '-'

# --- Advanced SEO and HTML Performance ---
def analyze_html_content(content, location, options, raw_html=None):
    issues = []
    soup = BeautifulSoup(content, 'html.parser')
    raw_html = raw_html or content
    # For line number, use the raw HTML
    # SEO: canonical
    if not soup.find('link', rel='canonical'):
        issues.append(make_issue('SEO_MISSING_CANONICAL', location, 'Missing canonical tag', line=find_line_number_in_text(raw_html, '<link rel="canonical"')))
    # SEO: Open Graph/Twitter
    if not soup.find('meta', property='og:title'):
        issues.append(make_issue('SEO_MISSING_OG', location, 'Missing Open Graph meta', line=find_line_number_in_text(raw_html, '<meta property="og:title"')))
    if not soup.find('meta', attrs={'name': 'twitter:card'}):
        issues.append(make_issue('SEO_MISSING_TWITTER', location, 'Missing Twitter meta', line=find_line_number_in_text(raw_html, '<meta name="twitter:card"')))
    # SEO: robots meta
    if not soup.find('meta', attrs={'name': 'robots'}):
        issues.append(make_issue('SEO_MISSING_ROBOTS', location, 'Missing robots meta', line=find_line_number_in_text(raw_html, '<meta name="robots"')))
    # SEO: sitemap
    if not soup.find('link', rel='sitemap'):
        issues.append(make_issue('SEO_MISSING_SITEMAP', location, 'Missing sitemap link', line=find_line_number_in_text(raw_html, '<link rel="sitemap"')))
    # SEO: structured data
    if not soup.find('script', type='application/ld+json'):
        issues.append(make_issue('SEO_MISSING_STRUCTURED', location, 'Missing JSON-LD structured data', line=find_line_number_in_text(raw_html, '<script type="application/ld+json"')))
    # SEO: microdata
    if not soup.find(attrs={'itemscope': True}):
        issues.append(make_issue('SEO_MISSING_MICRODATA', location, 'Missing microdata', line=find_line_number_in_text(raw_html, '<itemscope')))
    # Performance: large images, missing loading=lazy
    for img in soup.find_all('img'):
        src = img.get('src')
        if src and (src.startswith('http') or src.startswith('data:image')):
            if is_large_image(src, content):
                issues.append(make_issue('HTML_LARGE_IMAGE', location, f'Large image: {src}', line=find_line_number_in_text(raw_html, str(img))))
        if not img.get('loading') == 'lazy':
            issues.append(make_issue('HTML_IMG_NO_LAZY', location, f'Image missing loading=lazy: {src}', line=find_line_number_in_text(raw_html, str(img))))
    # Performance: unminified inline scripts/styles
    for script in soup.find_all('script', src=False):
        if script.string and not is_minified(script.string):
            issues.append(make_issue('HTML_UNMINIFIED_INLINE_SCRIPT', location, 'Unminified inline script', line=find_line_number_in_text(raw_html, str(script))))
    for style in soup.find_all('style'):
        if style.string and not is_minified(style.string):
            issues.append(make_issue('HTML_UNMINIFIED_INLINE_STYLE', location, 'Unminified inline style', line=find_line_number_in_text(raw_html, str(style))))
    # Deprecated tags
    deprecated_tags = ['center', 'font', 'marquee']
    for tag in deprecated_tags:
        for found in soup.find_all(tag):
            issues.append(make_issue('HTML_DEPRECATED_TAG', location, f"Deprecated HTML tag <{tag}> used", line=find_line_number_in_text(raw_html, str(found))))
    # Accessibility: missing aria (skip)
    # Accessibility: label/input (skip)
    # Accessibility: heading order (skip)
    # SEO: title, meta description, h1 count
    if not soup.find('title'):
        issues.append(make_issue('SEO_MISSING_TITLE', location, "Missing <title> tag", line=find_line_number_in_text(raw_html, '<title>')))
    if not soup.find('meta', attrs={'name': 'description'}):
        issues.append(make_issue('SEO_MISSING_DESCRIPTION', location, "Missing meta description", line=find_line_number_in_text(raw_html, '<meta name="description"')))
    h1s = soup.find_all('h1')
    if len(h1s) == 0:
        issues.append(make_issue('SEO_MISSING_H1', location, "No <h1> tag found", line=find_line_number_in_text(raw_html, '<h1>')))
    elif len(h1s) > 1:
        issues.append(make_issue('SEO_MULTIPLE_H1', location, "Multiple <h1> tags found", line=find_line_number_in_text(raw_html, '<h1>')))
    # Broken links
    for a in soup.find_all('a', href=True):
        href = a['href']
        if not is_absolute(href):
            continue  # skip local links in repo mode
        try:
            r = requests.head(href, allow_redirects=True, timeout=5)
            if r.status_code >= 400:
                issues.append(make_issue('HTML_BROKEN_LINK', href, f"Broken link: {r.status_code}", line=find_line_number_in_text(raw_html, str(a))))
        except Exception as e:
            issues.append(make_issue('HTML_BROKEN_LINK', href, f"Broken link: {str(e)}", line=find_line_number_in_text(raw_html, str(a))))
    for img in soup.find_all('img', src=True):
        src = img['src']
        if not is_absolute(src):
            continue
        try:
            r = requests.head(src, allow_redirects=True, timeout=5)
            if r.status_code >= 400:
                issues.append(make_issue('HTML_BROKEN_IMG', src, f"Broken image: {r.status_code}", line=find_line_number_in_text(raw_html, str(img))))
        except Exception as e:
            issues.append(make_issue('HTML_BROKEN_IMG', src, f"Broken image: {str(e)}", line=find_line_number_in_text(raw_html, str(img))))
    return issues

# --- Advanced CSS Analysis ---
def css_specificity(selector):
    # Simple specificity calculation: (IDs, classes, elements)
    id_count = selector.count('#')
    class_count = selector.count('.') + selector.count('[')
    element_count = len(re.findall(r'\b[a-zA-Z]+\b', selector))
    return (id_count, class_count, element_count)

def analyze_css_content(content, location, options, raw_content=None):
    issues = []
    raw_content = raw_content or content
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
                    issues.append(make_issue('CSS_SPECIFICITY_WAR', location, f'Selector {selector} has high specificity {spec}', line=find_line_number_in_text(raw_content, str(rule))))
                # Deep selectors
                if selector.count(' ') > 4:
                    issues.append(make_issue('CSS_DEEP_SELECTOR', location, f'Deep selector: {selector}', line=find_line_number_in_text(raw_content, str(rule))))
                # Use of IDs
                if '#' in selector:
                    issues.append(make_issue('CSS_ID_SELECTOR', location, f'ID selector: {selector}', line=find_line_number_in_text(raw_content, str(rule))))
                # Non-standard properties
                for prop in rule.style:
                    if prop.name.startswith('-') and not prop.name.startswith('--'):
                        issues.append(make_issue('CSS_NONSTANDARD_PROPERTY', location, f'Non-standard property: {prop.name}', line=find_line_number_in_text(raw_content, str(rule))))
                # !important
                for prop in rule.style:
                    if '!important' in prop.value:
                        issues.append(make_issue('CSS_IMPORTANT_OVERUSE', location, "Use of !important in CSS", line=find_line_number_in_text(raw_content, str(rule))))
                # Selector depth
                if options.max_selector_depth is not None:
                    depth = max(selector.count(' '), selector.count('>'))
                    if depth > options.max_selector_depth:
                        issues.append(make_issue('CSS_COMPLEX_SELECTOR', location, f"Overly complex selector: {selector}", line=find_line_number_in_text(raw_content, str(rule))))
                # Duplicate selectors
                if selector in selectors_seen:
                    issues.append(make_issue('CSS_DUPLICATE_SELECTOR', location, f"Duplicate selector: {selector}", line=find_line_number_in_text(raw_content, str(rule))))
                selectors_seen.add(selector)
                # Track selectors for unused check
                self.used_selectors.add(selector)
        # Large file
        if len(content) > 100*1024:
            issues.append(make_issue('CSS_LARGE_FILE', location, f'CSS file > 100KB', line=find_line_number_in_text(raw_content, '/*')))
        # Excessive @import
        if content.count('@import') > 3:
            issues.append(make_issue('CSS_EXCESSIVE_IMPORT', location, 'Excessive @import usage', line=find_line_number_in_text(raw_content, '/*')))
        # Non-minified CSS
        if not is_minified(content):
            issues.append(make_issue('CSS_UNMINIFIED', location, 'Non-minified CSS', line=find_line_number_in_text(raw_content, '/*')))
        # Specificity graph (optional: print or save as CSV/JSON)
        # ...
    except Exception as e:
        issues.append(make_issue('CSS_PARSING_ERROR', location, f"CSS parsing error: {str(e)}", line=find_line_number_in_text(raw_content, '/*')))
    return issues

# --- Advanced JS Analysis ---
def analyze_js_content(content, location, options, raw_content=None):
    issues = []
    raw_content = raw_content or content
    try:
        pyjsparser.parse(content)
    except Exception as e:
        issues.append(make_issue('JS_SYNTAX_ERROR', location, f"Syntax error: {str(e)}", line=find_line_number_in_text(raw_content, '/*')))
    # Deprecated APIs
    deprecated_apis = ['escape(', 'unescape(', 'document.all', 'document.layers']
    for api in deprecated_apis:
        if api in content:
            issues.append(make_issue('JS_DEPRECATED_API', location, f"Deprecated API used: {api}", line=find_line_number_in_text(raw_content, api)))
    # Performance: large bundles
    if len(content) > 200*1024:
        issues.append(make_issue('JS_LARGE_BUNDLE', location, 'JS file > 200KB', line=find_line_number_in_text(raw_content, '/*')))
    # Synchronous XHR
    if re.search(r'open\s*\(\s*["\"][A-Z]+["\"]\s*,\s*[^,]+,\s*false', content):
        issues.append(make_issue('JS_SYNC_XHR', location, 'Synchronous XHR detected', line=find_line_number_in_text(raw_content, '/*')))
    # Blocking scripts
    if 'document.write' in content:
        issues.append(make_issue('JS_BLOCKING_SCRIPT', location, 'document.write used', line=find_line_number_in_text(raw_content, '/*')))
    # Unused code: (not trivial, skip for now)
    # Modern syntax: (warn if ES6+ features detected)
    if re.search(r'=>|const |let |\bclass\b|\bimport\b|\bexport\b', content):
        issues.append(make_issue('JS_MODERN_SYNTAX', location, 'Modern JS syntax detected', line=find_line_number_in_text(raw_content, '/*')))
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
                        issues.append(make_issue('JS_ESLINT', location, f"{msg.get('message')} (rule: {msg.get('ruleId')})", line=find_line_number_in_text(raw_content, msg.get('line'))))
            os.remove('temp_eslint.js')
        except Exception as e:
            issues.append(make_issue('JS_ESLINT_ERROR', location, f"ESLint error: {str(e)}", line=find_line_number_in_text(raw_content, '/*')))
    return issues

# --- Dependency & Config Analysis ---
def analyze_package_json(path, raw_content=None):
    issues = []
    raw_content = raw_content or path
    try:
        with open(path, encoding='utf-8') as f:
            pkg = json.load(f)
        # Outdated/vulnerable/deprecated dependencies (basic: just warn if any dependency is pinned to old version)
        for dep_type in ['dependencies', 'devDependencies']:
            for dep, ver in pkg.get(dep_type, {}).items():
                if re.match(r'^[<>=~]?\d+\.\d+\.\d+$', ver) and ver.startswith(('0.', '1.0.', '2.0.')):
                    issues.append(make_issue('PKG_OLD_DEP', path, f'{dep} version {ver} may be outdated', line=find_line_number_in_text(raw_content, '/*')))
                if 'deprecated' in dep.lower():
                    issues.append(make_issue('PKG_DEPRECATED_DEP', path, f'{dep} is deprecated', line=find_line_number_in_text(raw_content, '/*')))
        # TODO: Integrate with npm audit or Snyk for real vulnerability scan
    except Exception as e:
        issues.append(make_issue('PKG_PARSE_ERROR', path, f'package.json parse error: {str(e)}', line=find_line_number_in_text(raw_content, '/*')))
    return issues

def analyze_env_file(path, raw_content=None):
    issues = []
    raw_content = raw_content or path
    try:
        with open(path, encoding='utf-8') as f:
            for line in f:
                if re.search(r'(key|token|secret|password|api)[^=]*=', line, re.I):
                    issues.append(make_issue('ENV_POTENTIAL_SECRET', path, f'Potential secret: {line.strip()}', line=find_line_number_in_text(raw_content, line)))
    except Exception as e:
        issues.append(make_issue('ENV_PARSE_ERROR', path, f'.env parse error: {str(e)}', line=find_line_number_in_text(raw_content, '/*')))
    return issues

# --- Advanced Reporting ---
# --- Solutions for Issues ---
ISSUE_SOLUTIONS = {
    'NETWORK_ERROR': lambda issue: (
        f"If the resource is required, ensure it exists at the specified URL: <code>{html.escape(str(issue.get('location', '')))}</code>. For robots.txt, create one at the site root if you want to control crawler access. Otherwise, you can ignore this warning."
    ),
    'HTML_MISSING_ALT': lambda issue: (
        f"Add a descriptive alt attribute to the image: <br><code>{html.escape(str(issue.get('location', ''))).replace('>', ' alt=\"describe image here\">')}</code>"
    ),
    'HTML_MISSING_ARIA': lambda issue: (
        f"Add an appropriate aria-label or aria-* attribute to the link: <br><code>{html.escape(str(issue.get('location', ''))).replace('>', ' aria-label=\"describe link purpose\">')}</code>"
    ),
    'HTML_HEADING_ORDER': lambda issue: (
        f"Check heading order near: <code>{html.escape(str(issue.get('location', '')))}</code>. Use headings in order (e.g., <h2> should not be followed by <h4> without an <h3> in between)."
    ),
    'SEO_MISSING_DESCRIPTION': lambda issue: (
        f"Add a meta description to your <head>: <br><code>&lt;meta name=\"description\" content=\"A brief description of your page.\"&gt;</code>"
    ),
    'HTML_BROKEN_LINK': lambda issue: (
        f"Fix or remove the broken hyperlink: <code>{html.escape(str(issue.get('location', '')))}</code>. For <code>javascript:void(0);</code>, use <code>href=\"#\"</code> and prevent default action in JS. For 404/405 errors, ensure the link points to a valid resource."
    ),
    'CSS_COMPLEX_SELECTOR': lambda issue: (
        f"Simplify this overly complex CSS selector: <br><code>{html.escape(str(issue.get('message', '')))}</code>"
    ),
    'CSS_VENDOR_PREFIX': lambda issue: (
        f"Vendor prefix used: <code>{html.escape(str(issue.get('message', '')))}</code>. Use vendor prefixes only when necessary for browser compatibility. Consider using Autoprefixer to automate this."
    ),
    'CSS_DUPLICATE_SELECTOR': lambda issue: (
        f"Remove or merge duplicate CSS selector: <code>{html.escape(str(issue.get('message', '')))}</code> to avoid redundancy."
    ),
    'CSS_UNUSED_SELECTOR': lambda issue: (
        f"Remove unused selector: <code>{html.escape(str(issue.get('message', '')))}</code> if not used in your HTML."
    ),
    'JS_SYNTAX_ERROR': lambda issue: (
        f"Fix JavaScript syntax errors. Example: <br><code>{html.escape(str(issue.get('message', '')))}</code><br>Use ES5-compatible syntax or transpile your JS with Babel for older browser support. Replace arrow functions with function expressions if needed."
    ),
    'SEC_INSECURE_REQUEST': lambda issue: (
        f"Insecure HTTP resource: <code>{html.escape(str(issue.get('location', '')))}</code>. Use <code>https://</code> for all external resources (CSS, JS, images) to avoid mixed content warnings."
    ),
    'SEC_INLINE_SCRIPT': lambda issue: (
        f"Move large inline scripts to external <code>.js</code> files for better caching and security."
    ),
    'SEC_INLINE_STYLE': lambda issue: (
        f"Move large inline styles to external <code>.css</code> files for better caching and security."
    ),
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
        html_lines = []
        html_lines.append("""<!DOCTYPE html>
<html lang='en'>
<head>
<meta charset='UTF-8'>
<title>Static Analysis Report</title>
<meta name='viewport' content='width=device-width, initial-scale=1'>
<link rel='preconnect' href='https://fonts.googleapis.com'>
<link rel='preconnect' href='https://fonts.gstatic.com' crossorigin>
<link href='https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700&display=swap' rel='stylesheet'>
<script src='https://cdn.jsdelivr.net/npm/chart.js'></script>
<style>
body { font-family: 'Inter', 'Segoe UI', Arial, sans-serif; background: #f4f6fa; margin: 0; padding: 0; }
.header-bar { background: linear-gradient(90deg, #8a2be2 0%, #4f8cff 100%); color: #fff; padding: 24px 0 16px 0; box-shadow: 0 2px 12px rgba(138,43,226,0.08); text-align: center; }
.header-bar h1 { margin: 0; font-size: 2.2rem; font-weight: 700; letter-spacing: 1px; }
.container { max-width: 1200px; margin: 32px auto; background: #fff; border-radius: 18px; box-shadow: 0 4px 32px rgba(138,43,226,0.10); padding: 36px 24px 32px 24px; }
#charts { display: flex; gap: 24px; margin-bottom: 32px; justify-content: center; flex-wrap: wrap; }
#charts canvas { background: #fff; border-radius: 12px; box-shadow: 0 2px 12px rgba(79,140,255,0.10); padding: 8px; width: 220px !important; height: 120px !important; max-width: 100vw; }
#filter-bar { margin-bottom: 22px; display: flex; gap: 18px; flex-wrap: wrap; align-items: center; }
#filter-bar label { margin-right: 0; font-weight: 600; color: #4f4f6f; }
#filter-bar select { border-radius: 6px; border: 1px solid #d1d5db; padding: 6px 14px; font-size: 1em; background: #f8f9fb; color: #333; transition: border 0.2s; }
#filter-bar select:focus { border: 1.5px solid #8a2be2; outline: none; }
.copy-btn { background: linear-gradient(90deg, #8a2be2 0%, #4f8cff 100%); border: none; border-radius: 6px; padding: 6px 16px; cursor: pointer; margin-left: 8px; font-size: 1em; color: #fff; font-weight: 600; transition: background 0.2s; box-shadow: 0 1px 4px rgba(138,43,226,0.08); }
.copy-btn:hover { background: linear-gradient(90deg, #4f8cff 0%, #8a2be2 100%); }
.table-wrap { margin-top: 32px; border-radius: 16px; box-shadow: 0 2px 16px rgba(79,140,255,0.10); border: 1.5px solid #e1e4e8; overflow-x: auto; background: #f8f9fb; }
table { width: 100%; border-collapse: separate; border-spacing: 0; font-size: 1.01em; border-radius: 16px; overflow: hidden; min-width: 900px; }
th, td { padding: 13px 10px; border-bottom: 1px solid #e1e4e8; text-align: left; }
th { background: linear-gradient(90deg, #8a2be2 0%, #4f8cff 100%); color: #fff; font-size: 1.08em; font-weight: 700; border-top-left-radius: 16px; border-top-right-radius: 16px; position: sticky; top: 0; z-index: 2; letter-spacing: 0.5px; }
tr { transition: background 0.18s, transform 0.18s; }
tr:nth-child(even) { background: linear-gradient(90deg, #f8f9fb 0%, #f4f6fa 100%); }
tr:nth-child(odd) { background: #fff; }
tr:hover { background: #e6eaff; transform: scale(1.012); box-shadow: 0 2px 8px rgba(79,140,255,0.08); }
th:first-child { border-top-left-radius: 16px; }
th:last-child { border-top-right-radius: 16px; }
td { font-size: 0.99em; }
.severity-LOW { color: #3498db; }
.severity-MEDIUM { color: #f39c12; }
.severity-HIGH { color: #e74c3c; font-weight: bold; }
.severity-CRITICAL { color: #c0392b; font-weight: bold; }
.solution { color: #16a085; font-size: 0.98em; }
.autofix { color: #8e44ad; font-size: 0.97em; font-family: monospace; background: #f8f6ff; border-radius: 4px; padding: 4px 8px; display: block; margin-top: 4px; }
.code-context { color: #2d3436; font-size: 0.97em; font-family: monospace; background: #f4f4f4; border-radius: 4px; padding: 4px 8px; display: block; margin-top: 4px; white-space: pre; }
.code-highlight { background: #ffeaa7; color: #d35400; font-weight: bold; }
.caret-highlight { color: #d35400; font-weight: bold; }
details code { background: none; padding: 0; }
@media (max-width: 900px) {
  .container { padding: 12px 2vw; }
  #charts { flex-direction: column; gap: 12px; }
  #charts canvas { width: 98vw !important; max-width: 100vw; height: 120px !important; }
  .table-wrap { margin-top: 18px; }
  table, thead, tbody, th, td, tr { font-size: 0.97em; }
  th, td { padding: 8px 4px; }
}
@media (max-width: 600px) {
  .header-bar h1 { font-size: 1.3rem; }
  .container { padding: 2vw 1vw; }
  #charts canvas { width: 98vw !important; max-width: 100vw; height: 100px !important; }
  .table-wrap { margin-top: 10px; }
  table, thead, tbody, th, td, tr { font-size: 0.93em; }
}
</style>
</head>
<body>
<div class='header-bar'><h1>Static Analysis Report</h1></div>
<div class='container'>
<div id='charts'>
  <canvas id='typeChart' width='220' height='120'></canvas>
  <canvas id='severityChart' width='220' height='120'></canvas>
</div>
<div id='filter-bar'>
  <label>Filter by Type: <select id='typeFilter'><option value=''>All</option></select></label>
  <label>Filter by Severity: <select id='severityFilter'><option value=''>All</option></select></label>
</div>
<div class='table-wrap'>
<table id='issues-table'>
<thead><tr><th>#</th><th>Type</th><th>Location</th><th>Severity</th><th>Line</th><th>Code Context</th><th>Message</th><th>Solution</th><th>Auto-fix Suggestion</th></tr></thead>
<tbody>""")
        # --- Auto-fix suggestion lambdas ---
        AUTO_FIX = {
            'HTML_MISSING_ALT': lambda issue: (
                html.escape(str(issue['location'])).replace('>', ' alt="describe image here">')
            ),
            'HTML_MISSING_ARIA': lambda issue: (
                html.escape(str(issue['location'])).replace('>', ' aria-label="describe link purpose">')
            ),
            'SEO_MISSING_DESCRIPTION': lambda issue: (
                '&lt;meta name="description" content="A brief description of your page."&gt;'
            ),
            'HTML_BROKEN_LINK': lambda issue: (
                str(issue['location']).startswith('javascript:void(0)')
                and '<a href="#" onclick="event.preventDefault();">...</a>'
                or f'Check/fix: {html.escape(str(issue["location"]))}'
            ),
            'CSS_COMPLEX_SELECTOR': lambda issue: (
                '/* Simplify selector: */\n' + html.escape(str(issue['message']))
            ),
            'CSS_DUPLICATE_SELECTOR': lambda issue: (
                '/* Remove duplicate selector: */\n' + html.escape(str(issue['message']))
            ),
            'CSS_UNUSED_SELECTOR': lambda issue: (
                '/* Remove unused selector: */\n' + html.escape(str(issue['message']))
            ),
            'JS_SYNTAX_ERROR': lambda issue: (
                '/* Replace with ES5 function: */\nfunction foo() { ... }'
            ),
        }

        def highlight_code_context(context, col):
            if not context:
                return ''
            if col and str(col).isdigit():
                col = int(col)
                if 1 <= col <= len(context):
                    # Highlight the character at col (1-based)
                    before = html.escape(context[:col-1])
                    highlight = f'<span class="code-highlight">{html.escape(context[col-1])}</span>'
                    after = html.escape(context[col:])
                    caret = f'<br><span class="caret-highlight">{"&nbsp;"*(col-1)}^</span>'
                    return before + highlight + after + caret
            # If context is long, use <details>
            if len(context) > 80:
                return f'<details><summary>Show code</summary><code>{html.escape(context)}</code></details>'
            return html.escape(context)

        for i, issue in enumerate(issues, 1):
            if isinstance(issue, dict):
                issue_type = issue.get('type', '')
                location = issue.get('location', '')
                message = issue.get('message', '')
                line = issue.get('line', 'N/A')
                code_context = issue.get('context', '')
                col = issue.get('column', '')
                severity = issue.get('severity', 'Info')
                # --- Make location clickable ---
                if location.startswith('http://') or location.startswith('https://'):
                    location_html = f'<a href="{html.escape(location)}" target="_blank">{html.escape(location)}</a>'
                elif location and line != 'N/A' and str(location).endswith(('.js', '.jsx', '.ts', '.tsx', '.html', '.css', '.py', '.php', '.json', '.md', '.txt', '.log')):
                    abs_path = os.path.abspath(location)
                    # VS Code URI scheme
                    location_html = f'<a href="vscode://file/{abs_path}:{line}" title="Open in VS Code">{html.escape(location)}:{line}</a>'
                elif location:
                    location_html = html.escape(location)
                else:
                    location_html = '-'
            elif isinstance(issue, (list, tuple)) and len(issue) >= 3:
                issue_type, location, message = issue[:3]
                line = issue[3] if len(issue) > 3 else '-'
                code_context = issue[4] if len(issue) > 4 else ''
                col = issue[5] if len(issue) > 5 else ''
                severity = 'Info'
                issue = {'type': issue_type, 'location': location, 'message': message, 'line': line, 'context': code_context, 'column': col, 'severity': severity}
                # --- Make location clickable ---
                if location.startswith('http://') or location.startswith('https://'):
                    location_html = f'<a href="{html.escape(location)}" target="_blank">{html.escape(location)}</a>'
                elif location and line != 'N/A' and str(location).endswith(('.js', '.jsx', '.ts', '.tsx', '.html', '.css', '.py', '.php', '.json', '.md', '.txt', '.log')):
                    abs_path = os.path.abspath(location)
                    # VS Code URI scheme
                    location_html = f'<a href="vscode://file/{abs_path}:{line}" title="Open in VS Code">{html.escape(location)}:{line}</a>'
                elif location:
                    location_html = html.escape(location)
                else:
                    location_html = '-'
            else:
                issue_type = str(issue)
                location = ''
                message = ''
                line = '-'
                code_context = ''
                col = ''
                severity = 'Info'
                issue = {'type': issue_type, 'location': location, 'message': message, 'line': line, 'context': code_context, 'column': col, 'severity': severity}
                # --- Make location clickable ---
                if location.startswith('http://') or location.startswith('https://'):
                    location_html = f'<a href="{html.escape(location)}" target="_blank">{html.escape(location)}</a>'
                elif location and line != 'N/A' and str(location).endswith(('.js', '.jsx', '.ts', '.tsx', '.html', '.css', '.py', '.php', '.json', '.md', '.txt', '.log')):
                    abs_path = os.path.abspath(location)
                    # VS Code URI scheme
                    location_html = f'<a href="vscode://file/{abs_path}:{line}" title="Open in VS Code">{html.escape(location)}:{line}</a>'
                elif location:
                    location_html = html.escape(location)
                else:
                    location_html = '-'
            solution = ISSUE_SOLUTIONS.get(issue_type, lambda i: 'Refer to documentation or best practices for this issue.')(issue)
            autofix = AUTO_FIX.get(issue_type, lambda i: '')(issue)
            code_html = highlight_code_context(code_context, col)
            html_lines.append(
                f"<tr>"
                f"<td>{i}</td>"
                f"<td>{html.escape(str(issue_type))}</td>"
                f"<td>{location_html}</td>"
                f"<td class='severity-{severity.upper()}'>{severity.title()}</td>"
                f"<td>{line}</td>"
                f"<td class='code-context'>{code_html}</td>"
                f"<td>{html.escape(str(message))}</td>"
                f"<td class='solution'>{solution}</td>"
                f"<td class='autofix'>{autofix}</td>"
                f"</tr>"
            )
        html_lines.append("""
</tbody></table>
</div>
<script>
// --- Chart.js Data ---
const issues = """ + json.dumps(issues) + """;
issues = issues.map(issue => {
  if (!issue.type || issue.type === 'undefined') issue.type = 'Other';
  if (!issue.severity || issue.severity === 'undefined') issue.severity = 'Info';
  return issue;
});
const typeCounts = {};
const severityCounts = {};
issues.forEach(issue => {
  typeCounts[issue.type] = (typeCounts[issue.type]||0)+1;
  severityCounts[issue.severity] = (severityCounts[issue.severity]||0)+1;
});
const typeLabels = Object.keys(typeCounts).filter(l=>l!=='undefined');
const typeData = typeLabels.map(l=>typeCounts[l]);
const severityLabels = Object.keys(severityCounts).filter(l=>l!=='undefined');
const severityData = severityLabels.map(l=>severityCounts[l]);
new Chart(document.getElementById('typeChart').getContext('2d'), {
  type: 'bar', data: {labels: typeLabels, datasets: [{label: 'Issues by Type', data: typeData, backgroundColor: '#8a2be2'}]}, options: {plugins: {legend: {display: false}}}
});
new Chart(document.getElementById('severityChart').getContext('2d'), {
  type: 'pie', data: {labels: severityLabels, datasets: [{label: 'Issues by Severity', data: severityData, backgroundColor: ['#e67e22','#e74c3c','#f1c40f','#2ecc71','#3498db']}]}, options: {plugins: {legend: {position: 'bottom'}}}
});
// --- Filtering ---
const typeFilter = document.getElementById('typeFilter');
const severityFilter = document.getElementById('severityFilter');
issues.forEach(issue => {
  if(issue.type && issue.type !== 'undefined' && ![...typeFilter.options].some(o=>o.value===issue.type)){
    let opt=document.createElement('option'); opt.value=issue.type; opt.text=issue.type; typeFilter.appendChild(opt);
  }
  if(issue.severity && issue.severity !== 'undefined' && ![...severityFilter.options].some(o=>o.value===issue.severity)){
    let opt=document.createElement('option'); opt.value=issue.severity; opt.text=issue.severity; severityFilter.appendChild(opt);
  }
});
function filterTable(){
  let t=typeFilter.value, s=severityFilter.value;
  document.querySelectorAll('#issues-table tbody tr').forEach(row=>{
    let type=row.getAttribute('data-type'), sev=row.getAttribute('data-severity');
    row.classList[(t&&type!==t)||(s&&sev!==s)?'add':'remove']('hide');
  });
}
typeFilter.onchange=severityFilter.onchange=filterTable;
// --- Copy Auto-fix ---
document.querySelectorAll('.copy-btn').forEach(btn=>{
  btn.onclick=function(){
    let code=this.previousElementSibling.textContent;
    navigator.clipboard.writeText(code);
    this.textContent='Copied!';
    setTimeout(()=>this.textContent='Copy Auto-fix',1200);
  };
});
</script>
</body></html>""")
        print('\n'.join(html_lines))
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
                        issues.append(make_issue('REACT_ESLINT' if ext in ['.jsx', '.tsx'] else 'TS_ESLINT', location, f"{msg.get('message')} (rule: {msg.get('ruleId')})", line=find_line_number_in_text(content, msg.get('line'))))
            os.remove(temp_file)
        except Exception as e:
            issues.append(make_issue('ESLINT_ERROR', location, f"ESLint error: {str(e)}", line=find_line_number_in_text(content, '/*')))
    # Heuristic checks for React
    if 'React.Component' in content or 'useState' in content or 'useEffect' in content:
        if re.search(r'<\w+\s+key=[^\s>]+', content) is None and re.search(r'\.map\(', content):
            pattern = r'\.map\('
            line = find_line_number_in_text(content, pattern)
            issues.append(make_issue('REACT_MISSING_KEY', location, 'Missing key prop in list rendering', line=line))
        if re.search(r'componentWillMount|componentWillReceiveProps|componentWillUpdate', content):
            issues.append(make_issue('REACT_DEPRECATED_LIFECYCLE', location, 'Deprecated lifecycle method used', line=find_line_number_in_text(content, '/*')))
        if re.search(r'document\.getElementById|document\.querySelector', content):
            issues.append(make_issue('REACT_DIRECT_DOM', location, 'Direct DOM manipulation in React', line=find_line_number_in_text(content, '/*')))
    # Heuristic checks for Angular
    if '@Component' in content or 'NgModule' in content:
        if re.search(r'\*ngFor(?!.*trackBy)', content):
            issues.append(make_issue('ANGULAR_MISSING_TRACKBY', location, 'Missing trackBy in *ngFor', line=find_line_number_in_text(content, '/*')))
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
                # Extract line/col if possible
                m = re.match(r'^(\d+):(\d+): ([A-Z]\d+) (.*)$', line)
                if m:
                    row, col, code, text = m.groups()
                    issues.append(make_issue('PY_FLAKE8', location, f'{code} {text}', line=row, column=col))
                else:
                    issues.append(make_issue('PY_FLAKE8', location, line, line=find_line_number_in_text(content, line)))
        os.remove(temp_file)
    except Exception as e:
        issues.append(make_issue('PY_FLAKE8_ERROR', location, f'flake8 error: {str(e)}', line=find_line_number_in_text(content, '/*')))
    # Flask-specific
    if 'Flask(' in content:
        if 'debug=True' in content:
            issues.append(make_issue('FLASK_DEBUG_MODE', location, 'Flask debug mode enabled', line=find_line_number_in_text(content, '/*')))
        if 'SECRET_KEY' in content and re.search(r'SECRET_KEY\s*=\s*["\"][^"\"]+["\"]', content):
            issues.append(make_issue('FLASK_HARDCODED_SECRET', location, 'Hardcoded Flask SECRET_KEY', line=find_line_number_in_text(content, '/*')))
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
            issues.append(make_issue('PHP_PARSE_ERROR', location, result.stdout + result.stderr, line=find_line_number_in_text(content, '/*')))
        os.remove(temp_file)
    except Exception as e:
        issues.append(make_issue('PHP_LINT_ERROR', location, f'php -l error: {str(e)}', line=find_line_number_in_text(content, '/*')))
    # Heuristic checks
    if 'eval(' in content:
        issues.append(make_issue('PHP_EVAL', location, 'Use of eval()', line=find_line_number_in_text(content, '/*')))
    if re.search(r'mysql_\w+\(', content):
        issues.append(make_issue('PHP_MYSQL_DEPRECATED', location, 'Use of deprecated mysql_* functions', line=find_line_number_in_text(content, '/*')))
    if re.search(r'\$_(GET|POST|REQUEST|COOKIE)\[', content) and not re.search(r'htmlspecialchars|filter_var', content):
        issues.append(make_issue('PHP_UNVALIDATED_INPUT', location, 'Potential unvalidated input', line=find_line_number_in_text(content, '/*')))
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
                        issues.append(make_issue('ANGULAR_NO_OPTIMIZATION', location, f'Angular project {proj} has optimization disabled', line=find_line_number_in_text(content, '/*')))
    except Exception as e:
        issues.append(make_issue('ANGULAR_JSON_ERROR', location, f'angular.json parse error: {str(e)}', line=find_line_number_in_text(content, '/*')))
    return issues

# --- Analyze generic text files for common issues ---
def analyze_text_file(content, location, options):
    issues = []
    patterns = [
        (re.compile(r'TODO|FIXME', re.I), 'TODO or FIXME found', 'TEXT_TODO_FIXME'),
        (re.compile(r'(password|secret|token|key)[^=]*=', re.I), 'Possible secret or password assignment', 'TEXT_POTENTIAL_SECRET'),
        (re.compile(r'\bdebug\b', re.I), 'Debug flag found', 'TEXT_DEBUG_FLAG'),
    ]
    for i, line in enumerate(content.splitlines(), 1):
        for pattern, msg, issue_type in patterns:
            if pattern.search(line):
                issues.append(make_issue(issue_type, location, msg, line=i, context=line.strip()))
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
                    issues += analyze_html_content(content, path, options, content)
                elif ext in ['.css'] and options.css:
                    issues += analyze_css_content(content, path, options, content)
                elif ext in ['.js'] and options.js:
                    issues += analyze_js_content(content, path, options, content)
                elif ext in ['.jsx', '.tsx', '.ts'] and options.js:
                    issues += analyze_jsx_tsx_content(content, path, options)
                elif ext == '.py':
                    issues += analyze_python_content(content, path, options)
                elif ext == '.php':
                    issues += analyze_php_content(content, path, options)
                elif file == 'package.json':
                    issues += analyze_package_json(path, content)
                elif file == '.env':
                    issues += analyze_env_file(path, content)
                elif file == 'angular.json':
                    issues += analyze_angular_json_content(content, path, options)
                elif ext in ['.txt', '.md', '.log']:
                    issues += analyze_text_file(content, path, options)
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
            self.issues.append(make_issue('NETWORK_ERROR', url, str(e), line=get_line_for_network_error(self.html_content, url)))
            return None

    def _check_robots_txt(self):
        if self.options.ignore_robots:
            return
        robots_url = f"{self.base_url}/robots.txt"
        robots = self._fetch_url(robots_url)
        if robots and "User-agent: *" in robots and "Disallow: /" in robots:
            self.issues.append(make_issue('ROBOTS_DISALLOW', robots_url, "Blocked by robots.txt", line=find_line_number_in_text(robots, "Disallow: /")))

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
                tag_str = str(img)
                line = find_line_number_in_text(self.html_content, tag_str)
                self.issues.append(make_issue('HTML_MISSING_ALT', self.url, "Image missing alt text", line=line, context=tag_str))
        # Deprecated tags
        deprecated_tags = ['center', 'font', 'marquee']
        for tag in deprecated_tags:
            for found in soup.find_all(tag):
                self.issues.append(make_issue('HTML_DEPRECATED_TAG', self.url, f"Deprecated HTML tag <{tag}> used", line=find_line_number_in_text(self.html_content, str(found)), context=str(found)))
        # Accessibility: missing aria
        for el in soup.find_all(True):
            if el.name in ['button', 'input', 'a'] and not any(attr.startswith('aria-') for attr in el.attrs):
                self.issues.append(make_issue('HTML_MISSING_ARIA', self.url, f"<{el.name}> missing aria-* attribute", line=find_line_number_in_text(self.html_content, str(el)), context=str(el)))
        # Accessibility: label/input
        for inp in soup.find_all('input'):
            if not inp.get('id') or not soup.find('label', attrs={'for': inp.get('id')}):
                self.issues.append(make_issue('HTML_INPUT_NO_LABEL', self.url, "Input missing associated <label>", line=find_line_number_in_text(self.html_content, str(inp)), context=str(inp)))
        # Accessibility: heading order
        headings = [int(h.name[1]) for h in soup.find_all(re.compile('^h[1-6]$'))]
        if headings:
            prev = 0
            for h in headings:
                if prev and h > prev + 1:
                    self.issues.append(make_issue('HTML_HEADING_ORDER', self.url, "Skipped heading level", line=find_line_number_in_text(self.html_content, f"h{h}")))
                prev = h
        # SEO: title, meta description, h1 count
        if not soup.find('title'):
            self.issues.append(make_issue('SEO_MISSING_TITLE', self.url, "Missing <title> tag", line=find_line_number_in_text(self.html_content, '<title>'), context='<title>'))
        if not soup.find('meta', attrs={'name': 'description'}):
            self.issues.append(make_issue('SEO_MISSING_DESCRIPTION', self.url, "Missing meta description", line=find_line_number_in_text(self.html_content, '<meta name="description"'), context='<meta name="description"'), context='<meta name="description"')
        h1s = soup.find_all('h1')
        if len(h1s) == 0:
            self.issues.append(make_issue('SEO_MISSING_H1', self.url, "No <h1> tag found", line=find_line_number_in_text(self.html_content, '<h1>'), context='<h1>'))
        elif len(h1s) > 1:
            self.issues.append(make_issue('SEO_MULTIPLE_H1', self.url, "Multiple <h1> tags found", line=find_line_number_in_text(self.html_content, '<h1>'), context='<h1>'))
        # Broken links
        for a in soup.find_all('a', href=True):
            href = a['href']
            if not is_absolute(href):
                href = urljoin(self.base_url + '/', href)
            self.all_links.append(href)
            try:
                r = self.session.head(href, allow_redirects=True, timeout=5)
                if r.status_code >= 400:
                    self.issues.append(make_issue('HTML_BROKEN_LINK', href, f"Broken link: {r.status_code}", line=find_line_number_in_text(self.html_content, str(a)), context=str(a)))
            except Exception as e:
                self.issues.append(make_issue('HTML_BROKEN_LINK', href, f"Broken link: {str(e)}", line=find_line_number_in_text(self.html_content, str(a)), context=str(a)))
        for img in soup.find_all('img', src=True):
            src = img['src']
            if not is_absolute(src):
                src = urljoin(self.base_url + '/', src)
            try:
                r = self.session.head(src, allow_redirects=True, timeout=5)
                if r.status_code >= 400:
                    self.issues.append(make_issue('HTML_BROKEN_IMG', src, f"Broken image: {r.status_code}", line=find_line_number_in_text(self.html_content, str(img)), context=str(img)))
            except Exception as e:
                self.issues.append(make_issue('HTML_BROKEN_IMG', src, f"Broken image: {str(e)}", line=find_line_number_in_text(self.html_content, str(img)), context=str(img)))

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
                            self.issues.append(make_issue('CSS_IMPORTANT_OVERUSE', source, "Use of !important in CSS", line=find_line_number_in_text(css_content, '/*')))
                    # Selector depth
                    selector = rule.selectorText
                    if self.options.max_selector_depth is not None:
                        depth = max(selector.count(' '), selector.count('>'))
                        if depth > self.options.max_selector_depth:
                            self.issues.append(make_issue('CSS_COMPLEX_SELECTOR', source, f"Overly complex selector: {selector}", line=find_line_number_in_text(css_content, str(rule)), context=str(rule)))
                    # Vendor prefix
                    for prop in rule.style:
                        if prop.name.startswith('-webkit-') or prop.name.startswith('-moz-') or prop.name.startswith('-ms-'):
                            if not prop.name.startswith('--'):
                                self.issues.append(make_issue('CSS_VENDOR_PREFIX', source, f"Vendor prefix used: {prop.name}", line=find_line_number_in_text(css_content, str(rule)), context=str(rule)))
                    # Duplicate selectors
                    if selector in selectors_seen:
                        self.issues.append(make_issue('CSS_DUPLICATE_SELECTOR', source, f"Duplicate selector: {selector}", line=find_line_number_in_text(css_content, str(rule)), context=str(rule)))
                    selectors_seen.add(selector)
                    # Track selectors for unused check
                    self.used_selectors.add(selector)
        except Exception as e:
            self.issues.append(make_issue('CSS_PARSING_ERROR', source, f"CSS parsing error: {str(e)}", line=find_line_number_in_text(css_content, '/*')))

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
                                self.issues.append(make_issue('CSS_UNUSED_SELECTOR', css_url, f"Unused selector: {selector}", line=find_line_number_in_text(css_content, str(rule)), context=str(rule)))
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
                    self.issues.append(make_issue('JS_INLINE_EVENT_HANDLER', self.url, f"Inline event handler: {attr}", line=find_line_number_in_text(self.html_content, str(el)), context=str(el)))
        # ESLint integration (optional)
        if self.options.eslint and subprocess:
            for js_url, js_content in self.external_js:
                self._eslint_check(js_content, js_url)

    def _analyze_javascript(self, js_content, source):
        try:
            pyjsparser.parse(js_content)
        except Exception as e:
            self.issues.append(make_issue('JS_SYNTAX_ERROR', source, f"Syntax error: {str(e)}", line=find_line_number_in_text(js_content, '/*')))
        # Dangerous patterns
        dangerous_patterns = {
            'eval': r'\beval\s*\(',
            'innerHTML': r'\.innerHTML\s*=',
            'document.write': r'document\.write\s*\('
        }
        for pattern_name, pattern in dangerous_patterns.items():
            for match in re.finditer(pattern, js_content):
                line = find_line_number_in_text(js_content, match.group(0))
                snippet = match.group(0)
                self.issues.append(make_issue('JS_DANGEROUS_FUNCTION', source, f"Use of {pattern_name} detected", line=line, context=snippet))
        # Deprecated APIs
        deprecated_apis = ['escape(', 'unescape(', 'document.all', 'document.layers']
        for api in deprecated_apis:
            for match in re.finditer(api, js_content):
                line = find_line_number_in_text(js_content, match.group(0))
                snippet = match.group(0)
                self.issues.append(make_issue('JS_DEPRECATED_API', source, f"Deprecated API used: {api}", line=line, context=snippet))

    def _eslint_check(self, js_content, source):
        try:
            with open('temp_eslint.js', 'w', encoding='utf-8') as f:
                f.write(js_content)
            result = subprocess.run(['eslint', 'temp_eslint.js', '-f', 'json'], capture_output=True, text=True)
            if result.returncode != 0 and result.stdout:
                eslint_issues = json.loads(result.stdout)
                for file_issues in eslint_issues:
                    for msg in file_issues.get('messages', []):
                        self.issues.append(make_issue('JS_ESLINT', source, f"{msg.get('message')} (rule: {msg.get('ruleId')})", line=find_line_number_in_text(js_content, msg.get('line'))))
            os.remove('temp_eslint.js')
        except Exception as e:
            self.issues.append(make_issue('JS_ESLINT_ERROR', source, f"ESLint error: {str(e)}", line=find_line_number_in_text(js_content, '/*')))

    # --- Performance & Security ---
    def _analyze_perfsec(self):
        # Large files
        for url, content in self.external_css + self.external_js:
            if len(content) > 100*1024:
                self.issues.append(make_issue('PERF_LARGE_FILE', url, f"File size > 100KB ({len(content)} bytes)", line=find_line_number_in_text(content, '/*')))
        # Insecure requests
        for url, _ in self.external_css + self.external_js:
            if url.startswith('http://'):
                self.issues.append(make_issue('SEC_INSECURE_REQUEST', url, "Insecure HTTP resource", line=find_line_number_in_text(self.html_content, '/*')))
        # Inline scripts/styles
        for script in self.soup.find_all('script', src=False):
            if script.string and len(script.string) > 100:
                self.issues.append(make_issue('SEC_INLINE_SCRIPT', self.url, "Large inline script detected", line=find_line_number_in_text(self.html_content, str(script)), context=str(script)))
        for style in self.soup.find_all('style'):
            if style.string and len(style.string) > 100:
                self.issues.append(make_issue('SEC_INLINE_STYLE', self.url, "Large inline style detected", line=find_line_number_in_text(self.html_content, str(style)), context=str(style)))

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