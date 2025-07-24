# Static-Code-Analysis-tool

## Setup and Usage

### 1. Create and Activate a Virtual Environment

```
python3 -m venv venv
source venv/bin/activate
```

### 2. Install Dependencies

```
pip install -r requirements.txt
```

### 3. Run the Analyzer

```
python analyzer.py https://example.com
```

Replace `https://example.com` with the URL of the website you want to analyze.

---

## Features
- **HTML Analysis**: Checks for missing `alt` attributes in images and deprecated tags like `<center>`, `<font>`, and `<marquee>`.
- **CSS Analysis**: Identifies overuse of `!important` and flags complex CSS selectors (more than 3 levels). Parses both external and inline styles.
- **JavaScript Analysis**: Detects syntax errors using AST parsing and identifies dangerous patterns (`eval`, `innerHTML`, `document.write`).
- **Resource Handling**: Respects `robots.txt` restrictions, handles absolute/relative URLs, and uses a custom user-agent header.
- **Reporting**: Structured issue categorization, source location identification, and clear error messages.

---

## Example Output
```
Found 3 issues:
============================================================
1. [HTML_MISSING_ALT]
   Location: <img src="logo.png">
   Issue: Image missing alt text
------------------------------------------------------------
2. [CSS_IMPORTANT_OVERUSE]
   Location: https://example.com/style.css
   Issue: Use of !important in CSS
------------------------------------------------------------
3. [JS_DANGEROUS_FUNCTION]
   Location: https://example.com/script.js
   Issue: Use of eval detected
------------------------------------------------------------
```

---

## Notes
- This tool focuses on **client-side static analysis**. Server-side code cannot be analyzed without source access.
- For advanced JavaScript analysis, consider integrating ESLint (requires Node.js).
- The tool handles basic CSS/JS parsing errors but may not catch all edge cases.